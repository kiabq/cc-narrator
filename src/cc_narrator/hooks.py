"""Claude Code hook entry point. Must stay fast and must never fail the session."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from .config import DEFAULT_ENV_PATH, Config, load_config
from .control import (
    DEFAULT_ROOT,
    SessionMeta,
    SessionState,
    cleanup_stale,
    list_sessions,
    logs_dir,
    watcher_running,
)
from .events import ANNOUNCED_EVENTS
from .focus import read_focus, write_focus


def spawn_watcher(session_id: str) -> int:
    """Start `python -m cc_narrator watch <id>` fully detached (like nohup … &)."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "cc_narrator", "watch", session_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    return proc.pid


def stop_watcher(session: SessionState) -> None:
    pid = session.read_pid()
    if pid is not None and watcher_running(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _ps_lookup(pid: int) -> tuple[int, str] | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True, timeout=1
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = result.stdout.strip().split(None, 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), parts[1]
    except ValueError:
        return None


def find_claude_pid(
    start_pid: int | None = None,
    ps: Callable[[int], tuple[int, str] | None] = _ps_lookup,
    max_depth: int = 6,
) -> int | None:
    pid = os.getppid() if start_pid is None else start_pid
    for _ in range(max_depth):
        info = ps(pid)
        if info is None:
            return None
        parent, command = info
        if os.path.basename(command) == "claude":
            return pid
        if parent <= 1:
            return None
        pid = parent
    return None


def _ensure_watcher(
    payload: dict,
    session: SessionState,
    root: Path,
    config: Config,
    spawn: Callable[[str], int],
    now: float,
    claude_pid: Callable[[], int | None],
) -> None:
    if session.exists() and session.watcher_alive():
        return
    is_new = not session.exists()
    pid = claude_pid()
    if pid is not None:
        # After /clear or a resume, the old session from this same Claude Code process is over.
        for other in list_sessions(root):
            meta = other.read_meta()
            if other.session_id != session.session_id and meta and meta.claude_pid == pid:
                stop_watcher(other)
                other.remove()
    session.create()
    previous = session.read_meta()
    session.write_meta(
        SessionMeta(
            session_id=session.session_id,
            transcript_path=str(
                payload.get("transcript_path") or (previous.transcript_path if previous else "")
            ),
            cwd=str(payload.get("cwd") or (previous.cwd if previous else os.getcwd())),
            session_title=payload.get("session_title")
            or (previous.session_title if previous else None),
            claude_pid=pid,
            started_at=now,
        )
    )
    if is_new:
        session.set_enabled(config.enabled_by_default)
    session.write_pid(spawn(session.session_id))


def handle(
    payload: dict,
    *,
    root: Path,
    config: Config,
    spawn: Callable[[str], int],
    now: float,
    claude_pid: Callable[[], int | None],
) -> dict | None:
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if not isinstance(event, str) or not isinstance(session_id, str) or not session_id:
        return None
    try:
        session = SessionState(root, session_id)
    except ValueError:
        return None

    if event == "SessionStart":
        cleanup_stale(root, now)
        if not config.is_valid:
            missing = ", ".join(config.missing)
            return {"systemMessage": f"Narration off: {missing} not set in {DEFAULT_ENV_PATH}."}
        _ensure_watcher(payload, session, root, config, spawn, now, claude_pid)
    elif event == "UserPromptSubmit":
        write_focus(root, session_id)
        if config.is_valid:
            _ensure_watcher(payload, session, root, config, spawn, now, claude_pid)
        if session.exists():
            session.request_clear()
    elif event in ANNOUNCED_EVENTS:
        if session.exists() and read_focus(root) != session_id:
            session.add_announcement(event, now)
    elif event == "SessionEnd":
        stop_watcher(session)
        session.remove()
    return None


def _log_failure(root: Path) -> None:
    try:
        logs = logs_dir(root)
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "hooks.log").open("a") as fh:
            fh.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}\n")
    except Exception:
        pass


def main(
    stdin: TextIO | None = None, stdout: TextIO | None = None, root: Path | None = None
) -> int:
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    root = DEFAULT_ROOT if root is None else root
    try:
        payload = json.load(stdin)
        if isinstance(payload, dict):
            result = handle(
                payload,
                root=root,
                config=load_config(),
                spawn=spawn_watcher,
                now=time.time(),
                claude_pid=find_claude_pid,
            )
            if result:
                json.dump(result, stdout)
    except Exception:
        _log_failure(root)
    return 0
