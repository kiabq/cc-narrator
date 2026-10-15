"""Per-session loop. This is the only module that wires the other units together."""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path
from typing import Protocol

from .config import Config
from .control import (
    SessionState,
    announcer_lock,
    pid_alive,
    read_last_speaker,
    write_last_speaker,
)
from .events import announcement_line
from .focus import read_focus
from .label import git_branch, label_for
from .player import ANNOUNCER, NARRATOR
from .prose import chunk, to_speech
from .transcript import TranscriptReader
from .tts import TTS, TTSAuthError

log = logging.getLogger(__name__)
AUTH_FAILED_MESSAGE = "Narration disabled: ElevenLabs key rejected."


class PlayerLike(Protocol):
    def enqueue(self, channel: str, source: Callable[[], Iterable[bytes]]) -> None: ...
    def play_blocking(
        self, channel: str, source: Callable[[], Iterable[bytes]], timeout: float | None = None
    ) -> None: ...
    def clear(self, channel: str) -> None: ...
    def duck(self, channel: str, factor: float) -> None: ...
    def unduck(self, channel: str) -> None: ...


def say_aloud(text: str) -> None:
    """Fallback voice (macOS `say`) for when ElevenLabs itself is the problem."""
    try:
        subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        log.warning("could not run say")


class Watcher:
    def __init__(
        self,
        session: SessionState,
        root: Path,
        config: Config,
        tts: TTS,
        player: PlayerLike,
        reader: TranscriptReader,
        announce: Callable[[str], None],
        *,
        now: Callable[[], float] = time.time,
        branch_lookup: Callable[[str], str | None] = git_branch,
        say: Callable[[str], None] = say_aloud,
    ):
        meta = session.read_meta()
        if meta is None:
            raise ValueError(f"session {session.session_id} has no meta.json")
        self.session = session
        self._meta = meta
        self._root = root
        self._config = config
        self._tts = tts
        self._player = player
        self._reader = reader
        self._announce = announce
        self._now = now
        self._branch_lookup = branch_lookup
        self._say = say
        self._speaking = False
        self._auth_reported = False

    def label(self) -> str:
        return label_for(
            self._meta.session_id, self._meta.session_title, self._meta.cwd, self._branch_lookup
        )

    def tick(self) -> bool:
        sid = self.session.session_id
        if not self.session.exists():
            return False
        if self._meta.claude_pid is not None and not pid_alive(self._meta.claude_pid):
            return False

        if self.session.take_clear():
            self._player.clear(NARRATOR)
        current = read_focus(self._root) == sid
        speaking = current and self.session.is_enabled()
        if self._speaking and not speaking:
            self._player.clear(NARRATOR)
        self._speaking = speaking

        for block in self._reader.read_new():
            if speaking:
                self._narrate(block.text)
        if self._reader.deleted:
            return False

        for item in self.session.take_announcements():
            if current or self._now() - item.ts > self._config.announce_max_age_seconds:
                continue
            line = announcement_line(item.event, self.label())
            if line:
                self._announce(line)
        return True

    def run(self, interval: float = 0.1, sleep: Callable[[float], None] = time.sleep) -> None:
        while self.tick():
            sleep(interval)
        log.info("watcher for %s exiting", self.session.session_id)

    def handle_player_error(self, channel: str, exc: BaseException) -> None:
        if isinstance(exc, TTSAuthError):
            self.session.set_enabled(False)
            if not self._auth_reported:
                self._auth_reported = True
                self._say(AUTH_FAILED_MESSAGE)
        else:
            log.warning("%s playback error: %s", channel, exc)

    def _narrate(self, markdown: str) -> None:
        text = to_speech(markdown)
        if not text:
            return
        sid = self.session.session_id
        if read_last_speaker(self._root) != sid:
            text = f"{self.label()}: {text}"
            write_last_speaker(self._root, sid)
        voice = self._config.narrator_voice_id
        for piece in chunk(text):
            self._player.enqueue(NARRATOR, partial(self._tts.synthesize, piece, voice))


def play_announcement(
    text: str,
    player: PlayerLike,
    tts: TTS,
    voice_id: str,
    root: Path,
    lock_timeout: float = 30.0,
    duck_factor: float = 0.5,
) -> bool:
    with announcer_lock(root, lock_timeout) as acquired:
        if not acquired:
            log.info("announcer busy; dropping %r", text)
            return False
        player.duck(NARRATOR, duck_factor)
        try:
            player.play_blocking(ANNOUNCER, partial(tts.synthesize, text, voice_id))
        finally:
            player.unduck(NARRATOR)
    return True


class AnnouncerWorker:
    """Plays announcements off the watcher thread so the loop keeps ticking while one waits."""

    def __init__(self, play: Callable[[str], object]):
        self._play = play
        self._queue: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._run, name="announcer", daemon=True).start()

    def submit(self, line: str) -> None:
        self._queue.put(line)

    def _run(self) -> None:
        while True:
            line = self._queue.get()
            try:
                self._play(line)
            except Exception:
                log.exception("announcement failed")
