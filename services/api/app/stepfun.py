from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class StepFunError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


Transport = Callable[[str, str, dict[str, str], bytes, float], tuple[int, bytes]]


def _transport(method: str, url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


@dataclass(frozen=True)
class StepFunConfig:
    api_key: str
    base_url: str = "https://api.stepfun.com/v1"
    tts_model: str = "stepaudio-3-tts"
    tts_voice: str = "elegantgentle-female"
    asr_model: str = "stepaudio-3-asr-max"
    language: str = "zh"


class StepFunSpeechClient:
    def __init__(self, config: StepFunConfig, transport: Transport = _transport):
        if not config.api_key:
            raise ValueError("STEPFUN_API_KEY is required")
        if not config.tts_voice:
            raise ValueError("TTS_VOICE is required")
        self.config = config
        self.transport = transport

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def synthesize(self, text: str, timeout: float = 90) -> bytes:
        if not text.strip() or len(text) > 1000:
            raise ValueError("TTS text must contain 1-1000 characters")
        payload = {
            "model": self.config.tts_model,
            "input": text,
            "voice": self.config.tts_voice,
            "response_format": "wav",
            "sample_rate": 16000,
            "speed": 1.0,
        }
        status, body = self.transport(
            "POST",
            f"{self.config.base_url.rstrip('/')}/audio/speech",
            self.headers,
            json.dumps(payload, ensure_ascii=False).encode(),
            timeout,
        )
        self._raise_for_error(status, body)
        if not body.startswith(b"RIFF"):
            raise StepFunError(status, "TTS response was not a WAV file")
        return body

    def transcribe_wav(self, audio: bytes, timeout: float = 90) -> str:
        if not audio.startswith(b"RIFF"):
            raise ValueError("ASR input must be a WAV file")
        payload = {
            "audio": {
                "data": base64.b64encode(audio).decode(),
                "input": {
                    "transcription": {
                        "language": self.config.language,
                        "model": self.config.asr_model,
                        "enable_itn": True,
                        "enable_timestamp": False,
                    },
                    "format": {"type": "wav"},
                },
            }
        }
        headers = {**self.headers, "Accept": "text/event-stream"}
        status, body = self.transport(
            "POST",
            f"{self.config.base_url.rstrip('/')}/audio/asr/sse",
            headers,
            json.dumps(payload).encode(),
            timeout,
        )
        self._raise_for_error(status, body)
        for line in reversed(body.decode(errors="replace").splitlines()):
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                continue
            event = json.loads(data)
            if event.get("type") == "transcript.text.done":
                return str(event.get("text", "")).strip()
            if event.get("type") == "error":
                raise StepFunError(status, str(event.get("message", "ASR failed")))
        raise StepFunError(status, "ASR response did not contain a final transcript")

    @staticmethod
    def _raise_for_error(status: int, body: bytes) -> None:
        if 200 <= status < 300:
            return
        message = f"StepFun request failed with HTTP {status}"
        try:
            error = json.loads(body).get("error", {})
            message = error.get("message", message)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise StepFunError(status, message)

