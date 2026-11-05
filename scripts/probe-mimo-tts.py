"""Real MiMo via production LiveKit adapter; no phone calls or saved audio."""
import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
sys.path.insert(0, str(ROOT / 'services/agent'))
from mimo_tts import MiMoTTS


async def main():
    engine = MiMoTTS()
    try:
        for n in (1, 2):
            start = time.monotonic()
            first = None
            frames = 0
            samples = 0
            peak = 0
            async with engine.synthesize('你好，这是一次语音合成测试。我们正在检查声音是否流畅。') as stream:
                async for event in stream:
                    if first is None: first = time.monotonic() - start
                    frames += 1
                    samples += event.frame.samples_per_channel
                    peak = max(peak, max(map(abs, event.frame.data), default=0))
            assert frames and peak > 100
            print(json.dumps({'test': n, 'adapter': 'MiMoTTS', 'first_frame_s': round(first, 3),
                              'frames': frames, 'audio_s': samples / 24000, 'peak': peak}), flush=True)
        # Stop a real request after its first frame, then ensure the same client works again.
        async with engine.synthesize('这是一段用于检查打断取消的较长测试语音。我们会中途停止播放，随后重新发起一次合成请求。') as stream:
            await anext(stream)
        async with engine.synthesize('再见。') as stream:
            frames = [event async for event in stream]
        assert frames
        print(json.dumps({'early_close_then_next_request': 'passed'}), flush=True)
    finally:
        await engine.aclose()


if __name__ == '__main__': asyncio.run(main())
