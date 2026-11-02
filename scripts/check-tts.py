"""Synthesize a Chinese fixture without ASR or LLM. Candidate key via stdin."""
import asyncio
import json
import os
from pathlib import Path
import sys
import wave

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
sys.path.insert(0, str(ROOT / 'services/agent'))
from qwen_tts import QwenTTS


async def main():
    if '--candidate' in sys.argv:
        key = sys.stdin.readline().strip()
        if not key:
            raise ValueError('Missing candidate key')
        os.environ['DASHSCOPE_TTS_API_KEY'] = key
        os.environ['DASHSCOPE_API_KEY'] = key  # Isolated test process only.
    engine = QwenTTS()
    try:
        async with engine.synthesize('你好，这是千问文字转语音的独立测试。如果你听到这句话，说明语音合成已成功。') as stream:
            pcm = b''.join([bytes(event.frame.data) async for event in stream])
        import array
        samples = array.array('h', pcm)
        peak = max(map(abs, samples), default=0)
        if len(samples) < 2400 or peak < 100:
            raise ValueError('Empty or silent synthesis')
        target = ROOT / 'BigApple输出' / 'tts-check.wav'
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(pcm)
        print(json.dumps({'ok': True, 'seconds': len(samples) / 24000, 'peak': peak, 'file': str(target)}))
    finally:
        await engine.aclose()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        # Never print SDK exception strings: they may contain request credentials.
        import traceback
        provider_error = None
        raw = getattr(error, 'resp_body', None)
        if raw:
            try:
                body = json.loads(raw)
                provider_error = {k: body[k] for k in ('code', 'message') if isinstance(body.get(k), str)}
                for k, value in provider_error.items():
                    for name, secret in os.environ.items():
                        if len(secret) > 12 and any(word in name for word in ('KEY', 'SECRET', 'TOKEN')):
                            value = value.replace(secret, '[redacted]')
                    provider_error[k] = value[:300]
            except (ValueError, TypeError):
                pass
        print(json.dumps({'ok': False, 'error_type': type(error).__name__,
                          'http_status': getattr(error, 'status_code', None),
                          'provider_error': provider_error,
                          'frames': [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                                     for f in traceback.extract_tb(error.__traceback__)]}))
        sys.exit(1)
