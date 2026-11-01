from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

import httpx


class ElevenLabsError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


Transport = Callable[[str, str, dict[str, str], bytes, float], tuple[int, bytes]]


def _transport(method: str, url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    if os.getenv("ELEVENLABS_CURL_CONNECT_TO") and shutil.which("curl"):
        return _curl_transport(method, url, headers, body, timeout)
    last_error: httpx.HTTPError | None = None
    for attempt in range(3):
        try:
            response = httpx.request(method, url, headers=headers, content=body, timeout=timeout)
            return response.status_code, response.content
        except httpx.HTTPError as error:
            last_error = error
            time.sleep(0.5 * (attempt + 1))
    if shutil.which("curl"):
        return _curl_transport(method, url, headers, body, timeout)
    raise ElevenLabsError(502, "ElevenLabs 网络连接失败，已自动重试 3 次") from last_error


def _curl_transport(method: str, url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    header_path = body_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as header_file:
            os.chmod(header_file.name, 0o600)
            header_path = header_file.name
            for name, value in headers.items():
                header_file.write(f"{name}: {value}\n")
        with tempfile.NamedTemporaryFile("wb", delete=False) as body_file:
            os.chmod(body_file.name, 0o600)
            body_path = body_file.name
            body_file.write(body)
        command = [
            "curl", "--silent", "--show-error", "--request", method,
            "--url", url, "--header", f"@{header_path}",
            "--data-binary", f"@{body_path}", "--max-time", str(int(timeout)),
            "--write-out", "\n%{http_code}",
        ]
        connect_to = os.getenv("ELEVENLABS_CURL_CONNECT_TO")
        if connect_to:
            command.extend(["--connect-to", connect_to])
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise ElevenLabsError(502, "ElevenLabs 网络连接失败，Python 与系统网络路径均不可用")
        response, separator, status = result.stdout.rpartition(b"\n")
        if not separator or not status.isdigit():
            raise ElevenLabsError(502, "ElevenLabs 网络响应格式无效")
        return int(status), response
    finally:
        for path in (header_path, body_path):
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass


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

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "speech.mp3",
        content_type: str = "audio/mpeg",
        timeout: float = 120,
    ) -> str:
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
            filename=filename,
            content_type=content_type,
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

    def transcribe_mp3(self, audio: bytes, timeout: float = 120) -> str:
        return self.transcribe(audio, timeout=timeout)

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
