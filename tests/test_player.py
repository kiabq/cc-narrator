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
    on_error = lambda name, exc: errors.append((name, exc))  # noqa: E731
    return Channel("test", output, volume, on_error, frame_bytes)


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
    ch.enqueue(lambda: [pcm(12345)])
    assert wait_until(lambda: len(out.writes) >= 1)
    ch.clear()
    ch.play_blocking(lambda: [pcm(7)], timeout=2)
    samples = out.samples()
    assert 12345 not in samples
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
