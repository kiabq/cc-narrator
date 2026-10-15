import json
import os

import pytest

from cc_narrator.config import Config
from cc_narrator.control import (
    SessionMeta,
    SessionState,
    announcer_lock,
    read_last_speaker,
    write_last_speaker,
)
from cc_narrator.focus import write_focus
from cc_narrator.player import ANNOUNCER, NARRATOR
from cc_narrator.transcript import TranscriptReader
from cc_narrator.tts import TTSAuthError
from cc_narrator.watcher import Watcher, play_announcement

SID = "639b1bcb-0000"
LABEL = "six-three-nine-bravo"
CONFIG = Config(api_key="k", narrator_voice_id="nv", announcer_voice_id="av")


class FakeTTS:
    def synthesize(self, text, voice_id):
        return iter([f"{voice_id}|{text}".encode()])


class FakePlayer:
    def __init__(self):
        self.calls = []

    def enqueue(self, channel, source):
        self.calls.append(("enqueue", channel, b"".join(source()).decode()))

    def play_blocking(self, channel, source, timeout=None):
        self.calls.append(("play", channel, b"".join(source()).decode()))

    def clear(self, channel):
        self.calls.append(("clear", channel))

    def duck(self, channel, factor):
        self.calls.append(("duck", channel, factor))

    def unduck(self, channel):
        self.calls.append(("unduck", channel))

    def spoken(self):
        return [c[2] for c in self.calls if c[0] == "enqueue"]


class Env:
    def __init__(self, tmp_path, clock):
        self.root = tmp_path / "state"
        self.transcript = tmp_path / "t.jsonl"
        self.transcript.touch()
        self.session = SessionState(self.root, SID)
        self.session.create()
        self.session.write_meta(
            SessionMeta(SID, str(self.transcript), str(tmp_path), None, os.getpid(), 0.0)
        )
        self.session.set_enabled(True)
        write_focus(self.root, SID)
        self.player = FakePlayer()
        self.announced = []
        self.said = []
        self.clock = clock
        self.watcher = Watcher(
            self.session,
            self.root,
            CONFIG,
            FakeTTS(),
            self.player,
            TranscriptReader(self.transcript),
            self.announced.append,
            now=lambda: self.clock[0],
            branch_lookup=lambda cwd: None,
            say=self.said.append,
        )

    def write(self, uuid, text):
        entry = {"type": "assistant", "uuid": uuid,
                 "message": {"content": [{"type": "text", "text": text}]}}
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path, clock=[1000.0])


def test_first_block_is_labelled_then_not(env):
    env.write("a", "Hello **there**.")
    assert env.watcher.tick()
    env.write("b", "Second.")
    env.watcher.tick()
    assert env.player.spoken() == [f"nv|{LABEL}: Hello there.", "nv|Second."]
    assert read_last_speaker(env.root) == SID


def test_label_repeats_after_another_session_spoke(env):
    write_last_speaker(env.root, "other")
    env.write("a", "Back.")
    env.watcher.tick()
    assert env.player.spoken() == [f"nv|{LABEL}: Back."]


def test_unfocused_session_is_silent_and_does_not_replay(env):
    write_focus(env.root, "other")
    env.write("a", "Missed.")
    env.watcher.tick()
    write_focus(env.root, SID)
    env.watcher.tick()
    assert env.player.spoken() == []


def test_disabled_session_is_silent(env):
    env.session.set_enabled(False)
    env.write("a", "Quiet.")
    env.watcher.tick()
    assert env.player.spoken() == []


def test_losing_focus_clears_narration(env):
    env.watcher.tick()
    write_focus(env.root, "other")
    env.watcher.tick()
    env.watcher.tick()
    assert env.player.calls.count(("clear", NARRATOR)) == 1


def test_clear_signal_clears_narration(env):
    env.session.request_clear()
    env.watcher.tick()
    assert ("clear", NARRATOR) in env.player.calls


def test_code_only_block_is_silent(env):
    # Review Focus 4
    env.write("a", "```python\nprint('hi')\n```")
    env.watcher.tick()
    assert env.player.spoken() == []
    assert read_last_speaker(env.root) is None


def test_long_block_is_split_into_clips(env):
    # Review Focus 3
    env.write("a", " ".join(f"This is sentence number {i} of a long reply." for i in range(40)))
    env.watcher.tick()
    clips = env.player.spoken()
    assert len(clips) > 1
    assert all(len(c) <= 400 + len(f"nv|{LABEL}: ") for c in clips)


def test_fresh_announcement_spoken_with_label(env):
    write_focus(env.root, "other")
    env.session.add_announcement("Stop", 995.0)
    env.watcher.tick()
    assert env.announced == [f"{LABEL} finished."]


def test_stale_announcement_dropped(env):
    write_focus(env.root, "other")
    env.session.add_announcement("Stop", 900.0)  # 100 s old, limit 60 s
    env.watcher.tick()
    assert env.announced == []


def test_current_session_never_announces(env):
    env.session.add_announcement("Stop", 999.0)
    env.watcher.tick()
    assert env.announced == []


def test_exits_when_session_dir_removed(env):
    env.session.remove()
    assert not env.watcher.tick()


def test_exits_when_transcript_deleted(env):
    env.transcript.unlink()
    assert not env.watcher.tick()


def test_exits_when_claude_process_gone(env, dead_pid):
    meta = env.session.read_meta()
    env.session.write_meta(SessionMeta(**{**meta.__dict__, "claude_pid": dead_pid}))
    watcher = Watcher(env.session, env.root, CONFIG, FakeTTS(), env.player,
                      TranscriptReader(env.transcript), env.announced.append,
                      branch_lookup=lambda cwd: None, say=env.said.append)
    assert not watcher.tick()


def test_auth_error_disables_session_and_says_once(env):
    env.watcher.handle_player_error(NARRATOR, TTSAuthError("401"))
    env.watcher.handle_player_error(NARRATOR, TTSAuthError("401"))
    assert not env.session.is_enabled()
    assert env.said == ["Narration disabled: ElevenLabs key rejected."]


def test_other_errors_do_not_disable(env):
    env.watcher.handle_player_error(NARRATOR, RuntimeError("blip"))
    assert env.session.is_enabled()
    assert env.said == []


def test_play_announcement_ducks_around_playback(tmp_path):
    player = FakePlayer()
    assert play_announcement("six finished.", player, FakeTTS(), "av", tmp_path)
    assert player.calls == [
        ("duck", NARRATOR, 0.5),
        ("play", ANNOUNCER, "av|six finished."),
        ("unduck", NARRATOR),
    ]


def test_play_announcement_gives_up_when_lock_busy(tmp_path):
    player = FakePlayer()
    with announcer_lock(tmp_path, timeout=1.0):
        assert not play_announcement("x", player, FakeTTS(), "av", tmp_path, lock_timeout=0.1)
    assert player.calls == []


def test_run_survives_tick_exceptions_until_failure_cap(env):
    sleeps = []

    def bad_tick():
        raise RuntimeError("boom")

    env.watcher.tick = bad_tick
    env.watcher.run(sleep=sleeps.append)
    assert len(sleeps) >= 49


def test_run_recovers_from_a_single_tick_exception(env):
    results = iter([RuntimeError("once"), False])

    def tick():
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    env.watcher.tick = tick
    sleeps = []
    env.watcher.run(sleep=sleeps.append)
    assert len(sleeps) == 1
