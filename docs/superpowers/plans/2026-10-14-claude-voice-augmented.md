# claude-voice-augmented Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code plugin plus Python package that narrates the current session's replies with ElevenLabs and announces other sessions' events on a quieter second voice.

**Architecture:** Plugin hooks call the `cva` CLI. Each Claude Code session gets a detached watcher process. The watcher tails that session's transcript JSONL, turns assistant text into speakable prose, and plays it on the narrator channel, but only if it is the current session (the one you last prompted). Hook events from other sessions are spoken as one-line announcements on the announcer channel. All coordination goes through small files under `~/.cache/claude-voice-augmented/`.

**Tech Stack:** Python ≥ 3.11, `uv`, `httpx`, `sounddevice`, `python-dotenv`, `pytest`, `ruff`. macOS only.

**Spec:** `docs/superpowers/specs/2026-10-14-claude-voice-augmented-design.md`

## Global Constraints

- Python `>=3.11`. Runtime dependencies are exactly `httpx`, `sounddevice`, `python-dotenv`. Dev: `pytest`, `ruff`.
- macOS only. Ghostty is the only target workspace in this version; no Superset code.
- Names: distribution and plugin `claude-voice-augmented`; import package `claude_voice_augmented`; CLI `claude-voice-augmented` with alias `cva`; slash command `/narrate`.
- State dir `~/.cache/claude-voice-augmented/`; config file `~/.config/claude-voice-augmented/.env`. Environment variables override the file. An empty environment variable does not override.
- Env keys and defaults: `ELEVENLABS_API_KEY` (required), `CVA_NARRATOR_VOICE_ID` (required), `CVA_ANNOUNCER_VOICE_ID` (required), `CVA_TTS_MODEL=eleven_flash_v2_5`, `CVA_NARRATOR_VOLUME=1.0`, `CVA_ANNOUNCER_VOLUME=0.4`, `CVA_ENABLED_BY_DEFAULT=true`, `CVA_ANNOUNCE_MAX_AGE_SECONDS=60`.
- Hooks always exit 0, catch every exception, and finish within 100 ms. Hook code must not import `httpx` or `sounddevice`.
- Audio: ElevenLabs `pcm_22050` (16-bit little-endian mono, 22050 Hz). ElevenLabs request timeout 5 s, retried once after 1 s on 429/5xx/timeout. 401/403 disables narration for the session and is reported once via macOS `say`.
- Watcher loop ~100 ms. Fade-out on clear ~100 ms. Announcements duck the narrator to 50%. Announcer lock wait 30 s.
- Short-ID label: first 4 alphanumeric characters of `session_id`, digits as words, letters in NATO alphabet, joined with `-`.
- Logs: `~/.cache/claude-voice-augmented/logs/<session_id>.log`, rotating 1 MB × 3. Stale session dirs: dead watcher and older than 24 h.
- Never narrate code blocks, tool calls, or tool output.
- Every commit ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

### Deliberate refinements of the spec

These close gaps found while planning. They don't change any behavior the spec asks for.

1. `meta.json` also stores `transcript_path`, because the watcher needs it and only hooks receive it.
2. Default branch names (`main`, `master`, `develop`, `trunk`) are skipped in the label chain, so many sessions in one repo don't all announce as "main".
3. A PID counts as "our watcher" only if it's alive and its command line contains `claude_voice_augmented`. This guards against sending SIGTERM to an unrelated process that reused a stale PID.
4. The `Notification` hook is registered only for the `idle_prompt` matcher. Permission prompts are announced through `PermissionRequest`, so one permission prompt produces one announcement, not two.
5. Long blocks are split into clips of at most 400 characters (on sentence boundaries), so first audio doesn't wait for the whole block to be synthesized.
6. `UserPromptSubmit` also bootstraps a session that never got `SessionStart`, for example when the plugin is installed mid-session.

## Review Focus

Failure modes the spec implies that are most likely to affect a real user. Each one is pinned by a test in the task named.

1. **One permission prompt fires both `Notification` and `PermissionRequest`.** Expect exactly one announcement. Pinned in Task 11 (`test_notification_only_matches_idle_prompt`).
2. **Several sessions in the same repo on `main`.** Expect distinct labels; fall back to the short ID instead of saying "main" for all of them. Pinned in Task 5 (`test_default_branch_falls_back_to_id`).
3. **A very long reply.** Expect it to start speaking quickly, not after synthesizing thousands of characters in one request. Pinned in Task 8 (`test_long_block_is_split_into_clips`).
4. **A block that is only code.** Expect silence, no label spoken, and `last_speaker` unchanged. Pinned in Task 8 (`test_code_only_block_is_silent`).
5. **`SessionStart` firing again for a live session** (`compact`, or resume of the same ID). Expect no second watcher. Pinned in Task 9 (`test_session_start_does_not_duplicate_live_watcher`).

---

## File Structure

```
claude-voice-augmented/
  pyproject.toml                       Task 1
  README.md                            Task 11
  .claude-plugin/marketplace.json      Task 11  (local marketplace → ./plugin)
  plugin/
    .claude-plugin/plugin.json         Task 11
    hooks/hooks.json                   Task 11
    commands/narrate.md                Task 11
  src/claude_voice_augmented/
    __init__.py                        Task 1
    __main__.py                        Task 1
    config.py                          Task 1   settings + SAMPLE_RATE
    control.py                         Task 2   state files, pids, lock, stale cleanup
    focus.py                           Task 2   current-session file
    transcript.py                      Task 3   JSONL tailer
    prose.py                           Task 4   markdown → speech, sentence chunking
    label.py                           Task 5   spoken session labels
    events.py                          Task 5   hook event → announcement line
    tts.py                             Task 6   ElevenLabs client
    player.py                          Task 7   two-channel audio
    watcher.py                         Task 8   per-session loop + announcements
    hooks.py                           Task 9   hook handling
    cli.py                             Task 1 (stub) / Task 10 (full)
  tests/
    fixtures/spike.jsonl               Task 3
    test_config.py                     Task 1
    test_control.py, test_focus.py     Task 2
    test_transcript.py                 Task 3
    test_prose.py                      Task 4
    test_label.py, test_events.py      Task 5
    test_tts.py                        Task 6
    test_player.py                     Task 7
    test_watcher.py                    Task 8
    test_hooks.py                      Task 9
    test_cli.py                        Task 10
    test_plugin.py, test_live.py       Task 11
```

Run all commands from the repo root: `/Users/box/Documents/Development/Repositories/claude-voice-augmented`.

---

### Task 1: Project scaffold and config

**Files:**
- Create: `pyproject.toml`, `src/claude_voice_augmented/__init__.py`, `src/claude_voice_augmented/__main__.py`, `src/claude_voice_augmented/cli.py`, `src/claude_voice_augmented/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `config.SAMPLE_RATE: int = 22050`
  - `config.DEFAULT_ENV_PATH: Path`
  - `config.REQUIRED_KEYS: tuple[str, ...]`
  - `@dataclass(frozen=True) Config(api_key, narrator_voice_id, announcer_voice_id, tts_model, narrator_volume, announcer_volume, enabled_by_default, announce_max_age_seconds, missing: tuple[str, ...])` with property `is_valid -> bool`
  - `load_config(env: Mapping[str, str] | None = None, env_path: Path | None = None) -> Config`
  - `cli.main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "claude-voice-augmented"
version = "0.1.0"
description = "Narrate Claude Code sessions with ElevenLabs."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "sounddevice>=0.4.6",
    "python-dotenv>=1.0",
]

[project.scripts]
claude-voice-augmented = "claude_voice_augmented.cli:main"
cva = "claude_voice_augmented.cli:main"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/claude_voice_augmented"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: runs the real claude CLI (opt-in: pytest -m live)"]
addopts = "-m 'not live'"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Create the package skeleton**

`src/claude_voice_augmented/__init__.py`:

```python
"""Narrate Claude Code sessions with ElevenLabs."""

__version__ = "0.1.0"
```

`src/claude_voice_augmented/__main__.py`:

```python
from .cli import main

raise SystemExit(main())
```

`src/claude_voice_augmented/cli.py` (a stub; Task 10 replaces it):

```python
import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cva", description="Narrate Claude Code sessions.")
    parser.parse_args(argv)
    return 0
```

Create an empty `README.md` (Task 11 fills it in) so `uv` can build the project:

```bash
touch README.md
```

Run: `uv sync`
Expected: creates `.venv` and `uv.lock`, installs dependencies, no errors.

- [ ] **Step 3: Write the failing config tests**

`tests/test_config.py`:

