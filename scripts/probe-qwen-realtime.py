"""Real Qwen Realtime probe, synthetic test utterances only; never dials a phone."""
import asyncio
import base64
import collections
import json
import os
from pathlib import Path
import sys
import time

import aiohttp
from dotenv import load_dotenv
from livekit import rtc

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
sys.path.insert(0, str(ROOT / 'services/agent'))
from qwen_tts import QwenTTS

URL = 'wss://ws-kc0oqyijpss62nix.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.1-realtime-flash'


async def fixture(text):
    engine = QwenTTS()
    resampler = rtc.AudioResampler(24000, 16000, num_channels=1)
    frames = []
    try:
        async with engine.synthesize(text) as stream:
            async for event in stream:
                frames.extend(resampler.push(event.frame))
        frames.extend(resampler.flush())
        return b''.join(bytes(frame.data) for frame in frames)
    finally:
        await engine.aclose()


async def main():
    key = os.environ['DASHSCOPE_API_KEY']
    pcm = await fixture('你好，请告诉我一天有多少个小时？')
    report = {'model':'qwen-audio-3.1-realtime-flash', 'synthetic_fixture':True,
              'phone_call':False, 'input_seconds':len(pcm)/32000, 'events':collections.Counter()}
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(URL,headers={'Authorization':'Bearer '+key}) as ws:
            async def receive():
                msg = await asyncio.wait_for(ws.receive(),20)
                if msg.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError('unexpected websocket close')
                e = json.loads(msg.data)
                report['events'][e['type']] += 1
                if e['type']=='error':
                    raise RuntimeError(str(e.get('error',{})).replace(key,'[REDACTED]')[:400])
                return e
            await ws.send_json({'type':'session.update','session':{
                'modalities':['text','audio'],'voice':'longanqian',
                'instructions':'你是中文测试助手。直接简短回答，不反问。',
                'turn_detection':{'type':'server_vad','threshold':0.5,'silence_duration_ms':500}}})
            while (await receive())['type']!='session.updated': pass
            sent_end = None
            async def send():
                nonlocal sent_end
                start=time.monotonic()
                for offset in range(0,len(pcm),640):
                    await ws.send_json({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm[offset:offset+640]).decode()})
                    await asyncio.sleep(max(0,start+(offset+640)/32000-time.monotonic()))
                sent_end=time.monotonic()
                for _ in range(100):
                    await ws.send_json({'type':'input_audio_buffer.append','audio':base64.b64encode(bytes(640)).decode()})
                    await asyncio.sleep(.02)
            sender=asyncio.create_task(send())
            audio_bytes=0
            try:
                while True:
                    e=await receive(); t=e['type']
                    if t=='response.audio.delta':
                        if not audio_bytes:
                            report['input_end_to_first_audio_seconds']=round(time.monotonic()-sent_end,3) if sent_end else None
                        audio_bytes+=len(base64.b64decode(e['delta']))
                    if t=='conversation.item.input_audio_transcription.completed':report['user_transcript']=e.get('transcript')
                    if t=='response.audio_transcript.done':report['assistant_transcript']=e.get('transcript')
                    if t=='response.done':break
            finally:
                sender.cancel();await asyncio.gather(sender,return_exceptions=True)
            report['output_audio_seconds']=audio_bytes/48000
            await ws.send_json({'type':'session.update','session':{'tools':[{
                'type':'function','name':'finish_consultation','description':'结束对话',
                'parameters':{'type':'object','properties':{'farewell':{'type':'string'}},'required':['farewell']}}]}})
            while (await receive())['type']!='session.updated':pass
            await ws.send_json({'type':'conversation.item.create','item':{'type':'message','role':'user',
                'content':[{'type':'input_text','text':'结束测试，请调用finish_consultation，farewell是再见，不要普通回复。'}]}})
            await ws.send_json({'type':'response.create','response':{'tool_choice':'required'}})
            while True:
                e=await receive()
                if e['type']=='response.function_call_arguments.done':
                    report['tool_call']={k:e.get(k) for k in ('name','arguments')}
                if e['type']=='response.done':break
            report['ok']=bool(audio_bytes and report.get('user_transcript') and report.get('assistant_transcript') and report.get('tool_call'))
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['ok']:raise SystemExit(1)


if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__,
            'detail':str(error).replace(os.getenv('DASHSCOPE_API_KEY','__no_key__'),'[REDACTED]')[:450]},ensure_ascii=False))
        raise SystemExit(1)
