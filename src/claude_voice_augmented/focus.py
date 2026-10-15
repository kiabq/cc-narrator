"""The current session: the one you most recently sent a prompt to."""

from __future__ import annotations

from pathlib import Path

from .control import atomic_write


def read_focus(root: Path) -> str | None:
    try:
        return (root / "focus").read_text().strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_focus(root: Path, session_id: str) -> None:
    atomic_write(root / "focus", session_id)