```python
import pytest

from claude_voice_augmented.config import REQUIRED_KEYS, load_config

REQUIRED = {
    "ELEVENLABS_API_KEY": "key",
    "CVA_NARRATOR_VOICE_ID": "narrator",
    "CVA_ANNOUNCER_VOICE_ID": "announcer",
}


def env_file(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text)
    return path


def test_missing_required_keys_are_reported(tmp_path):
    cfg = load_config(env={}, env_path=tmp_path / "absent.env")
    assert cfg.missing == REQUIRED_KEYS
    assert not cfg.is_valid


def test_defaults_apply(tmp_path):
    cfg = load_config(env=REQUIRED, env_path=tmp_path / "absent.env")
    assert cfg.is_valid
    assert cfg.api_key == "key"
    assert cfg.narrator_voice_id == "narrator"
    assert cfg.announcer_voice_id == "announcer"
    assert cfg.tts_model == "eleven_flash_v2_5"
    assert cfg.narrator_volume == 1.0
    assert cfg.announcer_volume == 0.4
    assert cfg.enabled_by_default is True
    assert cfg.announce_max_age_seconds == 60.0


def test_values_come_from_env_file(tmp_path):
    path = env_file(
        tmp_path,
        "ELEVENLABS_API_KEY=filekey\nCVA_NARRATOR_VOICE_ID=n\nCVA_ANNOUNCER_VOICE_ID=a\n"
        "CVA_ANNOUNCER_VOLUME=0.2\n",
    )
    cfg = load_config(env={}, env_path=path)
    assert cfg.api_key == "filekey"
    assert cfg.announcer_volume == 0.2


def test_environment_overrides_file(tmp_path):
    path = env_file(tmp_path, "ELEVENLABS_API_KEY=filekey\n")
    cfg = load_config(env={**REQUIRED, "ELEVENLABS_API_KEY": "envkey"}, env_path=path)
    assert cfg.api_key == "envkey"


def test_empty_environment_value_does_not_override_file(tmp_path):
    path = env_file(tmp_path, "ELEVENLABS_API_KEY=filekey\n")
    cfg = load_config(env={**REQUIRED, "ELEVENLABS_API_KEY": ""}, env_path=path)
    assert cfg.api_key == "filekey"


def test_bad_number_falls_back_to_default(tmp_path):
    cfg = load_config(env={**REQUIRED, "CVA_NARRATOR_VOLUME": "loud"}, env_path=tmp_path / "x")
    assert cfg.narrator_volume == 1.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("false", False), ("0", False), ("no", False), ("off", False), ("true", True), ("YES", True)],
)
def test_enabled_by_default_parsing(tmp_path, raw, expected):
    cfg = load_config(env={**REQUIRED, "CVA_ENABLED_BY_DEFAULT": raw}, env_path=tmp_path / "x")
    assert cfg.enabled_by_default is expected
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice_augmented.config'`

- [ ] **Step 5: Implement `config.py`**

`src/claude_voice_augmented/config.py`:

```python
"""Settings: environment variables over ~/.config/claude-voice-augmented/.env over defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

SAMPLE_RATE = 22050
DEFAULT_ENV_PATH = Path.home() / ".config" / "claude-voice-augmented" / ".env"
REQUIRED_KEYS = ("ELEVENLABS_API_KEY", "CVA_NARRATOR_VOICE_ID", "CVA_ANNOUNCER_VOICE_ID")
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    api_key: str
    narrator_voice_id: str
    announcer_voice_id: str
    tts_model: str = "eleven_flash_v2_5"
    narrator_volume: float = 1.0
    announcer_volume: float = 0.4
    enabled_by_default: bool = True
    announce_max_age_seconds: float = 60.0
    missing: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.missing


def _float(raw: str, default: float) -> float:
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def load_config(env: Mapping[str, str] | None = None, env_path: Path | None = None) -> Config:
    env = os.environ if env is None else env
    path = DEFAULT_ENV_PATH if env_path is None else env_path

    values: dict[str, str] = {}
    if path.is_file():
        values.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    values.update({k: v for k, v in env.items() if v and k.startswith(("CVA_", "ELEVENLABS_"))})

    def get(key: str) -> str:
        return values.get(key, "").strip()

    enabled = get("CVA_ENABLED_BY_DEFAULT")
    return Config(
        api_key=get("ELEVENLABS_API_KEY"),
        narrator_voice_id=get("CVA_NARRATOR_VOICE_ID"),
        announcer_voice_id=get("CVA_ANNOUNCER_VOICE_ID"),
        tts_model=get("CVA_TTS_MODEL") or "eleven_flash_v2_5",
        narrator_volume=_float(get("CVA_NARRATOR_VOLUME"), 1.0),
        announcer_volume=_float(get("CVA_ANNOUNCER_VOLUME"), 0.4),
        enabled_by_default=enabled.lower() in _TRUE if enabled else True,
        announce_max_age_seconds=_float(get("CVA_ANNOUNCE_MAX_AGE_SECONDS"), 60.0),
        missing=tuple(key for key in REQUIRED_KEYS if not get(key)),
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v && uv run ruff check .`
Expected: all PASS; ruff reports no issues.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock README.md src tests
git commit -m "feat: scaffold package and config loading" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: State files, focus, and announcer lock

**Files:**
- Create: `src/claude_voice_augmented/control.py`, `src/claude_voice_augmented/focus.py`
- Test: `tests/test_control.py`, `tests/test_focus.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces (`control.py`):
  - `DEFAULT_ROOT: Path` (= `~/.cache/claude-voice-augmented`)
  - `WATCHER_MARKER = "claude_voice_augmented"`
  - `pid_alive(pid: int) -> bool`
  - `process_command(pid: int) -> str | None`
  - `watcher_running(pid: int) -> bool`
  - `atomic_write(path: Path, text: str) -> None`
  - `@dataclass(frozen=True) SessionMeta(session_id: str, transcript_path: str, cwd: str, session_title: str | None, claude_pid: int | None, started_at: float)`
  - `@dataclass(frozen=True) Announcement(event: str, ts: float)`
  - `SessionState(root: Path, session_id: str)` with attributes `session_id` and `dir`, and methods `exists()`, `create()`, `remove()`, `write_meta(meta)`, `read_meta() -> SessionMeta | None`, `write_pid(pid)`, `read_pid() -> int | None`, `watcher_alive() -> bool`, `is_enabled() -> bool`, `set_enabled(on: bool)`, `request_clear()`, `take_clear() -> bool`, `add_announcement(event: str, ts: float)`, `take_announcements() -> list[Announcement]`
  - `list_sessions(root: Path) -> list[SessionState]`
  - `cleanup_stale(root: Path, now: float, max_age: float = 86400.0) -> list[str]`
  - `read_last_speaker(root: Path) -> str | None`, `write_last_speaker(root: Path, session_id: str) -> None`
  - `logs_dir(root: Path) -> Path`
  - `announcer_lock(root: Path, timeout: float, poll: float = 0.05)`, a context manager that yields `bool` (acquired)
- Produces (`focus.py`): `read_focus(root: Path) -> str | None`, `write_focus(root: Path, session_id: str) -> None`

- [ ] **Step 1: Write the shared test fixtures**

`tests/conftest.py`:

```python
import subprocess
import sys

import pytest


@pytest.fixture
def fake_watcher():
    """A live process whose command line contains the watcher marker."""
    procs = []

    def start() -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "claude_voice_augmented"]
        )
        procs.append(proc)
        return proc

    yield start
    for proc in procs:
        proc.kill()
        proc.wait()


@pytest.fixture
def dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid
```

- [ ] **Step 2: Write the failing tests**

`tests/test_control.py`:

```python
import os
import time

from claude_voice_augmented.control import (
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
```

`tests/test_focus.py`:

```python
from claude_voice_augmented.focus import read_focus, write_focus


def test_focus_round_trip(tmp_path):
    assert read_focus(tmp_path) is None
    write_focus(tmp_path, "s1")
    assert read_focus(tmp_path) == "s1"
    write_focus(tmp_path, "s2")
    assert read_focus(tmp_path) == "s2"


def test_blank_focus_reads_as_none(tmp_path):
    (tmp_path / "focus").write_text("  \n")
    assert read_focus(tmp_path) is None
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_control.py tests/test_focus.py -v`
Expected: FAIL with `ModuleNotFoundError` for `claude_voice_augmented.control` and `claude_voice_augmented.focus`.

- [ ] **Step 4: Implement `control.py`**

`src/claude_voice_augmented/control.py`:

```python
"""File-based state shared by hooks and watchers under ~/.cache/claude-voice-augmented/."""

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

DEFAULT_ROOT = Path.home() / ".cache" / "claude-voice-augmented"
WATCHER_MARKER = "claude_voice_augmented"


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
    except OSError:
        return None


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
        for line in taking.read_text().splitlines():
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
    return [SessionState(root, p.name) for p in base.iterdir() if p.is_dir()]


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
```

- [ ] **Step 5: Implement `focus.py`**

`src/claude_voice_augmented/focus.py`:

```python
"""The current session: the one you most recently sent a prompt to."""

from __future__ import annotations

from pathlib import Path

from .control import atomic_write


def read_focus(root: Path) -> str | None:
    try:
        return (root / "focus").read_text().strip() or None
    except OSError:
        return None


def write_focus(root: Path, session_id: str) -> None:
    atomic_write(root / "focus", session_id)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_control.py tests/test_focus.py -v && uv run ruff check .`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/claude_voice_augmented/control.py src/claude_voice_augmented/focus.py tests
git commit -m "feat: add session state files, focus, and announcer lock" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Transcript tailer

**Files:**
- Create: `src/claude_voice_augmented/transcript.py`, `tests/fixtures/spike.jsonl`
- Test: `tests/test_transcript.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) TextBlock(uuid: str, text: str)`
  - `TranscriptReader(path: Path, start_at_end: bool = True)` with `read_new() -> list[TextBlock]`, attribute `deleted: bool` (True once a file that was opened has disappeared), and `close()`.
- Behavior: a file that doesn't exist yet when the reader is created is read from its beginning once it appears, because transcripts are created on the first message. A replaced or truncated file is reopened at its end.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/spike.jsonl` mirrors the entry shapes seen in the 2026-10-14 spike, with paths and IDs removed. Each line is one JSON object:

