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
