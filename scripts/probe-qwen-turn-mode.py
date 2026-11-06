"""Synthetic audio interruption probe; never places a phone call."""
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import time

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixture', ROOT/'scripts/probe-qwen-realtime.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


async def run(mode, repeat, backchannel, interrupt):
    events = []
    phase = 'opening'
    first_audio = asyncio.Event()
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(fixture.URL, headers={
            'Authorization': 'Bearer '+os.environ['DASHSCOPE_API_KEY']}) as ws:
            await ws.send_json({'type':'session.update','session':{
                'modalities':['text','audio'],'voice':'longanqian',
                'instructions':'你是测试助手。请详细讲述中国古代造纸的过程，至少讲一分钟；若用户要求停下，请停止并简短回应。',
                'turn_detection': {'type':mode,'threshold':.5, **({'silence_duration_ms':500} if mode=='server_vad' else {})}}})
            async def receive():
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:break
                    e=json.loads(msg.data)
                    if e['type']=='response.audio.delta':
                        first_audio.set()
                        continue
                    if e['type'].endswith('.delta') and 'ambient_audio' not in e['type']:continue
                    events.append({'at':time.time(),'phase':phase,'event':e})
            reader=asyncio.create_task(receive())
            async def audio(pcm, silence=0):
                pcm+=bytes(int(silence*32000))
                start=time.monotonic()
                for offset in range(0,len(pcm),640):
                    await ws.send_json({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm[offset:offset+640]).decode()})
                    await asyncio.sleep(max(0,start+(offset+640)/32000-time.monotonic()))
            try:
                await ws.send_json({'type':'conversation.item.create','item':{'type':'message','role':'user',
                    'content':[{'type':'input_text','text':'请开始详细讲述造纸的过程。'}]}})
                await ws.send_json({'type':'response.create'})
                await asyncio.wait_for(first_audio.wait(),20)
                await audio(bytes(32000))
                phase='backchannel'
                await audio(backchannel,3)
                phase='explicit_interrupt'
                await audio(interrupt,5)
            finally:
                await ws.close()
                await reader
    return {'mode':mode,'repeat':repeat,'phone_call':False,'synthetic_audio':True,'events':events}


async def main():
    backchannel=await fixture.fixture('嗯。')
    interrupt=await fixture.fixture('停一下，我想问另外一个问题。')
    results=[]
    for mode in ('server_vad','smart_turn_v2'):
        for repeat in (1,2):
            result=await run(mode,repeat,backchannel,interrupt)
            results.append(result)
            print(json.dumps({'mode':mode,'repeat':repeat,'events':[
                {'phase':e['phase'],'type':e['event']['type'],'reason':e['event'].get('reason')}
                for e in result['events'] if 'speech_' in e['event']['type'] or 'ambient_audio' in e['event']['type']
                or e['event']['type']=='error']},ensure_ascii=False),flush=True)
    target=ROOT/'BigApple输出'/'qwen-validation'/f'turn-mode-{time.time_ns()}.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(target)

if __name__=='__main__':asyncio.run(main())
