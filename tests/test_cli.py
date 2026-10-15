import subprocess
import sys

from cc_narrator.cli import cmd_narrate, main
from cc_narrator.control import SessionMeta, SessionState
from cc_narrator.focus import read_focus, write_focus


def make_session(root, sid="639b0000", cwd="/nonexistent"):
    session = SessionState(root, sid)
    session.create()
    session.write_meta(SessionMeta(sid, "/tmp/t.jsonl", cwd, None, None, 0.0))
    return session


def test_narrate_off_and_on(tmp_path):
    session = make_session(tmp_path)
    session.set_enabled(True)
    assert cmd_narrate("off", "639b0000", tmp_path) == "Narration off for six-three-nine-bravo."
    assert not session.is_enabled()
    assert session.take_clear()
    assert cmd_narrate("on", "639b0000", tmp_path) == "Narration on for six-three-nine-bravo."
    assert session.is_enabled()


def test_narrate_focus(tmp_path):
    make_session(tmp_path)
    write_focus(tmp_path, "other")
    assert cmd_narrate("focus", "639b0000", tmp_path) == "Now narrating six-three-nine-bravo."
    assert read_focus(tmp_path) == "639b0000"


def test_narrate_falls_back_to_focus_when_id_missing_or_unsubstituted(tmp_path):
    session = make_session(tmp_path)
    write_focus(tmp_path, "639b0000")
    cmd_narrate("off", "", tmp_path)
    assert not session.is_enabled()
    cmd_narrate("on", "${CLAUDE_SESSION_ID}", tmp_path)
    assert session.is_enabled()


def test_narrate_unknown_session(tmp_path):
    assert cmd_narrate("on", "nope", tmp_path) == "No narrator is running for this session."
    assert cmd_narrate("on", "", tmp_path) == "No narrator is running for this session."


def test_watch_without_session_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("cc_narrator.cli.DEFAULT_ROOT", tmp_path)
    assert main(["watch", "missing"]) == 1


def test_cli_entry_point_help():
    result = subprocess.run(
        [sys.executable, "-m", "cc_narrator", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    for command in ("hook", "watch", "narrate", "doctor", "say"):
        assert command in result.stdout


def test_watch_crash_is_logged_and_returns_1(tmp_path, monkeypatch):
    import logging

    monkeypatch.setattr("cc_narrator.cli.DEFAULT_ROOT", tmp_path)
    make_session(tmp_path, "crashy")

    def boom():
        raise RuntimeError("kaboom-marker")

    monkeypatch.setattr("cc_narrator.cli.load_config", boom)
    try:
        assert main(["watch", "crashy"]) == 1
    finally:
        for handler in logging.getLogger().handlers[:]:
            handler.flush()
            logging.getLogger().removeHandler(handler)
            handler.close()
    log = (tmp_path / "logs" / "crashy.log").read_text()
    assert "Traceback" in log and "kaboom-marker" in log


def test_narrate_invalid_session_id(tmp_path):
    assert cmd_narrate("on", "../x", tmp_path) == "No narrator is running for this session."


VOICE_ENV = (
    "ELEVENLABS_API_KEY=k\nCC_NARRATOR_NARRATOR_VOICE_ID=n0\nCC_NARRATOR_ANNOUNCER_VOICE_ID=a0\n"
)


def test_voice_without_args_shows_both(tmp_path):
    from cc_narrator.cli import cmd_voice

    path = tmp_path / ".env"
    path.write_text(VOICE_ENV)
    message, code = cmd_voice("", "", path, env={}, check=lambda v: True)
    assert code == 0
    assert "Narrator voice: n0" in message and "Announcer voice: a0" in message


def test_voice_sets_checked_id(tmp_path):
    from cc_narrator.cli import cmd_voice
    from cc_narrator.config import load_config

    path = tmp_path / ".env"
    path.write_text(VOICE_ENV)
    message, code = cmd_voice("narrator", "n1", path, env={}, check=lambda v: v == "n1")
    assert code == 0 and message == "Narrator voice set to n1."
    assert load_config(env={}, env_path=path).narrator_voice_id == "n1"


def test_voice_rejects_unknown_id(tmp_path):
    from cc_narrator.cli import cmd_voice

    path = tmp_path / ".env"
    path.write_text(VOICE_ENV)
    message, code = cmd_voice("announcer", "bad", path, env={}, check=lambda v: False)
    assert code == 1 and "not found" in message
    assert "a0" in path.read_text()


def test_voice_warns_when_environment_overrides(tmp_path):
    from cc_narrator.cli import cmd_voice

    path = tmp_path / ".env"
    path.write_text(VOICE_ENV)
    env = {"CC_NARRATOR_NARRATOR_VOICE_ID": "shell"}
    message, code = cmd_voice("narrator", "n1", path, env=env, check=lambda v: True)
    assert code == 0 and "CC_NARRATOR_NARRATOR_VOICE_ID" in message and "overrides" in message


def test_voice_role_without_id_is_an_error(tmp_path):
    from cc_narrator.cli import cmd_voice

    message, code = cmd_voice("narrator", "", tmp_path / ".env", env={}, check=lambda v: True)
    assert code == 1
