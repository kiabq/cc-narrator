"""`cc-narrate` command line: hook entry point, watcher process, and manual tools."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
from functools import partial
from pathlib import Path

from .config import DEFAULT_ENV_PATH, load_config
from .control import DEFAULT_ROOT, SessionState, logs_dir
from .focus import read_focus, write_focus
from .label import label_for

NO_SESSION = "No narrator is running for this session."


def cmd_narrate(action: str, session_id: str, root: Path) -> str:
    # An unsubstituted "${CLAUDE_SESSION_ID}" or empty value falls back to the current session.
    sid = session_id if session_id and not session_id.startswith("$") else read_focus(root) or ""
    try:
        session = SessionState(root, sid) if sid else None
    except ValueError:
        session = None
    if session is None or not session.exists():
        return NO_SESSION
    meta = session.read_meta()
    label = label_for(sid, meta.session_title if meta else None, meta.cwd if meta else None)
    if action == "on":
        session.set_enabled(True)
        return f"Narration on for {label}."
    if action == "off":
        session.set_enabled(False)
        session.request_clear()
        return f"Narration off for {label}."
    write_focus(root, sid)
    return f"Now narrating {label}."


def _setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def cmd_watch(session_id: str) -> int:
    root = DEFAULT_ROOT
    session = SessionState(root, session_id)
    meta = session.read_meta()
    if meta is None:
        return 1
    _setup_logging(logs_dir(root) / f"{session_id}.log")
    try:
        config = load_config()
        if not config.is_valid:
            logging.error("config invalid; missing %s", ", ".join(config.missing))
            return 1

        from .player import Player
        from .transcript import TranscriptReader
        from .tts import ElevenLabsTTS
        from .watcher import AnnouncerWorker, Watcher, play_announcement

        tts = ElevenLabsTTS(config.api_key, config.tts_model)
        watchers: list[Watcher] = []

        def on_error(channel: str, exc: BaseException) -> None:
            if watchers:
                watchers[0].handle_player_error(channel, exc)

        player = Player(config.narrator_volume, config.announcer_volume, on_error)
        worker = AnnouncerWorker(
            lambda line: play_announcement(line, player, tts, config.announcer_voice_id, root)
        )
        watcher = Watcher(
            session, root, config, tts, player, TranscriptReader(Path(meta.transcript_path)),
            worker.submit,
        )
        watchers.append(watcher)
        logging.info("watching %s (%s)", session_id, meta.transcript_path)
        watcher.run()
        return 0
    except Exception:
        logging.exception("watcher for %s crashed", session_id)
        return 1


def cmd_doctor() -> int:
    state = "found" if DEFAULT_ENV_PATH.is_file() else "missing"
    print(f"Config file: {DEFAULT_ENV_PATH} ({state})")
    config = load_config()
    if config.missing:
        print(f"Missing settings: {', '.join(config.missing)}")
        return 1

    from .tts import ElevenLabsTTS, TTSError

    tts = ElevenLabsTTS(config.api_key, config.tts_model)
    ok = True
    voices = (("Narrator", config.narrator_voice_id), ("Announcer", config.announcer_voice_id))
    for name, voice in voices:
        try:
            found = tts.voice_exists(voice)
        except TTSError as exc:
            print(f"{name} voice {voice}: error ({exc})")
            ok = False
            continue
        print(f"{name} voice {voice}: {'ok' if found else 'NOT FOUND'}")
        ok = ok and found
    try:
        import sounddevice as sd

        print(f"Output device: {sd.query_devices(kind='output')['name']}")
    except Exception as exc:
        print(f"Output device: error ({exc})")
        ok = False
    return 0 if ok else 1


def cmd_say(text: str, announcer: bool) -> int:
    config = load_config()
    if config.missing:
        print(f"Missing settings: {', '.join(config.missing)}")
        return 1

    from .player import ANNOUNCER, NARRATOR, Player
    from .tts import ElevenLabsTTS

    errors: list[BaseException] = []
    tts = ElevenLabsTTS(config.api_key, config.tts_model)
    player = Player(
        config.narrator_volume, config.announcer_volume, lambda ch, exc: errors.append(exc)
    )
    if announcer:
        channel, voice = ANNOUNCER, config.announcer_voice_id
    else:
        channel, voice = NARRATOR, config.narrator_voice_id
    player.play_blocking(channel, partial(tts.synthesize, text, voice), timeout=60)
    player.close()
    if errors:
        print(f"Playback failed: {errors[0]}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cc-narrate", description="Narrate Claude Code sessions.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hook", help="handle a Claude Code hook event (JSON on stdin)")
    watch = sub.add_parser("watch", help="run the watcher for one session")
    watch.add_argument("session_id")
    narrate = sub.add_parser("narrate", help="turn narration on/off or make a session current")
    narrate.add_argument("action", choices=["on", "off", "focus"])
    narrate.add_argument("--session", default="")
    sub.add_parser("doctor", help="check API key, voices, and audio device")
    say = sub.add_parser("say", help="speak a test phrase")
    say.add_argument("text")
    say.add_argument("--announcer", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "hook":
        from .hooks import main as hook_main

        return hook_main()
    if args.command == "watch":
        return cmd_watch(args.session_id)
    if args.command == "narrate":
        print(cmd_narrate(args.action, args.session, DEFAULT_ROOT))
        return 0
    if args.command == "doctor":
        return cmd_doctor()
    return cmd_say(args.text, args.announcer)
