import pytest

from cc_narrator.events import ANNOUNCED_EVENTS, announcement_line


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
