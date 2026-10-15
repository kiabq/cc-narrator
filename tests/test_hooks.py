import io
import json
import sys
import time

import pytest

from claude_voice_augmented.config import Config
from claude_voice_augmented.control import SessionMeta, SessionState, watcher_running
from claude_voice_augmented.focus import read_focus, write_focus
from claude_voice_augmented.hooks import find_claude_pid, handle, main

VALID = Config(api_key="k", narrator_voice_id="n", announcer_voice_id="a")
INVALID = Config(api_key="", narrator_voice_id="", announcer_voice_id="",
                 missing=("ELEVENLABS_API_KEY",))


class Spawner:
    def __init__(self, fake_watcher):
        self.calls = []
        self._fake_watcher = fake_watcher

    def __call__(self, session_id):
        self.calls.append(session_id)
        return self._fake_watcher().pid


@pytest.fixture
def spawn(fake_watcher):
    return Spawner(fake_watcher)


def payload(event, session_id="s1", **extra):
    return {"hook_event_name": event, "session_id": session_id,
            "transcript_path": f"/tmp/{session_id}.jsonl", "cwd": "/repo", **extra}


def run(event, tmp_path, spawn, config=VALID, session_id="s1", claude_pid=4242, now=1000.0,
        **extra):
    return handle(payload(event, session_id, **extra), root=tmp_path, config=config,
                  spawn=spawn, now=now, claude_pid=lambda: claude_pid)


def test_session_start_creates_state_and_spawns(tmp_path, spawn):
    result = run("SessionStart", tmp_path, spawn, session_title="Login work", source="startup")
    assert result is None
    session = SessionState(tmp_path, "s1")
    assert session.read_meta() == SessionMeta(
        "s1", "/tmp/s1.jsonl", "/repo", "Login work", 4242, 1000.0
    )
    assert session.is_enabled()
    assert spawn.calls == ["s1"]
    assert session.watcher_alive()


def test_session_start_respects_enabled_default(tmp_path, spawn):
    config = Config(api_key="k", narrator_voice_id="n", announcer_voice_id="a",
                    enabled_by_default=False)
    run("SessionStart", tmp_path, spawn, config=config)
    assert not SessionState(tmp_path, "s1").is_enabled()


def test_session_start_with_invalid_config_explains_and_does_nothing(tmp_path, spawn):
    result = run("SessionStart", tmp_path, spawn, config=INVALID)
    assert "ELEVENLABS_API_KEY" in result["systemMessage"]
    assert spawn.calls == []
    assert not SessionState(tmp_path, "s1").exists()


def test_session_start_does_not_duplicate_live_watcher(tmp_path, spawn):
    # Review Focus 5: compact / resume of the same session.
    run("SessionStart", tmp_path, spawn, source="startup")
    run("SessionStart", tmp_path, spawn, source="compact")
    assert spawn.calls == ["s1"]


def test_session_start_stops_previous_session_of_same_claude(tmp_path, spawn, fake_watcher):
    old = SessionState(tmp_path, "old")
    old.create()
    old.write_meta(SessionMeta("old", "/tmp/old.jsonl", "/repo", None, 4242, 900.0))
    proc = fake_watcher()
    old.write_pid(proc.pid)

    run("SessionStart", tmp_path, spawn, source="clear")

    assert proc.wait(timeout=2) is not None
    assert not old.exists()


def test_session_start_leaves_other_claude_sessions_alone(tmp_path, spawn, fake_watcher):
    other = SessionState(tmp_path, "other")
    other.create()
    other.write_meta(SessionMeta("other", "/tmp/o.jsonl", "/repo", None, 9999, 900.0))
    other.write_pid(fake_watcher().pid)
    run("SessionStart", tmp_path, spawn)
    assert other.exists() and other.watcher_alive()


