import json

import pytest

from app.elevenlabs import ElevenLabsConfig, ElevenLabsError, ElevenLabsSpeechClient


def config():
    return ElevenLabsConfig(api_key="test-key", voice_id="test-voice")


def test_tts_and_asr_payloads():
    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append((method, url, headers, body, timeout))
        if "/text-to-speech/" in url:
            return 200, b"ID3fake-mp3"
        return 200, json.dumps({"language_code": "zho", "text": "你好，人工智能电话助手"}).encode()

    client = ElevenLabsSpeechClient(config(), transport)
    audio = client.synthesize("你好")
    assert client.transcribe_mp3(audio) == "你好，人工智能电话助手"
    assert json.loads(calls[0][3])["model_id"] == "eleven_v4"
    assert calls[0][2]["xi-api-key"] == "test-key"
    assert b'name="model_id"\r\n\r\nscribe_v2' in calls[1][3]
    assert b'name="file"; filename="speech.mp3"' in calls[1][3]


def test_transcribe_browser_audio_uses_supplied_format():
    def transport(method, url, headers, body, timeout):
        assert headers["Content-Type"].startswith("multipart/form-data")
        assert b'filename="recording.webm"' in body
        assert b"Content-Type: audio/webm" in body
        return 200, json.dumps({"text": "浏览器录音"}).encode()

    client = ElevenLabsSpeechClient(config(), transport)
    assert client.transcribe(b"webm-audio", filename="recording.webm", content_type="audio/webm") == "浏览器录音"


def test_permission_error_is_redacted():
    def transport(*_):
        return 401, json.dumps({"detail": {"message": "missing permission"}}).encode()

    client = ElevenLabsSpeechClient(config(), transport)
    with pytest.raises(ElevenLabsError, match="missing permission") as error:
        client.synthesize("test")
    assert error.value.status_code == 401
    assert "test-key" not in str(error.value)
