"""Exercise the actual LiveKit realtime engine with Qwen; no room or phone."""
import asyncio
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import llm, function_tool

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
sys.path.insert(0,str(ROOT/'services/agent'))
sys.path.insert(0,str(ROOT/'scripts'))
from qwen_realtime import QwenRealtime
from importlib.util import spec_from_file_location, module_from_spec
spec=spec_from_file_location('fixture_probe',ROOT/'scripts/probe-qwen-realtime.py')
fixture_probe=module_from_spec(spec);spec.loader.exec_module(fixture_probe)


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--natural-ending',action='store_true')
    args=parser.parse_args()
    wire=[]
    model=QwenRealtime(audit=lambda kind,data:wire.append({'kind':kind,**data}))
    session=model.session()
    result={'phone_call':False,'events':[],'audio_frames':0,'transcripts':[],'functions':[]}
    tasks=[]
    completed=asyncio.Event()
    errors=[]
    class ErrorCapture(logging.Handler):
        def emit(self,record):
            if record.levelno>=logging.ERROR:
                errors.append('sdk_log:'+record.name+':'+(record.exc_info[0].__name__ if record.exc_info else 'error'))
    error_capture=ErrorCapture(level=logging.ERROR)
    logging.getLogger('livekit').addHandler(error_capture)
    @session.on('error')
    def error(e):errors.append(type(e.error).__name__)
    @session.on('input_audio_transcription_completed')
    def transcript(e):
        if e.is_final:result['transcripts'].append(e.transcript)
    @session.on('generation_created')
    def generation(e):
        async def consume():
            async def messages():
                async for m in e.message_stream:
                    async def text():
                        chunks=[]
                        async for t in m.text_stream:chunks.append(t)
                        result['events'].append(''.join(chunks))
                    async def audio():
                        async for frame in m.audio_stream:result['audio_frames']+=1
                    await asyncio.gather(text(),audio())
            async def functions():
                async for f in e.function_stream:result['functions'].append(f.name)
            await asyncio.gather(messages(),functions())
            completed.set()
        tasks.append(asyncio.create_task(consume()))
    @function_tool()
    async def finish_consultation(farewell:str):
        """Finish the conversation with a farewell."""
        return 'not executed in this probe'
    try:
        await session.update_instructions('你是中文测试助手，回答简短。要求结束时只调用finish_consultation，不输出普通文本。')
        await session.update_tools([finish_consultation])
        await asyncio.wait_for(session.generate_reply(instructions='简短说你好。'),15)
        await asyncio.wait_for(completed.wait(),20)
        result['greeting_ok']=result['audio_frames']>0
        completed.clear()
        pcm=await fixture_probe.fixture('请告诉我一天有多少个小时？')
        start=time.monotonic()
        for offset in range(0,len(pcm),640):
            chunk=pcm[offset:offset+640]
            session.push_audio(rtc.AudioFrame(data=chunk,sample_rate=16000,num_channels=1,samples_per_channel=len(chunk)//2))
            await asyncio.sleep(max(0,start+(offset+640)/32000-time.monotonic()))
        for _ in range(75):
            session.push_audio(rtc.AudioFrame(data=bytes(640),sample_rate=16000,num_channels=1,samples_per_channel=320))
            await asyncio.sleep(.02)
        await asyncio.wait_for(completed.wait(),20)
        completed.clear()
        if args.natural_ending:
            pcm=await fixture_probe.fixture('今天就聊到这里吧，再见，请挂断电话。')
            start=time.monotonic()
            for offset in range(0,len(pcm),640):
                chunk=pcm[offset:offset+640]
                session.push_audio(rtc.AudioFrame(data=chunk,sample_rate=16000,num_channels=1,samples_per_channel=len(chunk)//2))
                await asyncio.sleep(max(0,start+(offset+640)/32000-time.monotonic()))
            for _ in range(75):
                session.push_audio(rtc.AudioFrame(data=bytes(640),sample_rate=16000,num_channels=1,samples_per_channel=320))
                await asyncio.sleep(.02)
        else:
            chat=session.chat_ctx.copy()
            chat.add_message(role='user',content='结束测试，请调用finish_consultation，farewell是再见，不要普通回复。')
            await session.update_chat_ctx(chat)
            await asyncio.wait_for(session.generate_reply(instructions='现在调用finish_consultation结束测试。',tool_choice='required'),15)
        await asyncio.wait_for(completed.wait(),20)
        result['errors']=errors
        result['wire']=wire
        result['natural_ending']=args.natural_ending
        result['ok']=bool(result['greeting_ok'] and result['transcripts'] and result['functions'] and not errors)
    finally:
        await session.aclose()
        await asyncio.gather(*tasks,return_exceptions=True)
        await model.aclose()
        logging.getLogger('livekit').removeHandler(error_capture)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['ok']:raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
