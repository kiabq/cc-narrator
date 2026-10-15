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
