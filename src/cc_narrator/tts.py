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
