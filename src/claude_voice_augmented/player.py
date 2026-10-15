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


# PortAudio init/terminate is process-global: serialize it across all outputs.
_PORTAUDIO_LOCK = threading.Lock()


class SoundDeviceOutput:
    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self._rate = sample_rate
        self._stream = None

    def write(self, pcm: bytes) -> None:
        import sounddevice as sd

        try:
            with _PORTAUDIO_LOCK:
                if self._stream is None:
                    self._stream = sd.RawOutputStream(
                        samplerate=self._rate, channels=1, dtype="int16", latency="low"
                    )
                    self._stream.start()
                stream = self._stream
            stream.write(pcm)  # blocking; kept outside the lock so channels play concurrently
        except sd.PortAudioError as exc:
            raise OutputError(str(exc)) from exc

    def reopen(self) -> None:
        import sounddevice as sd

        with _PORTAUDIO_LOCK:
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
            try:
                close = getattr(iterator, "close", None)
                if close is not None:
                    close()
            except Exception:
                log.debug("error closing source iterator", exc_info=True)
            finally:
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
                frame = data[offset : offset + self._frame_bytes]
                self._write(apply_gain(frame, self._gain, target))
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
