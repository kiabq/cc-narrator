"""File-based state shared by hooks and watchers under ~/.cache/cc-narrator/."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".cache" / "cc-narrator"
WATCHER_MARKER = "cc_narrator"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_command(pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=1
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def watcher_running(pid: int) -> bool:
    """True only for a live process that is one of our watchers (guards against PID reuse)."""
    return pid_alive(pid) and WATCHER_MARKER in (process_command(pid) or "")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def valid_session_id(session_id: str) -> bool:
    return bool(session_id) and not (
        any(c in session_id for c in "/\\\0") or session_id.startswith(".")
    )


@dataclass(frozen=True)
class SessionMeta:
    session_id: str
    transcript_path: str
    cwd: str
    session_title: str | None
    claude_pid: int | None
    started_at: float


@dataclass(frozen=True)
class Announcement:
    event: str
    ts: float


class SessionState:
    def __init__(self, root: Path, session_id: str):
        if not valid_session_id(session_id):
            raise ValueError(f"invalid session id: {session_id!r}")
        self.session_id = session_id
        self.dir = root / "sessions" / session_id

    def exists(self) -> bool:
        return self.dir.is_dir()

    def create(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def remove(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def write_meta(self, meta: SessionMeta) -> None:
        atomic_write(self.dir / "meta.json", json.dumps(asdict(meta)))

    def read_meta(self) -> SessionMeta | None:
        raw = _read_text(self.dir / "meta.json")
        if raw is None:
            return None
        try:
            return SessionMeta(**json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            return None

    def write_pid(self, pid: int) -> None:
        atomic_write(self.dir / "watcher.pid", str(pid))

    def read_pid(self) -> int | None:
        raw = _read_text(self.dir / "watcher.pid")
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    def watcher_alive(self) -> bool:
        pid = self.read_pid()
        return pid is not None and watcher_running(pid)

    def is_enabled(self) -> bool:
        return (self.dir / "enabled").exists()

    def set_enabled(self, on: bool) -> None:
        flag = self.dir / "enabled"
        if on:
            atomic_write(flag, "")
        else:
            flag.unlink(missing_ok=True)

    def request_clear(self) -> None:
        atomic_write(self.dir / "clear", "")

    def take_clear(self) -> bool:
        try:
            (self.dir / "clear").unlink()
        except FileNotFoundError:
            return False
        return True

    def add_announcement(self, event: str, ts: float) -> None:
        # One short line per write; appends of this size are atomic.
        with (self.dir / "announce").open("a") as fh:
            fh.write(json.dumps({"event": event, "ts": ts}) + "\n")

    def take_announcements(self) -> list[Announcement]:
        path = self.dir / "announce"
        taking = self.dir / "announce.taking"
        try:
            os.replace(path, taking)
        except FileNotFoundError:
            return []
        items: list[Announcement] = []
        text = taking.read_bytes().decode("utf-8", errors="replace")
        for line in text.splitlines():
            try:
                data = json.loads(line)
                items.append(Announcement(str(data["event"]), float(data["ts"])))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        taking.unlink(missing_ok=True)
        return items


def list_sessions(root: Path) -> list[SessionState]:
    base = root / "sessions"
    if not base.is_dir():
        return []
    return [
        SessionState(root, p.name)
        for p in base.iterdir()
        if p.is_dir() and valid_session_id(p.name)
    ]


def cleanup_stale(root: Path, now: float, max_age: float = 86400.0) -> list[str]:
    removed: list[str] = []
    for session in list_sessions(root):
        if session.watcher_alive():
            continue
        meta = session.read_meta()
        started = meta.started_at if meta else session.dir.stat().st_mtime
        if now - started > max_age:
            session.remove()
            removed.append(session.session_id)
    return removed


def read_last_speaker(root: Path) -> str | None:
    return _read_text(root / "last_speaker")


def write_last_speaker(root: Path, session_id: str) -> None:
    atomic_write(root / "last_speaker", session_id)


def logs_dir(root: Path) -> Path:
    return root / "logs"


@contextmanager
def announcer_lock(root: Path, timeout: float, poll: float = 0.05) -> Iterator[bool]:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "announcer.lock", "a") as fh:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(poll)
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