```jsonl
{"type":"queue-operation","operation":"enqueue","timestamp":"2026-10-15T02:58:59.406Z"}
{"type":"attachment","timestamp":"2026-10-15T02:58:59.297Z"}
{"type":"user","uuid":"u-1","isSidechain":false,"message":{"role":"user","content":"Run three commands."}}
{"type":"atis-latch"}
{"type":"last-prompt"}
{"type":"assistant","uuid":"a-1","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"Running the first command to print \"a\"."}]}}
{"type":"assistant","uuid":"a-2","isSidechain":false,"message":{"role":"assistant","content":[{"type":"tool_use","id":"t-1","name":"Bash","input":{"command":"sleep 3; echo a"}}]}}
{"type":"user","uuid":"u-2","isSidechain":false,"message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t-1","content":"a"}]}}
{"type":"assistant","uuid":"a-3","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"Running the second command to print \"b\"."}]}}
{"type":"assistant","uuid":"a-4","isSidechain":false,"message":{"role":"assistant","content":[{"type":"tool_use","id":"t-2","name":"Bash","input":{"command":"sleep 3; echo b"}}]}}
{"type":"user","uuid":"u-3","isSidechain":false,"message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t-2","content":"b"}]}}
{"type":"assistant","uuid":"a-5","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"Running the third command to print \"c\"."}]}}
{"type":"assistant","uuid":"a-6","isSidechain":false,"message":{"role":"assistant","content":[{"type":"tool_use","id":"t-3","name":"Bash","input":{"command":"sleep 3; echo c"}}]}}
{"type":"user","uuid":"u-4","isSidechain":false,"message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t-3","content":"c"}]}}
{"type":"assistant","uuid":"a-7","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"I ran the three commands one after another, and each printed its letter."}]}}
{"type":"cost-state"}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_transcript.py`:

```python
import json
import os
from pathlib import Path

from claude_voice_augmented.transcript import TextBlock, TranscriptReader

FIXTURE = Path(__file__).parent / "fixtures" / "spike.jsonl"


def assistant(uuid, *texts, sidechain=False):
    content = [{"type": "text", "text": t} for t in texts]
    return json.dumps(
        {"type": "assistant", "uuid": uuid, "isSidechain": sidechain,
         "message": {"role": "assistant", "content": content}}
    ) + "\n"


def append(path, text):
    with open(path, "ab") as fh:
        fh.write(text.encode() if isinstance(text, str) else text)


def test_reads_fixture_from_start():
    reader = TranscriptReader(FIXTURE, start_at_end=False)
    assert [b.text for b in reader.read_new()] == [
        'Running the first command to print "a".',
        'Running the second command to print "b".',
        'Running the third command to print "c".',
        "I ran the three commands one after another, and each printed its letter.",
    ]


def test_start_at_end_skips_existing_content(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(FIXTURE.read_text())
    reader = TranscriptReader(path)
    assert reader.read_new() == []
    append(path, assistant("new", "Fresh text."))
    assert reader.read_new() == [TextBlock("new", "Fresh text.")]


def test_partial_line_waits_for_newline(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    line = assistant("p", "Split line.")
    append(path, line[:20])
    assert reader.read_new() == []
    append(path, line[20:])
    assert reader.read_new() == [TextBlock("p", "Split line.")]


def test_multibyte_character_split_across_writes(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    raw = assistant("u", "Café ✓ done.").encode()
    cut = raw.index("✓".encode()) + 1  # in the middle of the 3-byte character
    append(path, raw[:cut])
    assert reader.read_new() == []
    append(path, raw[cut:])
    assert reader.read_new() == [TextBlock("u", "Café ✓ done.")]


def test_duplicates_sidechains_and_junk_are_skipped(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    append(path, assistant("a", "Once."))
    append(path, assistant("a", "Once."))
    append(path, assistant("s", "Subagent.", sidechain=True))
    append(path, "{not json\n")
    append(path, '"a string"\n')
    append(path, json.dumps({"type": "mystery", "uuid": "m"}) + "\n")
    append(path, assistant("e", ""))
    assert reader.read_new() == [TextBlock("a", "Once.")]


def test_multiple_text_blocks_in_one_entry_are_joined(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    append(path, assistant("m", "First.", "Second."))
    assert reader.read_new() == [TextBlock("m", "First.\n\nSecond.")]


def test_file_created_after_reader_is_read_from_start(tmp_path):
    path = tmp_path / "later.jsonl"
    reader = TranscriptReader(path)
    assert reader.read_new() == []
    assert not reader.deleted
    path.write_text(assistant("x", "Hello."))
    assert reader.read_new() == [TextBlock("x", "Hello.")]


def test_truncated_file_is_reopened_at_end(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(assistant("a", "A.") * 3)
    reader = TranscriptReader(path)
    path.write_text(assistant("b", "B."))  # shorter than before → truncated
    assert reader.read_new() == []
    append(path, assistant("c", "C."))
    assert reader.read_new() == [TextBlock("c", "C.")]


def test_replaced_file_is_reopened_at_end(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(assistant("a", "A."))
    reader = TranscriptReader(path)
    replacement = tmp_path / "new.jsonl"
    replacement.write_text(assistant("b", "B.") * 5)
    os.replace(replacement, path)
    assert reader.read_new() == []
    append(path, assistant("c", "C."))
    assert reader.read_new() == [TextBlock("c", "C.")]


def test_deleted_file_sets_deleted(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    path.unlink()
    assert reader.read_new() == []
    assert reader.deleted
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_transcript.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice_augmented.transcript'`

- [ ] **Step 4: Implement `transcript.py`**

`src/claude_voice_augmented/transcript.py`:

```python
"""Follow a Claude Code session transcript and yield new assistant text blocks.

The transcript format is internal to Claude Code, so parsing is defensive: anything
unrecognized is skipped.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextBlock:
    uuid: str
    text: str


def _extract(entry: object) -> TextBlock | None:
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return None
    if entry.get("isSidechain") is True:
        return None
    uuid = entry.get("uuid")
    message = entry.get("message")
    if not isinstance(uuid, str) or not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
    else:
        return None
    text = "\n\n".join(t for t in texts if t.strip())
    return TextBlock(uuid, text) if text else None


class TranscriptReader:
    def __init__(self, path: Path, start_at_end: bool = True):
        self.path = Path(path)
        self.deleted = False
        self._fh: BinaryIO | None = None
        self._inode: int | None = None
        self._buffer = b""
        self._seen: set[str] = set()
        self._open(seek_end=start_at_end)

    def _open(self, seek_end: bool) -> None:
        try:
            fh = open(self.path, "rb")
        except FileNotFoundError:
            return
        if self._fh is not None:
            self._fh.close()
        self._fh = fh
        self._inode = os.fstat(fh.fileno()).st_ino
        self._buffer = b""
        if seek_end:
            fh.seek(0, os.SEEK_END)

    def read_new(self) -> list[TextBlock]:
        try:
            stat = os.stat(self.path)
        except FileNotFoundError:
            if self._fh is not None:
                self.deleted = True
            return []
        if self._fh is None:
            self._open(seek_end=False)  # created after we started: all of it is new
        elif stat.st_ino != self._inode or stat.st_size < self._fh.tell():
            self._open(seek_end=True)  # replaced or truncated
        if self._fh is None:
            return []

        self._buffer += self._fh.read()
        *lines, self._buffer = self._buffer.split(b"\n")
        blocks: list[TextBlock] = []
        for raw in lines:
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                log.debug("skipping unreadable transcript line")
                continue
            block = _extract(entry)
            if block is None or block.uuid in self._seen:
                continue
            self._seen.add(block.uuid)
            blocks.append(block)
        return blocks

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_transcript.py -v && uv run ruff check .`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/claude_voice_augmented/transcript.py tests
git commit -m "feat: add defensive transcript tailer" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Markdown to speakable prose

**Files:**
- Create: `src/claude_voice_augmented/prose.py`
- Test: `tests/test_prose.py`

**Interfaces:**
- Produces:
  - `to_speech(markdown: str) -> str`: returns `""` when nothing is speakable.
  - `sentences(text: str) -> list[str]`
  - `chunk(text: str, max_chars: int = 400) -> list[str]`: groups whole sentences; a single sentence longer than `max_chars` becomes its own chunk.

- [ ] **Step 1: Write the failing tests**

`tests/test_prose.py`:

```python
import pytest

from claude_voice_augmented.prose import chunk, sentences, to_speech


@pytest.mark.parametrize(
    ("markdown", "speech"),
    [
        ("", ""),
        ("Hello **world**.", "Hello world."),
        ("an *emphasized* word and ~~gone~~ text", "an emphasized word and gone text"),
        ("snake_case_name stays", "snake_case_name stays"),
        ("Use `cva doctor` first.", "Use cva doctor first."),
        ("Call `__init__` here.", "Call __init__ here."),
        ("Before\n```python\nprint('x')\n```\nAfter.", "Before After."),
        ("~~~\ncode\n~~~\nDone.", "Done."),
        ("```\nunclosed code\nmore", ""),
        ("# Title\nBody.", "Title. Body."),
        ("## Done!", "Done!"),
        ("- one\n- two.", "one. two."),
        ("1. first\n2) second", "first. second."),
        ("> quoted line", "quoted line"),
        ("---\nText.", "Text."),
        ("See [the docs](https://x.com/a).", "See the docs."),
        ("![diagram](https://x.com/d.png) shows it.", "diagram shows it."),
        ("Go to https://example.com/x now.", "Go to a link now."),
        ("Edit `/Users/box/dev/app/src/main.py:12`.", "Edit main.py:12."),
        ("Open src/app.py.", "Open app.py."),
        ("~/x/y/file.txt is here", "file.txt is here"),
        ("Both and/or work.", "Both and/or work."),
        ("Half is 1/2.", "Half is 1/2."),
        (
            "| Name | Value |\n|---|:---:|\n| a | 1 |\n| b | 2 |",
            "Name: a, Value: 1. Name: b, Value: 2.",
        ),
        ("| a | b | c | d | e |\n|---|---|---|---|---|\n| 1 | 2 | 3 | 4 | 5 |", ""),
        ("Intro:\n\n| K | V |\n|---|---|\n| x | `y` |\n\nEnd.", "Intro: K: x, V: y. End."),
    ],
)
def test_to_speech(markdown, speech):
    assert to_speech(markdown) == speech