def test_prompt_sets_focus_and_clears_queue(tmp_path, spawn):
    run("SessionStart", tmp_path, spawn)
    run("UserPromptSubmit", tmp_path, spawn, prompt="hi")
    assert read_focus(tmp_path) == "s1"
    assert SessionState(tmp_path, "s1").take_clear()
    assert spawn.calls == ["s1"]


def test_prompt_respawns_dead_watcher(tmp_path, spawn, dead_pid):
    run("SessionStart", tmp_path, spawn)
    SessionState(tmp_path, "s1").write_pid(dead_pid)
    run("UserPromptSubmit", tmp_path, spawn)
    assert spawn.calls == ["s1", "s1"]


def test_prompt_bootstraps_unknown_session(tmp_path, spawn):
    run("UserPromptSubmit", tmp_path, spawn, session_id="late")
    assert SessionState(tmp_path, "late").exists()
    assert spawn.calls == ["late"]


def test_events_from_other_sessions_are_queued(tmp_path, spawn):
    run("SessionStart", tmp_path, spawn)
    write_focus(tmp_path, "other")
    run("Stop", tmp_path, spawn, now=1234.0)
    [item] = SessionState(tmp_path, "s1").take_announcements()
    assert (item.event, item.ts) == ("Stop", 1234.0)


def test_events_from_current_session_are_not_queued(tmp_path, spawn):
    run("SessionStart", tmp_path, spawn)
    write_focus(tmp_path, "s1")
    run("PermissionRequest", tmp_path, spawn)
    assert SessionState(tmp_path, "s1").take_announcements() == []


def test_events_for_unknown_session_ignored(tmp_path, spawn):
    run("Stop", tmp_path, spawn, session_id="ghost")
    assert not SessionState(tmp_path, "ghost").exists()


def test_session_end_stops_watcher_and_removes_state(tmp_path, spawn):
    run("SessionStart", tmp_path, spawn)
    session = SessionState(tmp_path, "s1")
    pid = session.read_pid()
    run("SessionEnd", tmp_path, spawn)
    assert not session.exists()
    deadline = time.monotonic() + 2
    while watcher_running(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not watcher_running(pid)


def test_unknown_event_and_bad_payload(tmp_path, spawn):
    assert run("PreToolUse", tmp_path, spawn) is None
    assert handle({"hook_event_name": "Stop"}, root=tmp_path, config=VALID, spawn=spawn,
                  now=0.0, claude_pid=lambda: None) is None
    assert spawn.calls == []


def test_session_start_is_fast(tmp_path, spawn):
    start = time.perf_counter()
    run("SessionStart", tmp_path, spawn)
    assert time.perf_counter() - start < 0.1


def test_main_never_fails(tmp_path):
    out = io.StringIO()
    assert main(stdin=io.StringIO("{broken"), stdout=out, root=tmp_path) == 0
    assert out.getvalue() == ""
    assert (tmp_path / "logs" / "hooks.log").exists()


def test_main_prints_system_message(tmp_path, monkeypatch):
    monkeypatch.setattr("claude_voice_augmented.hooks.load_config", lambda: INVALID)
    out = io.StringIO()
    main(stdin=io.StringIO(json.dumps(payload("SessionStart"))), stdout=out, root=tmp_path)
    assert "systemMessage" in json.loads(out.getvalue())


def test_hooks_do_not_import_audio_or_http():
    import subprocess
    code = ("import sys, claude_voice_augmented.hooks; "
            "print([m for m in ('httpx', 'sounddevice') if m in sys.modules])")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == "[]"


def test_find_claude_pid_walks_ancestors():
    table = {10: (9, "/bin/zsh"), 9: (8, "/Users/me/.local/bin/claude"), 8: (1, "launchd")}
    assert find_claude_pid(10, ps=table.get) == 9


def test_find_claude_pid_none_when_absent():
    table = {10: (9, "zsh"), 9: (1, "login")}
    assert find_claude_pid(10, ps=table.get) is None
    assert find_claude_pid(10, ps=lambda pid: None) is None
