"""Real provider test: require non-silent audio before remaining text/end_input.

No phone call. Loads server-local protected .env, never prints provider errors.
"""
import asyncio
import array
import json
from pathlib import Path
import sys
import time
from dotenv import load_dotenv

root=Path(__file__).resolve().parents[1]
load_dotenv(root/'.env')
sys.path.insert(0,str(root/'services/agent'))
from qwen_tts import QwenTTS

async def main():
    engine=QwenTTS()
    assert engine.mode=='duplex-v1'
    stream=engine.stream()
    first=asyncio.Event(); samples=array.array('h'); t0=time.perf_counter(); first_at=None
    async def consume():
        nonlocal first_at
        async for event in stream:
            if first_at is None: first_at=time.perf_counter();first.set()
            samples.frombytes(bytes(event.frame.data))
    reader=asyncio.create_task(consume())
    try:
        stream.push_text('你好，这是千问双向流式语音测试，')
        await asyncio.wait_for(first.wait(),15)
        assert not reader.done()
        stream.push_text('这一句话是在收到第一段声音之后才发送的。')
        stream.end_input()
        await asyncio.wait_for(reader,30)
        assert max(map(abs,samples),default=0)>100
        print(json.dumps({'ok':True,'audio_before_remaining_text':True,
            'first_audio_seconds':round(first_at-t0,3),
            'audio_seconds':round(len(samples)/24000,3),'peak':max(map(abs,samples))}))
    finally:
        await stream.aclose()
        reader.cancel();await asyncio.gather(reader,return_exceptions=True)
        await engine.aclose()

if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__}));sys.exit(1)
