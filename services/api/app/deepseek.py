from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import httpx


class DeepSeekError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


Transport = Callable[[str, str, dict[str, str], bytes, float], tuple[int, bytes]]


def _transport(method: str, url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    try:
        response = httpx.request(method, url, headers=headers, content=body, timeout=timeout)
        return response.status_code, response.content
    except httpx.HTTPError as error:
        raise DeepSeekError(502, "DeepSeek network connection failed") from error


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig, transport: Transport = _transport):
        if not config.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required")
        self.config = config
        self.transport = transport

    def reply(self, transcript: str, history: list[dict[str, str]], timeout: float = 90) -> str:
        if not transcript.strip():
            raise ValueError("Transcript must not be blank")
        system = (
            "你叫小禾，是一个友好、自然的中文语音助手。回答要口语化、简洁，通常不超过三句话。"
            "不要使用 Markdown、列表符号或表情；不知道时如实说明。"
        )
        safe_history = [
            {"role": item["role"], "content": item["content"][:2000]}
            for item in history[-10:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}, *safe_history, {"role": "user", "content": transcript}],
            "temperature": 0.6,
            "max_tokens": 300,
        }
        status, body = self.transport(
            "POST",
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"},
            json.dumps(payload, ensure_ascii=False).encode(),
            timeout,
        )
        if not 200 <= status < 300:
            message = f"DeepSeek request failed with HTTP {status}"
            try:
                message = json.loads(body).get("error", {}).get("message", message)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise DeepSeekError(status, message)
        try:
            answer = json.loads(body)["choices"][0]["message"]["content"].strip()
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise DeepSeekError(status, "DeepSeek response did not contain an answer") from error
        if not answer:
            raise DeepSeekError(status, "DeepSeek returned an empty answer")
        return answer
