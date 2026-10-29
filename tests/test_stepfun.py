import json

import pytest

from app.stepfun import StepFunConfig, StepFunError, StepFunSpeechClient


def config():
    return StepFunConfig(api_key="test-key", tts_voice="test-voice")


def test_tts_and_asr_payloads():
    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append((method, url, headers, json.loads(body), timeout))
        if url.endswith("/audio/speech"):
            return 200, b"RIFFfake-wave"
        events = 'data: {"type":"transcript.text.delta","delta":"你好"}\n\ndata: {"type":"transcript.text.done","text":"你好，世界"}\n\ndata: [DONE]\n'
        return 200, events.encode()

    client = StepFunSpeechClient(config(), transport)
    audio = client.synthesize("你好")
    assert client.transcribe_wav(audio) == "你好，世界"
    assert calls[0][3]["model"] == "stepaudio-3-tts"
    assert calls[1][3]["audio"]["input"]["transcription"]["model"] == "stepaudio-3-asr-max"
    assert calls[1][2]["Authorization"] == "Bearer test-key"


def test_quota_error_is_reported_without_secret():
    def transport(*_):
        return 402, b'{"error":{"message":"quota exceeded","type":"quota_exceeded"}}'

    client = StepFunSpeechClient(config(), transport)
    with pytest.raises(StepFunError, match="quota exceeded") as error:
        client.synthesize("test")
    assert error.value.status_code == 402
    assert "test-key" not in str(error.value)
