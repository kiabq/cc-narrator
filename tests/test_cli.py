import subprocess
import sys

from claude_voice_augmented.cli import cmd_narrate, main
from claude_voice_augmented.control import SessionMeta, SessionState
from claude_voice_augmented.focus import read_focus, write_focus


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
    monkeypatch.setattr("claude_voice_augmented.cli.DEFAULT_ROOT", tmp_path)
    assert main(["watch", "missing"]) == 1


def test_cli_entry_point_help():
    result = subprocess.run(
        [sys.executable, "-m", "claude_voice_augmented", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    for command in ("hook", "watch", "narrate", "doctor", "say"):
        assert command in result.stdout
