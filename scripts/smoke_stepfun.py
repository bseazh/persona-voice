#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.stepfun import StepFunConfig, StepFunError, StepFunSpeechClient  # noqa: E402


def load_env(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def main() -> int:
    load_env(ROOT / ".env")
    config = StepFunConfig(
        api_key=os.environ.get("STEPFUN_API_KEY", ""),
        base_url=os.environ.get("STEPFUN_BASE_URL", "https://api.stepfun.com/v1"),
        tts_model=os.environ.get("TTS_MODEL", "stepaudio-3-tts"),
        tts_voice=os.environ.get("TTS_VOICE", ""),
        asr_model=os.environ.get("STT_MODEL", "stepaudio-3-asr-max"),
        language=os.environ.get("STT_LANGUAGE", "zh"),
    )
    client = StepFunSpeechClient(config)
    text = "你好，我是人工智能电话助手。现在进行阶跃星辰语音合成和识别链路测试。"
    output = ROOT / "BigApple输出" / "stepfun-roundtrip.wav"
    output.parent.mkdir(exist_ok=True)

    try:
        audio = client.synthesize(text)
        output.write_bytes(audio)
        transcript = client.transcribe_wav(audio)
    except StepFunError as error:
        print(f"STEPFUN_FAILED HTTP={error.status_code}: {error}", file=sys.stderr)
        return 1

    print(f"TTS_OK bytes={len(audio)}")
    print(f"ASR_OK transcript={transcript}")
    print(f"AUDIO_PATH={output}")
    return 0 if transcript else 1


if __name__ == "__main__":
    raise SystemExit(main())

