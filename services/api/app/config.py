from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "data/calls.db")
    enable_real_calls: bool = _bool("ENABLE_REAL_CALLS")
    allowed_numbers: frozenset[str] = frozenset(
        item.strip()
        for item in os.getenv("ALLOWED_DESTINATION_NUMBERS", "").split(",")
        if item.strip()
    )
    mock_step_delay: float = float(os.getenv("MOCK_STEP_DELAY_SECONDS", "0.8"))
    max_concurrent_calls: int = int(os.getenv("MAX_CONCURRENT_CALLS", "1"))

    @property
    def livekit_configured(self) -> bool:
        required = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
        return all(os.getenv(name) and "REPLACE_ME" not in os.getenv(name, "") for name in required)

    @property
    def sip_configured(self) -> bool:
        required = ("SIP_OUTBOUND_TRUNK_ID",)
        return all(os.getenv(name) and "REPLACE_ME" not in os.getenv(name, "") for name in required)

    @property
    def stepfun_configured(self) -> bool:
        required = ("STEPFUN_API_KEY", "STT_MODEL", "TTS_MODEL", "TTS_VOICE")
        return all(os.getenv(name) and "REPLACE" not in os.getenv(name, "") for name in required)

    @property
    def elevenlabs_configured(self) -> bool:
        required = ("ELEVENLABS_API_KEY", "STT_MODEL", "TTS_MODEL", "TTS_VOICE_ID")
        return all(os.getenv(name) and "REPLACE" not in os.getenv(name, "") for name in required)


settings = Settings()
