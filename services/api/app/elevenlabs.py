from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ElevenLabsError(RuntimeError):
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
class ElevenLabsConfig:
    api_key: str
    base_url: str = "https://api.elevenlabs.io/v1"
    tts_model: str = "eleven_v4"
    voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    output_format: str = "mp3_44100_128"
    asr_model: str = "scribe_v2"
    language: str = "zh"


class ElevenLabsSpeechClient:
    def __init__(self, config: ElevenLabsConfig, transport: Transport = _transport):
        if not config.api_key:
            raise ValueError("ELEVENLABS_API_KEY is required")
        if not config.voice_id:
            raise ValueError("TTS_VOICE_ID is required")
        self.config = config
        self.transport = transport

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"xi-api-key": self.config.api_key}

    def synthesize(self, text: str, timeout: float = 90) -> bytes:
        if not text.strip():
            raise ValueError("TTS text must not be blank")
        query = urlencode({"output_format": self.config.output_format})
        url = f"{self.config.base_url.rstrip('/')}/text-to-speech/{self.config.voice_id}?{query}"
        payload = {"text": text, "model_id": self.config.tts_model}
        status, body = self.transport(
            "POST",
            url,
            {**self.auth_headers, "Content-Type": "application/json"},
            json.dumps(payload, ensure_ascii=False).encode(),
            timeout,
        )
        self._raise_for_error(status, body)
        if not (body.startswith(b"ID3") or body.startswith(b"\xff")):
            raise ElevenLabsError(status, "TTS response was not an MP3 file")
        return body

    def transcribe_mp3(self, audio: bytes, timeout: float = 120) -> str:
        if not audio:
            raise ValueError("ASR input must not be empty")
        boundary = f"persona-voice-{uuid.uuid4().hex}"
        body = self._multipart(
            boundary,
            fields={
                "model_id": self.config.asr_model,
                "language_code": self.config.language,
                "tag_audio_events": "false",
            },
            filename="speech.mp3",
            content_type="audio/mpeg",
            audio=audio,
        )
        status, response = self.transport(
            "POST",
            f"{self.config.base_url.rstrip('/')}/speech-to-text",
            {**self.auth_headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
            body,
            timeout,
        )
        self._raise_for_error(status, response)
        try:
            transcript = json.loads(response).get("text", "").strip()
        except (json.JSONDecodeError, AttributeError) as error:
            raise ElevenLabsError(status, "ASR response was not valid JSON") from error
        if not transcript:
            raise ElevenLabsError(status, "ASR response did not contain a transcript")
        return transcript

    @staticmethod
    def _multipart(
        boundary: str,
        fields: dict[str, str],
        filename: str,
        content_type: str,
        audio: bytes,
    ) -> bytes:
        marker = f"--{boundary}\r\n".encode()
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend([
                marker,
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode(),
            ])
        chunks.extend([
            marker,
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            audio,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        return b"".join(chunks)

    @staticmethod
    def _raise_for_error(status: int, body: bytes) -> None:
        if 200 <= status < 300:
            return
        message = f"ElevenLabs request failed with HTTP {status}"
        try:
            detail = json.loads(body).get("detail", {})
            if isinstance(detail, dict):
                message = detail.get("message", message)
            elif isinstance(detail, str):
                message = detail
        except (json.JSONDecodeError, AttributeError):
            pass
        raise ElevenLabsError(status, message)