def test_sentences():
    assert sentences("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]
    assert sentences("") == []


def test_chunk_short_text_is_one_chunk():
    assert chunk("One. Two.") == ["One. Two."]


def test_chunk_groups_sentences_under_limit():
    text = " ".join(f"Sentence number {i} is here and padded out a little bit more." for i in range(20))
    pieces = chunk(text, max_chars=200)
    assert len(pieces) > 1
    assert all(len(p) <= 200 for p in pieces)
    assert " ".join(pieces) == text


def test_chunk_keeps_overlong_sentence_whole():
    long = "word " * 150 + "end."
    assert chunk(long.strip(), max_chars=100) == [long.strip()]


def test_chunk_empty():
    assert chunk("") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_prose.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice_augmented.prose'`

- [ ] **Step 3: Implement `prose.py`**

`src/claude_voice_augmented/prose.py`:

```python
"""Turn Claude's markdown into text that sounds natural when spoken."""

from __future__ import annotations

import re

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HR = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_QUOTE = re.compile(r"^\s*>\s?")
_TABLE_SEP_CELL = re.compile(r"^:?-{3,}:?$")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC_STAR = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
_ITALIC_UNDER = re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_STRIKE = re.compile(r"~~(.+?)~~")
_PATH = re.compile(r"(?<![\w/.~-])(?P<prefix>~/|\.{1,2}/|/)?(?P<body>(?:[\w.@+-]+/)+[\w.@+-]+)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_MAX_TABLE_COLUMNS = 4


def _shorten_path(match: re.Match[str]) -> str:
    body = match.group("body")
    last = body.rsplit("/", 1)[-1]
    if match.group("prefix") is None and body.count("/") == 1 and "." not in last.rstrip("."):
        return match.group(0)  # "and/or", "1/2": not a path
    return last


def _inline(text: str) -> str:
    spans: list[str] = []

    def protect(match: re.Match[str]) -> str:
        spans.append(match.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE_SPAN.sub(protect, text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("a link", text)
    text = _BOLD.sub(r"\2", text)
    text = _ITALIC_STAR.sub(r"\1", text)
    text = _ITALIC_UNDER.sub(r"\1", text)
    text = _STRIKE.sub(r"\1", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
    return _PATH.sub(_shorten_path, text)


def _terminate(text: str) -> str:
    return text if not text or text[-1] in ".!?:" else text + "."


def _table(lines: list[str]) -> str:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [r for r in rows if not all(_TABLE_SEP_CELL.match(c) for c in r if c)]
    if not rows or len(rows[0]) > _MAX_TABLE_COLUMNS:
        return ""
    header, *body = rows
    phrases = []
    for row in body:
        pairs = [f"{_inline(h)}: {_inline(v)}" for h, v in zip(header, row) if v]
        if pairs:
            phrases.append(", ".join(pairs) + ".")
    return " ".join(phrases)


def to_speech(markdown: str) -> str:
    segments: list[str] = []
    table: list[str] = []
    fence: str | None = None

    def flush_table() -> None:
        if table:
            segments.append(_table(table))
            table.clear()

    for line in markdown.splitlines():
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        opening = _FENCE.match(line)
        if opening:
            flush_table()
            fence = opening.group(1)[:3]
            continue
        if line.strip().startswith("|"):
            table.append(line)
            continue
        flush_table()
        if not line.strip() or _HR.match(line):
            continue
        if _HEADING.match(line):
            segments.append(_terminate(_inline(_HEADING.sub("", line).strip())))
        elif _LIST.match(line):
            segments.append(_terminate(_inline(_LIST.sub("", line).strip())))
        else:
            segments.append(_inline(_QUOTE.sub("", line).strip()))
    flush_table()
    return re.sub(r"\s+", " ", " ".join(s for s in segments if s)).strip()


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def chunk(text: str, max_chars: int = 400) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in sentences(text):
        candidate = f"{current} {sentence}" if current else sentence
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_prose.py -v && uv run ruff check .`
Expected: all PASS. If a case fails, fix the regex in `prose.py`, not the expected output; the table above is the contract.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice_augmented/prose.py tests/test_prose.py
git commit -m "feat: convert markdown replies to speakable prose" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Session labels and announcement lines

**Files:**
- Create: `src/claude_voice_augmented/label.py`, `src/claude_voice_augmented/events.py`
- Test: `tests/test_label.py`, `tests/test_events.py`

**Interfaces:**
- Produces (`label.py`):
  - `DEFAULT_BRANCHES = frozenset({"main", "master", "develop", "trunk"})`
  - `spell_id(session_id: str, length: int = 4) -> str`
  - `git_branch(cwd: str, timeout: float = 1.0) -> str | None`
  - `speak_branch(branch: str) -> str`
  - `label_for(session_id: str, session_title: str | None = None, cwd: str | None = None, branch_lookup: Callable[[str], str | None] = git_branch) -> str`
- Produces (`events.py`):
  - `ANNOUNCED_EVENTS: frozenset[str]` = `{"Stop", "StopFailure", "PermissionRequest", "Notification"}`
  - `announcement_line(event: str, label: str) -> str | None`

- [ ] **Step 1: Write the failing tests**

`tests/test_label.py`:

```python
import subprocess

from claude_voice_augmented.label import git_branch, label_for, speak_branch, spell_id


def test_spell_id():
    assert spell_id("639b1bcb-4b66-4047") == "six-three-nine-bravo"
    assert spell_id("A0F2") == "alfa-zero-foxtrot-two"
    assert spell_id("ab-cd", length=3) == "alfa-bravo-charlie"


def test_speak_branch():
    assert speak_branch("feat/ABC-123-login-fix") == "feat ABC-123 login fix"
    assert speak_branch("fix_thing") == "fix thing"
    assert speak_branch("chore/update-deps") == "chore update deps"


def test_title_wins():
    assert label_for("639b", "Login refactor", "/x", lambda cwd: "feat/y") == "Login refactor"


def test_blank_title_is_ignored():
    assert label_for("639b", "   ", "/x", lambda cwd: "feat/y") == "feat y"


def test_branch_used_without_title():
    assert label_for("639b", None, "/x", lambda cwd: "feat/ABC-1-x") == "feat ABC-1 x"


def test_default_branch_falls_back_to_id():
    # Review Focus 2: many sessions on main must not all be called "main".
    assert label_for("639b", None, "/x", lambda cwd: "main") == "six-three-nine-bravo"


def test_no_cwd_or_branch_uses_id():
    assert label_for("639b") == "six-three-nine-bravo"
    assert label_for("639b", None, "/x", lambda cwd: None) == "six-three-nine-bravo"


def test_git_branch_reads_real_repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "topic", str(tmp_path)], check=True)
    assert git_branch(str(tmp_path)) == "topic"


def test_git_branch_outside_repo(tmp_path):
    assert git_branch(str(tmp_path)) is None
    assert git_branch(str(tmp_path / "missing")) is None
```

`tests/test_events.py`:

```python
import pytest

from claude_voice_augmented.events import ANNOUNCED_EVENTS, announcement_line


@pytest.mark.parametrize(
    ("event", "line"),
    [
        ("Stop", "six finished."),
        ("StopFailure", "six hit an error."),
        ("PermissionRequest", "six needs permission."),
        ("Notification", "six needs your attention."),
    ],
)
def test_announcement_lines(event, line):
    assert announcement_line(event, "six") == line


def test_unknown_event():
    assert announcement_line("PreToolUse", "six") is None


def test_announced_events():
    assert ANNOUNCED_EVENTS == {"Stop", "StopFailure", "PermissionRequest", "Notification"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_label.py tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `label.py`**

`src/claude_voice_augmented/label.py`:

```python
"""Spoken session labels: title → git branch → short spelled-out ID."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

DEFAULT_BRANCHES = frozenset({"main", "master", "develop", "trunk"})

_DIGITS = dict(zip("0123456789", "zero one two three four five six seven eight nine".split()))
_NATO = dict(
    zip(
        "abcdefghijklmnopqrstuvwxyz",
        (
            "alfa bravo charlie delta echo foxtrot golf hotel india juliett kilo lima mike "
            "november oscar papa quebec romeo sierra tango uniform victor whiskey xray "
            "yankee zulu"
        ).split(),
    )
)
# Keep a hyphen only inside ticket IDs like ABC-123; every other one becomes a space.
_SOFT_HYPHEN = re.compile(r"(?<![A-Z])-|-(?!\d)")


def spell_id(session_id: str, length: int = 4) -> str:
    chars = [c for c in session_id.lower() if c.isalnum()][:length]
    return "-".join(_DIGITS.get(c) or _NATO.get(c, c) for c in chars)


def git_branch(cwd: str, timeout: float = 1.0) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch else None


def speak_branch(branch: str) -> str:
    parts = [p for p in re.split(r"[/_]+", branch) if p]
    return " ".join(_SOFT_HYPHEN.sub(" ", p) for p in parts).strip()


def label_for(
    session_id: str,
    session_title: str | None = None,
    cwd: str | None = None,
    branch_lookup: Callable[[str], str | None] = git_branch,
) -> str:
    if session_title and session_title.strip():
        return session_title.strip()
    if cwd:
        branch = branch_lookup(cwd)
        if branch and branch not in DEFAULT_BRANCHES:
            return speak_branch(branch)
    return spell_id(session_id)
```

- [ ] **Step 4: Implement `events.py`**

`src/claude_voice_augmented/events.py`:

```python
"""Hook events from non-current sessions, as short spoken lines."""

from __future__ import annotations

_LINES = {
    "Stop": "finished.",
    "StopFailure": "hit an error.",
    "PermissionRequest": "needs permission.",
    "Notification": "needs your attention.",
}
ANNOUNCED_EVENTS = frozenset(_LINES)


def announcement_line(event: str, label: str) -> str | None:
    suffix = _LINES.get(event)
    return f"{label} {suffix}" if suffix else None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_label.py tests/test_events.py -v && uv run ruff check .`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/claude_voice_augmented/label.py src/claude_voice_augmented/events.py tests
git commit -m "feat: add spoken session labels and announcement lines" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: ElevenLabs client

**Files:**
- Create: `src/claude_voice_augmented/tts.py`
- Test: `tests/test_tts.py`

**Interfaces:**
- Consumes: `config.SAMPLE_RATE`.
- Produces:
  - `class TTSError(Exception)` and `class TTSAuthError(TTSError)`
  - `class TTS(Protocol)` with `synthesize(text: str, voice_id: str) -> Iterator[bytes]`
  - `ElevenLabsTTS(api_key: str, model: str, client: httpx.Client | None = None, retry_delay: float = 1.0, sleep: Callable[[float], None] = time.sleep)` with `synthesize(...)` and `voice_exists(voice_id: str) -> bool`
- Behavior:
  - Retries once on 429, 5xx, timeouts, and transport errors, but only if no audio has been yielded yet.
  - 401/403 raise `TTSAuthError` immediately.
  - Other 4xx raise `TTSError` immediately.

- [ ] **Step 1: Write the failing tests**

`tests/test_tts.py`:

```python
import json

import httpx
import pytest

from claude_voice_augmented.tts import ElevenLabsTTS, TTSAuthError, TTSError


def make(handler, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ElevenLabsTTS("secret", "eleven_flash_v2_5", client=client, sleep=sleeps.append)


def test_streams_pcm_and_sends_expected_request():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["xi-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"\x01\x00\x02\x00")

    audio = b"".join(make(handler).synthesize("Hello.", "voice1"))
    assert audio == b"\x01\x00\x02\x00"
    assert seen["url"] == (
        "https://api.elevenlabs.io/v1/text-to-speech/voice1/stream?output_format=pcm_22050"
    )
    assert seen["key"] == "secret"
    assert seen["body"] == {"text": "Hello.", "model_id": "eleven_flash_v2_5"}


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_not_retried(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(TTSAuthError):
        list(make(handler).synthesize("x", "v"))
    assert len(calls) == 1


def test_server_error_retried_once_then_succeeds():
    responses = iter([httpx.Response(503), httpx.Response(200, content=b"ok")])
    sleeps = []
    assert b"".join(make(lambda r: next(responses), sleeps).synthesize("x", "v")) == b"ok"
    assert sleeps == [1.0]


def test_server_error_twice_raises():
    with pytest.raises(TTSError):
        list(make(lambda r: httpx.Response(429)).synthesize("x", "v"))


def test_timeout_retried_once():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, content=b"ok")

    assert b"".join(make(handler).synthesize("x", "v")) == b"ok"


def test_other_client_error_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(422, json={"detail": "bad"})

    with pytest.raises(TTSError) as err:
        list(make(handler).synthesize("x", "v"))
    assert not isinstance(err.value, TTSAuthError)
    assert len(calls) == 1


def test_voice_exists():
    def handler(request):
        assert request.url.path in ("/v1/voices/good", "/v1/voices/bad")
        return httpx.Response(200 if request.url.path.endswith("good") else 404)

    tts = make(handler)
    assert tts.voice_exists("good")
    assert not tts.voice_exists("bad")


def test_voice_exists_auth_error():
    with pytest.raises(TTSAuthError):
        make(lambda r: httpx.Response(401)).voice_exists("v")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice_augmented.tts'`

- [ ] **Step 3: Implement `tts.py`**

`src/claude_voice_augmented/tts.py`:

```python
"""ElevenLabs streaming text-to-speech, returning raw 16-bit mono PCM."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Protocol

import httpx

from .config import SAMPLE_RATE

API_BASE = "https://api.elevenlabs.io/v1"


class TTSError(Exception):
    pass


class TTSAuthError(TTSError):
    pass


class _Retryable(Exception):
    pass


class TTS(Protocol):
    def synthesize(self, text: str, voice_id: str) -> Iterator[bytes]: ...


class ElevenLabsTTS:
    def __init__(
        self,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
        retry_delay: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=httpx.Timeout(5.0))
        self._retry_delay = retry_delay
        self._sleep = sleep

    def synthesize(self, text: str, voice_id: str) -> Iterator[bytes]:
        for attempt in (1, 2):
            yielded = False
            try:
                with self._client.stream(
                    "POST",
                    f"{API_BASE}/text-to-speech/{voice_id}/stream",
                    params={"output_format": f"pcm_{SAMPLE_RATE}"},
                    headers={"xi-api-key": self._api_key},
                    json={"text": text, "model_id": self._model},
                ) as response:
                    self._check(response)
                    for data in response.iter_bytes():
                        yielded = True
                        yield data
                    return
            except (_Retryable, httpx.TimeoutException, httpx.TransportError) as exc:
                if yielded or attempt == 2:
                    raise TTSError(f"ElevenLabs request failed: {exc}") from exc
                self._sleep(self._retry_delay)

    def voice_exists(self, voice_id: str) -> bool:
        try:
            response = self._client.get(
                f"{API_BASE}/voices/{voice_id}", headers={"xi-api-key": self._api_key}
            )
        except httpx.HTTPError as exc:
            raise TTSError(f"ElevenLabs request failed: {exc}") from exc
        if response.status_code in (401, 403):
            raise TTSAuthError(f"ElevenLabs rejected the key ({response.status_code})")
        if response.status_code >= 500:
            raise TTSError(f"ElevenLabs error {response.status_code}")
        return response.status_code == 200

    @staticmethod
    def _check(response: httpx.Response) -> None:
        status = response.status_code
        if status in (401, 403):
            raise TTSAuthError(f"ElevenLabs rejected the key ({status})")
        if status == 429 or status >= 500:
            raise _Retryable(f"status {status}")
        if status >= 400:
            response.read()
            raise TTSError(f"ElevenLabs error {status}: {response.text[:200]}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_tts.py -v && uv run ruff check .`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice_augmented/tts.py tests/test_tts.py
git commit -m "feat: add ElevenLabs streaming client with retry" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Two-channel audio player

**Files:**
- Create: `src/claude_voice_augmented/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: `config.SAMPLE_RATE`.
- Produces:
  - `NARRATOR = "narrator"`, `ANNOUNCER = "announcer"`
  - `Source = Callable[[], Iterable[bytes]]`, called lazily when the clip starts fetching.
  - `ErrorHandler = Callable[[str, BaseException], None]`, receiving `(channel_name, exc)`.
  - `class OutputError(Exception)`
  - `class Output(Protocol)`: `write(pcm: bytes) -> None` (blocking), `reopen() -> None`, `close() -> None`
  - `SoundDeviceOutput(sample_rate: int = SAMPLE_RATE)`
  - `apply_gain(pcm: bytes, start: float, end: float) -> bytes`: a linear ramp that reaches `end` on the last sample.
  - `Clip(source)` with `start()`, `chunks() -> Iterator[bytes]`, `cancel()`, and attribute `done: threading.Event`
  - `Channel(name, output, volume, on_error, frame_bytes=2048, sample_rate=SAMPLE_RATE)` with `enqueue(source) -> Clip`, `play_blocking(source, timeout=None)`, `clear()`, `duck(factor)`, `unduck()`, `close()`
  - `Player(narrator_volume, announcer_volume, on_error, output_factory=SoundDeviceOutput)` with `enqueue(channel, source)`, `play_blocking(channel, source, timeout=None)`, `clear(channel)`, `duck(channel, factor)`, `unduck(channel)`, `close()`
- Behavior:
  - Clips on a channel play in order, one at a time.
  - Only the playing clip and the next one fetch audio; later clips wait.
  - `clear()` drops the queue and fades the current clip out over about 100 ms; the next clip after that fades in.
  - A device error drops the current clip and reopens the device.

- [ ] **Step 1: Write the failing tests**

`tests/test_player.py`:

```python
import threading
import time
from array import array

from claude_voice_augmented.player import (
    ANNOUNCER,
    NARRATOR,
    Channel,
    OutputError,
    Player,
    apply_gain,
)


def pcm(*samples):
    return array("h", samples).tobytes()


def decode(data):
    out = array("h")
    out.frombytes(data)
    return list(out)


class FakeOutput:
    def __init__(self, delay=0.0, fail_first=False):
        self.writes = []
        self.reopens = 0
        self.closed = False
        self.delay = delay
        self.fail_first = fail_first

    def write(self, data):
        if self.fail_first:
            self.fail_first = False
            raise OutputError("device gone")
        time.sleep(self.delay)
        self.writes.append(data)

    def reopen(self):
        self.reopens += 1

    def close(self):
        self.closed = True

    def samples(self):
        return decode(b"".join(self.writes))


def channel(output, volume=1.0, errors=None, frame_bytes=2048):
    errors = [] if errors is None else errors
    return Channel("test", output, volume, lambda name, exc: errors.append((name, exc)), frame_bytes)


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_apply_gain():
    assert apply_gain(pcm(100, 100), 1.0, 1.0) == pcm(100, 100)
    assert decode(apply_gain(pcm(1000, -1000), 0.5, 0.5)) == [500, -500]
    assert decode(apply_gain(pcm(1000, 1000, 1000, 1000), 1.0, 0.0)) == [750, 500, 250, 0]
    assert decode(apply_gain(pcm(30000), 2.0, 2.0)) == [32767]
    assert apply_gain(b"", 0.0, 1.0) == b""


def test_plays_clip_in_order():
    out = FakeOutput()
    channel(out).play_blocking(lambda: [pcm(1, 2), pcm(3)], timeout=2)
    assert out.samples() == [1, 2, 3]


def test_volume_scales_samples():
    out = FakeOutput()
    channel(out, volume=0.5).play_blocking(lambda: [pcm(1000, -1000)], timeout=2)
    assert out.samples() == [500, -500]


def test_odd_length_chunks_are_reassembled():
    out = FakeOutput()
    channel(out).play_blocking(lambda: [b"\x01", b"\x00\x02", b"\x00"], timeout=2)
    assert out.samples() == [1, 2]


def test_queued_clips_play_in_order():
    out = FakeOutput()
    ch = channel(out)
    ch.enqueue(lambda: [pcm(1)])
    ch.enqueue(lambda: [pcm(2)])
    ch.play_blocking(lambda: [pcm(3)], timeout=2)
    assert out.samples() == [1, 2, 3]


def test_only_current_and_next_clip_prefetch():
    started = []
    gate = threading.Event()

    def source(name, wait=False):
        def run():
            started.append(name)
            if wait:
                gate.wait(2)
            return [pcm(1)]
        return run

    out = FakeOutput()
    ch = channel(out)
    ch.enqueue(source("a", wait=True))
    ch.enqueue(source("b"))
    ch.enqueue(source("c"))
    assert wait_until(lambda: started == ["a", "b"])
    time.sleep(0.05)
    assert started == ["a", "b"]
    gate.set()
    assert wait_until(lambda: started == ["a", "b", "c"])


def test_clear_fades_current_and_drops_queue():
    out = FakeOutput(delay=0.01)
    ch = channel(out, frame_bytes=200)
    ch.enqueue(lambda: [pcm(*([1000] * 4410))])
    ch.enqueue(lambda: [pcm(555)])
    assert wait_until(lambda: len(out.writes) >= 1)
    ch.clear()
    ch.play_blocking(lambda: [pcm(7)], timeout=2)
    samples = out.samples()
    assert 555 not in samples
    assert samples[-1] == 7
    played = samples[:-1]
    assert len(played) < 4410
    assert abs(played[-1]) < 50  # faded to silence, not cut at full volume


def test_play_blocking_returns_when_cleared():
    gate = threading.Event()
    out = FakeOutput()
    ch = channel(out)

    def slow():
        gate.wait(2)
        return [pcm(1)]

    ch.enqueue(slow)
    finished = threading.Event()
    threading.Thread(target=lambda: (ch.play_blocking(lambda: [pcm(2)]), finished.set())).start()
    time.sleep(0.05)
    ch.clear()
    gate.set()
    assert finished.wait(2)


def test_source_error_reported_and_next_clip_plays():
    errors = []
    out = FakeOutput()
    ch = channel(out, errors=errors)

    def broken():
        raise RuntimeError("boom")

    ch.enqueue(broken)
    ch.play_blocking(lambda: [pcm(9)], timeout=2)
    assert out.samples() == [9]
    assert errors and errors[0][0] == "test" and str(errors[0][1]) == "boom"


def test_output_error_reopens_and_drops_clip():
    out = FakeOutput(fail_first=True)
    ch = channel(out)
    ch.play_blocking(lambda: [pcm(1)], timeout=2)
    ch.play_blocking(lambda: [pcm(2)], timeout=2)
    assert out.reopens == 1
    assert out.samples() == [2]


def test_duck_lowers_volume():
    out = FakeOutput()
    ch = channel(out, frame_bytes=4)
    ch.duck(0.5)
    ch.play_blocking(lambda: [pcm(1000, 1000, 1000, 1000)], timeout=2)
    assert out.samples()[-1] == 500
    ch.unduck()
    ch.play_blocking(lambda: [pcm(1000, 1000, 1000, 1000)], timeout=2)
    assert out.samples()[-1] == 1000


def test_player_routes_channels_and_closes():
    outputs = []

    def factory():
        outputs.append(FakeOutput())
        return outputs[-1]

    player = Player(1.0, 1.0, on_error=lambda name, exc: None, output_factory=factory)
    player.play_blocking(NARRATOR, lambda: [pcm(1)], timeout=2)
    player.play_blocking(ANNOUNCER, lambda: [pcm(2)], timeout=2)
    narrator_out, announcer_out = outputs
    assert narrator_out.samples() == [1]
    assert announcer_out.samples() == [2]
    player.close()
    assert narrator_out.closed and announcer_out.closed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_player.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice_augmented.player'`

- [ ] **Step 3: Implement `player.py`**

`src/claude_voice_augmented/player.py`:

```python
"""Two audio channels (narrator, announcer) that play queued PCM clips as they stream in.

PCM is 16-bit signed mono in native byte order (little-endian on every Mac),
matching ElevenLabs' pcm_22050 output.
"""

from __future__ import annotations

import logging
import queue
import threading
from array import array
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from typing import Protocol

from .config import SAMPLE_RATE

log = logging.getLogger(__name__)

NARRATOR = "narrator"
ANNOUNCER = "announcer"
FADE_SECONDS = 0.1

Source = Callable[[], Iterable[bytes]]
ErrorHandler = Callable[[str, BaseException], None]


class OutputError(Exception):
    pass


class Output(Protocol):
    def write(self, pcm: bytes) -> None: ...
    def reopen(self) -> None: ...
    def close(self) -> None: ...


class SoundDeviceOutput:
    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self._rate = sample_rate
        self._stream = None

    def write(self, pcm: bytes) -> None:
        import sounddevice as sd

        try:
            if self._stream is None:
                self._stream = sd.RawOutputStream(
                    samplerate=self._rate, channels=1, dtype="int16", latency="low"
                )
                self._stream.start()
            self._stream.write(pcm)
        except sd.PortAudioError as exc:
            raise OutputError(str(exc)) from exc

    def reopen(self) -> None:
        import sounddevice as sd

        self.close()
        # Re-scan devices so a newly connected default output is picked up.
        sd._terminate()
        sd._initialize()

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()  # lets buffered audio finish
                self._stream.close()
            except Exception:
                log.debug("error closing audio stream", exc_info=True)
            self._stream = None


def apply_gain(pcm: bytes, start: float, end: float) -> bytes:
    if not pcm or start == end == 1.0:
        return pcm
    samples = array("h")
    samples.frombytes(pcm)
    n = len(samples)
    for i in range(n):
        gain = start + (end - start) * (i + 1) / n
        value = int(samples[i] * gain)
        samples[i] = 32767 if value > 32767 else -32768 if value < -32768 else value
    return samples.tobytes()


class Clip:
    """Fetches one source's audio on a background thread; playback reads it as it arrives."""

    def __init__(self, source: Source):
        self._source = source
        self._queue: queue.Queue[bytes | BaseException | None] = queue.Queue()
        self._started = False
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self.done = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self) -> None:
        iterator = None
        try:
            iterator = iter(self._source())
            for data in iterator:
                if self._cancelled.is_set():
                    break
                self._queue.put(data)
        except BaseException as exc:  # handed to the playing thread
            self._queue.put(exc)
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
            self._queue.put(None)

    def chunks(self) -> Iterator[bytes]:
        self.start()
        while True:
            item = self._queue.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    def cancel(self) -> None:
        self._cancelled.set()
        self._queue.put(None)  # wake a reader blocked on the next chunk


class _ClipDropped(Exception):
    pass


class Channel:
    def __init__(
        self,
        name: str,
        output: Output,
        volume: float,
        on_error: ErrorHandler,
        frame_bytes: int = 2048,
        sample_rate: int = SAMPLE_RATE,
    ):
        self.name = name
        self._output = output
        self._volume = volume
        self._duck = 1.0
        self._gain = volume
        self._on_error = on_error
        self._frame_bytes = max(2, frame_bytes - frame_bytes % 2)
        self._fade_bytes = int(sample_rate * FADE_SECONDS) * 2
        self._queue: deque[Clip] = deque()
        self._current: Clip | None = None
        self._generation = 0
        self._cv = threading.Condition()
        threading.Thread(target=self._run, name=f"channel-{name}", daemon=True).start()

    def enqueue(self, source: Source) -> Clip:
        clip = Clip(source)
        with self._cv:
            self._queue.append(clip)
            if len(self._queue) + (1 if self._current else 0) <= 2:
                clip.start()  # playing or next up: fetch now
            self._cv.notify()
        return clip

    def play_blocking(self, source: Source, timeout: float | None = None) -> None:
        self.enqueue(source).done.wait(timeout)

    def clear(self) -> None:
        with self._cv:
            self._generation += 1
            for clip in self._queue:
                clip.cancel()
                clip.done.set()
            self._queue.clear()
            if self._current is not None:
                self._current.cancel()

    def duck(self, factor: float) -> None:
        self._duck = factor

    def unduck(self) -> None:
        self._duck = 1.0

    def close(self) -> None:
        self._output.close()

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._queue:
                    self._cv.wait()
                clip = self._queue.popleft()
                self._current = clip
                generation = self._generation
                if self._queue:
                    self._queue[0].start()
            try:
                self._play(clip, generation)
            except _ClipDropped:
                pass
            except Exception as exc:
                log.warning("%s clip failed: %s", self.name, exc)
                self._on_error(self.name, exc)
            finally:
                with self._cv:
                    self._current = None
                clip.done.set()

    def _play(self, clip: Clip, generation: int) -> None:
        leftover = b""
        for data in clip.chunks():
            data = leftover + data
            usable = len(data) - len(data) % 2
            data, leftover = data[:usable], data[usable:]
            for offset in range(0, len(data), self._frame_bytes):
                if self._generation != generation:
                    tail = data[offset : offset + self._fade_bytes]
                    self._write(apply_gain(tail, self._gain, 0.0))
                    self._gain = 0.0  # next clip fades in from silence
                    return
                target = self._volume * self._duck
                self._write(apply_gain(data[offset : offset + self._frame_bytes], self._gain, target))
                self._gain = target

    def _write(self, pcm: bytes) -> None:
        if not pcm:
            return
        try:
            self._output.write(pcm)
        except OutputError as exc:
            log.warning("%s output failed (%s); reopening", self.name, exc)
            self._output.reopen()
            raise _ClipDropped from exc


class Player:
    def __init__(
        self,
        narrator_volume: float,
        announcer_volume: float,
        on_error: ErrorHandler,
        output_factory: Callable[[], Output] = SoundDeviceOutput,
    ):
        self._channels = {
            NARRATOR: Channel(NARRATOR, output_factory(), narrator_volume, on_error),
            ANNOUNCER: Channel(ANNOUNCER, output_factory(), announcer_volume, on_error),
        }

    def enqueue(self, channel: str, source: Source) -> None:
        self._channels[channel].enqueue(source)

    def play_blocking(self, channel: str, source: Source, timeout: float | None = None) -> None:
        self._channels[channel].play_blocking(source, timeout)

    def clear(self, channel: str) -> None:
        self._channels[channel].clear()

    def duck(self, channel: str, factor: float) -> None:
        self._channels[channel].duck(factor)

    def unduck(self, channel: str) -> None:
        self._channels[channel].unduck()

    def close(self) -> None:
        for ch in self._channels.values():
            ch.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_player.py -v && uv run ruff check .`
Expected: all PASS. Run the file three times in a row to make sure the threaded tests aren't flaky.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice_augmented/player.py tests/test_player.py
git commit -m "feat: add two-channel streaming audio player" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Per-session watcher

**Files:**
- Create: `src/claude_voice_augmented/watcher.py`
- Test: `tests/test_watcher.py`

**Interfaces:**
- Consumes:
  - `SessionState`, `pid_alive`, `read_last_speaker`, `write_last_speaker`, `announcer_lock` (Task 2)
  - `read_focus` (Task 2)
  - `TranscriptReader` (Task 3)
  - `to_speech`, `chunk` (Task 4)
  - `label_for`, `git_branch`, `announcement_line` (Task 5)
  - `TTS`, `TTSAuthError` (Task 6)
  - `NARRATOR`, `ANNOUNCER` (Task 7)
  - `Config` (Task 1)
- Produces:
  - `class PlayerLike(Protocol)` with `enqueue`, `play_blocking`, `clear`, `duck`, `unduck` (same signatures as `Player`)
  - `Watcher(session, root, config, tts, player, reader, announce, *, now=time.time, branch_lookup=git_branch, say=say_aloud)`:
    - `tick() -> bool`: False means exit.
    - `run(interval: float = 0.1, sleep=time.sleep) -> None`
    - `label() -> str`
    - `handle_player_error(channel: str, exc: BaseException) -> None`
  - `play_announcement(text, player, tts, voice_id, root, lock_timeout=30.0, duck_factor=0.5) -> bool`
  - `AnnouncerWorker(play: Callable[[str], object])` with `submit(line: str) -> None`
  - `say_aloud(text: str) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/test_watcher.py`:

```python
import json
import os

import pytest

from claude_voice_augmented.config import Config
from claude_voice_augmented.control import (
    SessionMeta,
    SessionState,
    announcer_lock,
    read_last_speaker,
    write_last_speaker,
)
from claude_voice_augmented.focus import write_focus
from claude_voice_augmented.player import ANNOUNCER, NARRATOR
from claude_voice_augmented.transcript import TranscriptReader
from claude_voice_augmented.tts import TTSAuthError
from claude_voice_augmented.watcher import Watcher, play_announcement

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_watcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice_augmented.watcher'`

- [ ] **Step 3: Implement `watcher.py`**

`src/claude_voice_augmented/watcher.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_watcher.py -v && uv run ruff check .`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice_augmented/watcher.py tests/test_watcher.py
git commit -m "feat: add per-session watcher with focus and announcements" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Hook handling

**Files:**
- Create: `src/claude_voice_augmented/hooks.py`
- Test: `tests/test_hooks.py`

**Interfaces:**
- Consumes:
  - `Config`, `load_config`, `DEFAULT_ENV_PATH` (Task 1)
  - `DEFAULT_ROOT`, `SessionMeta`, `SessionState`, `cleanup_stale`, `list_sessions`, `watcher_running`, `logs_dir` (Task 2)
  - `read_focus`, `write_focus` (Task 2)
  - `ANNOUNCED_EVENTS` (Task 5)
- Produces:
  - `handle(payload: dict, *, root: Path, config: Config, spawn: Callable[[str], int], now: float, claude_pid: Callable[[], int | None]) -> dict | None`
  - `spawn_watcher(session_id: str) -> int`
  - `stop_watcher(session: SessionState) -> None`
  - `find_claude_pid(start_pid: int | None = None, ps: Callable[[int], tuple[int, str] | None] = ..., max_depth: int = 6) -> int | None`
  - `main(stdin=None, stdout=None, root: Path | None = None) -> int`: always returns 0.
- Constraint: no import of `httpx`, `sounddevice`, `player`, `tts`, or `watcher` anywhere in this module's import chain.

- [ ] **Step 1: Write the failing tests**

`tests/test_hooks.py`:

```python
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
    assert run("SessionStart", tmp_path, spawn, session_title="Login work", source="startup") is None
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_hooks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice_augmented.hooks'`

- [ ] **Step 3: Implement `hooks.py`**

`src/claude_voice_augmented/hooks.py`:

```python
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
    """Start `python -m claude_voice_augmented watch <id>` fully detached (like nohup … &)."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "claude_voice_augmented", "watch", session_id],
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
    session = SessionState(root, session_id)

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


def main(stdin: TextIO | None = None, stdout: TextIO | None = None, root: Path | None = None) -> int:
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_hooks.py -v && uv run ruff check .`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice_augmented/hooks.py tests/test_hooks.py
git commit -m "feat: handle Claude Code hook events" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: CLI commands

**Files:**
- Modify: `src/claude_voice_augmented/cli.py` (replace the Task 1 stub entirely)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `hooks.main` (Task 9)
  - `Watcher`, `AnnouncerWorker`, `play_announcement` (Task 8)
  - `Player`, `NARRATOR`, `ANNOUNCER` (Task 7)
  - `ElevenLabsTTS` (Task 6)
  - `TranscriptReader` (Task 3)
  - `label_for` (Task 5)
  - Control and focus functions (Task 2)
  - `load_config`, `DEFAULT_ENV_PATH` (Task 1)
- Produces:
  - `main(argv: list[str] | None = None) -> int` with subcommands `hook`, `watch SESSION_ID`, `narrate {on,off,focus} [--session ID]`, `doctor`, `say TEXT [--announcer]`
  - `cmd_narrate(action: str, session_id: str, root: Path) -> str`
- Constraint: heavy imports (`player`, `tts`, `watcher`, `sounddevice`) happen inside the command functions, so `cva hook` stays fast.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'cmd_narrate'`

- [ ] **Step 3: Implement `cli.py`**

Replace `src/claude_voice_augmented/cli.py` with:

```python
"""`cva` command line: hook entry point, watcher process, and manual tools."""

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
    session = SessionState(root, sid) if sid else None
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
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def cmd_watch(session_id: str) -> int:
    root = DEFAULT_ROOT
    session = SessionState(root, session_id)
    meta = session.read_meta()
    if meta is None:
        return 1
    _setup_logging(logs_dir(root) / f"{session_id}.log")
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


def cmd_doctor() -> int:
    print(f"Config file: {DEFAULT_ENV_PATH} ({'found' if DEFAULT_ENV_PATH.is_file() else 'missing'})")
    config = load_config()
    if config.missing:
        print(f"Missing settings: {', '.join(config.missing)}")
        return 1

    from .tts import ElevenLabsTTS, TTSError

    tts = ElevenLabsTTS(config.api_key, config.tts_model)
    ok = True
    for name, voice in (("Narrator", config.narrator_voice_id), ("Announcer", config.announcer_voice_id)):
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
    player = Player(config.narrator_volume, config.announcer_volume, lambda ch, exc: errors.append(exc))
    channel, voice = (
        (ANNOUNCER, config.announcer_voice_id) if announcer else (NARRATOR, config.narrator_voice_id)
    )
    player.play_blocking(channel, partial(tts.synthesize, text, voice), timeout=60)
    player.close()
    if errors:
        print(f"Playback failed: {errors[0]}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cva", description="Narrate Claude Code sessions.")
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
```

Because `cmd_watch` reads `DEFAULT_ROOT` from this module's globals, `test_watch_without_session_returns_error` can monkeypatch it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -v && uv run ruff check .`
Expected: the whole suite passes; `test_hooks_do_not_import_audio_or_http` still passes.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice_augmented/cli.py tests/test_cli.py
git commit -m "feat: add cva CLI commands" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Plugin, docs, drift test, and end-to-end check

**Files:**
- Create: `plugin/.claude-plugin/plugin.json`, `plugin/hooks/hooks.json`, `plugin/commands/narrate.md`, `.claude-plugin/marketplace.json`, `README.md` (overwrite the empty file), `tests/test_plugin.py`, `tests/test_live.py`

**Interfaces:**
- Consumes: the `cva` CLI (Task 10), `TranscriptReader` (Task 3).
- Produces: an installable local plugin, `claude-voice-augmented@claude-voice-augmented`.

- [ ] **Step 1: Write the failing plugin tests**

`tests/test_plugin.py`:

```python
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
HOOKS = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]


def test_all_events_call_cva_hook():
    expected = {"SessionStart", "SessionEnd", "UserPromptSubmit", "Stop", "StopFailure",
                "PermissionRequest", "Notification"}
    assert set(HOOKS) == expected
    for groups in HOOKS.values():
        for group in groups:
            assert [h["command"] for h in group["hooks"]] == ["cva hook"]


def test_notification_only_matches_idle_prompt():
    # Review Focus 1: permission prompts are announced via PermissionRequest only.
    assert [g.get("matcher") for g in HOOKS["Notification"]] == ["idle_prompt"]


def test_manifests_agree_on_name():
    plugin = json.loads((ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert plugin["name"] == "claude-voice-augmented"
    assert market["plugins"][0]["name"] == plugin["name"]
    assert market["plugins"][0]["source"] == "./plugin"


def test_narrate_command_passes_session_id():
    text = (ROOT / "plugin" / "commands" / "narrate.md").read_text()
    assert "cva narrate $ARGUMENTS --session" in text
    assert "${CLAUDE_SESSION_ID}" in text
```

Run: `uv run pytest tests/test_plugin.py -v`
Expected: FAIL with `FileNotFoundError` for `plugin/hooks/hooks.json`.

- [ ] **Step 2: Create the plugin files**

`plugin/.claude-plugin/plugin.json`:

```json
{
  "name": "claude-voice-augmented",
  "version": "0.1.0",
  "description": "Narrates the current Claude Code session with ElevenLabs and announces other sessions' events on a quieter voice.",
  "author": { "name": "kiabq" }
}
```

`plugin/hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "cva hook", "timeout": 10 }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "command": "cva hook", "timeout": 10 }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "cva hook", "timeout": 10 }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "cva hook", "timeout": 10 }] }],
    "StopFailure": [{ "hooks": [{ "type": "command", "command": "cva hook", "timeout": 10 }] }],
    "PermissionRequest": [{ "hooks": [{ "type": "command", "command": "cva hook", "timeout": 10 }] }],
    "Notification": [
      { "matcher": "idle_prompt", "hooks": [{ "type": "command", "command": "cva hook", "timeout": 10 }] }
    ]
  }
}
```

`plugin/commands/narrate.md`:

```markdown
---
description: Turn narration on or off for this session, or make it the narrated session
argument-hint: on | off | focus
allowed-tools: Bash(cva narrate:*)
---

!`cva narrate $ARGUMENTS --session "${CLAUDE_SESSION_ID}"`

Repeat the line above to the user, word for word, and nothing else.
```

`.claude-plugin/marketplace.json`:

```json
{
  "name": "claude-voice-augmented",
  "owner": { "name": "kiabq" },
  "plugins": [
    {
      "name": "claude-voice-augmented",
      "source": "./plugin",
      "description": "ElevenLabs narration for Claude Code sessions."
    }
  ]
}
```

Run: `uv run pytest tests/test_plugin.py -v`
Expected: all PASS.

- [ ] **Step 3: Add the opt-in format-drift test**

`tests/test_live.py`:

```python
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_voice_augmented.transcript import TranscriptReader


@pytest.mark.live
def test_transcript_format_still_parses(tmp_path):
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not installed")
    result = subprocess.run(
        ["claude", "-p", "Reply with exactly: narrator check", "--output-format", "json"],
        cwd=tmp_path, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    session_id = json.loads(result.stdout)["session_id"]
    matches = list((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    assert matches, "transcript file not found"
    blocks = TranscriptReader(matches[0], start_at_end=False).read_new()
    assert any("narrator check" in block.text.lower() for block in blocks)
```

Run: `uv run pytest -m live -v`
Expected: PASS (it makes one small real Claude request). Then run `uv run pytest` and confirm the live test is deselected by default.

- [ ] **Step 4: Write `README.md`**

```markdown
# claude-voice-augmented

Narrates the Claude Code session you're working in with an ElevenLabs voice, and
announces when your other sessions finish, fail, or need you, on a second, quieter voice.

macOS only for now, tested in Ghostty.

## How it works

- Plugin hooks start a small watcher process for every Claude Code session.
- The watcher reads the session transcript and speaks Claude's prose; code blocks are skipped.
- Only the **current session** (the one you most recently sent a prompt to) is narrated.
- Other sessions announce events by name: "six-three-nine-bravo finished."
- Sessions are named by `/rename` title, then git branch, then a short spelled-out ID.

## Install

1. Install the CLI (puts `cva` in `~/.local/bin`, which must be on your `PATH`):

       uv tool install --editable /path/to/claude-voice-augmented

2. Configure:

       mkdir -p ~/.config/claude-voice-augmented
       cp .env.example ~/.config/claude-voice-augmented/.env
       # fill in ELEVENLABS_API_KEY and the two voice IDs
       cva doctor
       cva say "Narrator check."
       cva say "Announcer check." --announcer

3. Install the plugin from inside Claude Code:

       /plugin marketplace add /path/to/claude-voice-augmented
       /plugin install claude-voice-augmented@claude-voice-augmented

   Restart your Claude Code sessions afterwards.

## Use

- `/narrate off` / `/narrate on`: narration for this session.
- `/narrate focus`: narrate this session without sending a prompt.
- `CVA_ENABLED_BY_DEFAULT=false` starts new sessions silent.

## Troubleshooting

- Hook errors: `~/.cache/claude-voice-augmented/logs/hooks.log`
- Watcher logs: `~/.cache/claude-voice-augmented/logs/<session-id>.log`
- After a Claude Code upgrade, run `uv run pytest -m live` to check that the transcript format still parses.
```

- [ ] **Step 5: Commit**

```bash
git add plugin .claude-plugin README.md tests/test_plugin.py tests/test_live.py
git commit -m "feat: add Claude Code plugin, README, and transcript drift test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: End-to-end check in Ghostty (manual, needs the user)**

The user does these steps, because they need an ElevenLabs key, speakers, and interactive sessions. Record each result in the final report.

1. `uv tool install --editable .`, fill in `~/.config/claude-voice-augmented/.env`, then `cva doctor` → all ok.
2. `cva say "Narrator check."` and `cva say "Announcer check." --announcer` → two different voices; the announcer is quieter.
3. Install the plugin (README step 3). Open two Ghostty tabs, A and B, each running `claude`.
4. In A, ask for a task with a few tool calls. A's prose is narrated block by block, starting with A's label.
5. While A is still working, send a prompt in B. A's narration fades out within a moment; B is narrated from then on, starting with B's label.
6. When A finishes, the announcer says "<A's label> finished." while B keeps talking at lower volume.
7. Trigger a permission prompt in A while B is current. Exactly **one** "needs permission" announcement plays.
8. In B, run `/narrate off`, then `/narrate on`. The confirmation names B. **If it says "No narrator is running for this session" or names A**, `${CLAUDE_SESSION_ID}` isn't substituted in plugin commands. The focus fallback still works for the current session; note this in the report.
9. Run `ps -o ppid=,comm= -p $(pgrep -n -f "claude_voice_augmented watch")` and check that the watcher's metadata in `~/.cache/claude-voice-augmented/sessions/*/meta.json` has a non-null `claude_pid`. **If it is null**, the Claude Code process isn't named `claude` on this install. Note the actual name, so `find_claude_pid` can be adjusted.
10. Close tab A with `exit`. Its session folder disappears and its watcher process is gone (`pgrep -f "claude_voice_augmented watch"` shows only B's).

Fix anything that fails with a new failing test first, then the code.
