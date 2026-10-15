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
