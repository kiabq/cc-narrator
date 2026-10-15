"""Spoken session labels: title → git branch → short spelled-out ID."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

DEFAULT_BRANCHES = frozenset({"main", "master", "develop", "trunk"})

_DIGITS = dict(
    zip("0123456789", "zero one two three four five six seven eight nine".split(), strict=True)
)
_NATO = dict(
    zip(
        "abcdefghijklmnopqrstuvwxyz",
        (
            "alfa bravo charlie delta echo foxtrot golf hotel india juliett kilo lima mike "
            "november oscar papa quebec romeo sierra tango uniform victor whiskey xray "
            "yankee zulu"
        ).split(),
        strict=True,
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
