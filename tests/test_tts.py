import json

import httpx
import pytest

from cc_narrator.tts import ElevenLabsTTS, TTSAuthError, TTSError


def make(handler, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ElevenLabsTTS("secret", "eleven_flash_v2_5", client=client, sleep=sleeps.append)


def test_streams_pcm_and_sends_expected_request():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["xi-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"\x01\x00\x02\x00")

    audio = b"".join(make(handler).synthesize("Hello.", "voice1"))
    assert audio == b"\x01\x00\x02\x00"
    assert seen["url"] == (
        "https://api.elevenlabs.io/v1/text-to-speech/voice1/stream?output_format=pcm_22050"
    )
    assert seen["key"] == "secret"
    assert seen["body"] == {"text": "Hello.", "model_id": "eleven_flash_v2_5"}


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_not_retried(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(TTSAuthError):
        list(make(handler).synthesize("x", "v"))
    assert len(calls) == 1


def test_server_error_retried_once_then_succeeds():
    responses = iter([httpx.Response(503), httpx.Response(200, content=b"ok")])
    sleeps = []
    assert b"".join(make(lambda r: next(responses), sleeps).synthesize("x", "v")) == b"ok"
    assert sleeps == [1.0]


def test_server_error_twice_raises():
    with pytest.raises(TTSError):
        list(make(lambda r: httpx.Response(429)).synthesize("x", "v"))


def test_timeout_retried_once():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, content=b"ok")

    assert b"".join(make(handler).synthesize("x", "v")) == b"ok"


def test_other_client_error_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(422, json={"detail": "bad"})

    with pytest.raises(TTSError) as err:
        list(make(handler).synthesize("x", "v"))
    assert not isinstance(err.value, TTSAuthError)
    assert len(calls) == 1


def test_voice_exists():
    def handler(request):
        assert request.url.path in ("/v1/voices/good", "/v1/voices/bad")
        return httpx.Response(200 if request.url.path.endswith("good") else 404)

    tts = make(handler)
    assert tts.voice_exists("good")
    assert not tts.voice_exists("bad")


def test_voice_exists_auth_error():
    with pytest.raises(TTSAuthError):
        make(lambda r: httpx.Response(401)).voice_exists("v")
