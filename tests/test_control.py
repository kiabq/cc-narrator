import os
import time

from cc_narrator.control import (
    Announcement,
    SessionMeta,
    SessionState,
    announcer_lock,
    atomic_write,
    cleanup_stale,
    list_sessions,
    pid_alive,
    read_last_speaker,
    watcher_running,
    write_last_speaker,
)


def meta(session_id="s1", started_at=1000.0, claude_pid=None):
    return SessionMeta(
        session_id=session_id,
        transcript_path="/tmp/t.jsonl",
        cwd="/tmp",
        session_title=None,
        claude_pid=claude_pid,
        started_at=started_at,
    )


def test_atomic_write_creates_and_replaces(tmp_path):
    path = tmp_path / "a" / "b.txt"
    atomic_write(path, "one")
    atomic_write(path, "two")
    assert path.read_text() == "two"
    assert [p.name for p in path.parent.iterdir()] == ["b.txt"]


def test_pid_alive(dead_pid):
    assert pid_alive(os.getpid())
    assert not pid_alive(dead_pid)
    assert not pid_alive(0)


def test_watcher_running_requires_marker(fake_watcher, dead_pid):
    assert watcher_running(fake_watcher().pid)
    assert not watcher_running(os.getpid())  # alive but not a watcher
    assert not watcher_running(dead_pid)


def test_session_create_exists_remove(tmp_path):
    session = SessionState(tmp_path, "s1")
    assert not session.exists()
    session.create()
    assert session.exists()
    assert session.dir == tmp_path / "sessions" / "s1"
    session.remove()
    assert not session.exists()


def test_meta_round_trip(tmp_path):
    session = SessionState(tmp_path, "s1")
    session.create()
    session.write_meta(meta(claude_pid=42))
    assert session.read_meta() == meta(claude_pid=42)


def test_read_meta_missing_or_corrupt(tmp_path):
    session = SessionState(tmp_path, "s1")
    assert session.read_meta() is None
    session.create()
    (session.dir / "meta.json").write_text("{not json")
    assert session.read_meta() is None


def test_pid_and_watcher_alive(tmp_path, fake_watcher, dead_pid):
    session = SessionState(tmp_path, "s1")
    session.create()
    assert session.read_pid() is None
    assert not session.watcher_alive()
    session.write_pid(dead_pid)
    assert not session.watcher_alive()
    session.write_pid(fake_watcher().pid)
    assert session.watcher_alive()


def test_enabled_flag(tmp_path):
    session = SessionState(tmp_path, "s1")
    session.create()
    assert not session.is_enabled()
    session.set_enabled(True)
    assert session.is_enabled()
    session.set_enabled(False)
    assert not session.is_enabled()
    session.set_enabled(False)  # idempotent


def test_clear_signal_is_taken_once(tmp_path):
    session = SessionState(tmp_path, "s1")
    session.create()
    assert not session.take_clear()
    session.request_clear()
    assert session.take_clear()
    assert not session.take_clear()


def test_announcements_append_and_take(tmp_path):
    session = SessionState(tmp_path, "s1")
    session.create()
    session.add_announcement("Stop", 1.0)
    session.add_announcement("StopFailure", 2.0)
    with (session.dir / "announce").open("a") as fh:
        fh.write("garbage\n")
    assert session.take_announcements() == [
        Announcement("Stop", 1.0),
        Announcement("StopFailure", 2.0),
    ]
    assert session.take_announcements() == []


def test_list_sessions(tmp_path):
    SessionState(tmp_path, "a").create()
    SessionState(tmp_path, "b").create()
    assert sorted(s.session_id for s in list_sessions(tmp_path)) == ["a", "b"]
    assert list_sessions(tmp_path / "nothing") == []


def test_cleanup_stale(tmp_path, fake_watcher, dead_pid):
    now = 1_000_000.0
    old, recent, alive = (SessionState(tmp_path, n) for n in ("old", "recent", "alive"))
    for session, started in ((old, now - 90_000), (recent, now - 60), (alive, now - 90_000)):
        session.create()
        session.write_meta(meta(session.session_id, started_at=started))
        session.write_pid(dead_pid)
    alive.write_pid(fake_watcher().pid)

    removed = cleanup_stale(tmp_path, now)

    assert removed == ["old"]
    assert not old.exists()
    assert recent.exists()
    assert alive.exists()


def test_last_speaker(tmp_path):
    assert read_last_speaker(tmp_path) is None
    write_last_speaker(tmp_path, "s1")
    assert read_last_speaker(tmp_path) == "s1"


def test_announcer_lock_is_exclusive(tmp_path):
    with announcer_lock(tmp_path, timeout=1.0) as first:
        assert first
        start = time.monotonic()
        with announcer_lock(tmp_path, timeout=0.1) as second:
            assert not second
        assert time.monotonic() - start >= 0.1
    with announcer_lock(tmp_path, timeout=0.1) as third:
        assert third


def test_undecodable_files_do_not_raise(tmp_path):
    import pytest

    from cc_narrator.control import SessionState, list_sessions
    from cc_narrator.focus import read_focus

    (tmp_path / "focus").write_bytes(b"\xff\xfe\x80")
    assert read_focus(tmp_path) is None
    s = SessionState(tmp_path, "abc")
    s.create()
    (s.dir / "meta.json").write_bytes(b"\xff\xfe")
    assert s.read_meta() is None
    (s.dir / "announce").write_bytes(b"\xff\xfe\n")
    assert s.take_announcements() == []
    assert not (s.dir / "announce.taking").exists()
    assert [x.session_id for x in list_sessions(tmp_path)] == ["abc"]
    del pytest


def test_session_id_validation(tmp_path):
    import pytest

    from cc_narrator.control import SessionState

    for bad in ("", "a/b", "a\\b", "a\0b", ".hidden", "..", "../x"):
        with pytest.raises(ValueError):
            SessionState(tmp_path, bad)
    SessionState(tmp_path, "ok-id_1")


def test_list_sessions_skips_invalid_dir_names(tmp_path):
    from cc_narrator.control import list_sessions

    (tmp_path / "sessions" / ".hidden").mkdir(parents=True)
    (tmp_path / "sessions" / "good").mkdir()
    assert [s.session_id for s in list_sessions(tmp_path)] == ["good"]
