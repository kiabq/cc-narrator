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
