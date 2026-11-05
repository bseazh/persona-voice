"""Real Baidu through LiveKit AgentSession; no phone, no fabricated replies."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from livekit import rtc
from livekit.agents import AgentSession

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/agent'))
from baidu_realtime import BaiduRealtime
from realtime_voice import RealtimeAssistant
spec=importlib.util.spec_from_file_location('harness',ROOT/'scripts/probe-qwen-agent-session.py')
harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)

async def main():
    events=[];messages=[];errors=[]
    model=BaiduRealtime(audit=lambda k,p:events.append({'kind':k,'payload':p}))
    session=AgentSession(llm=model)
    source,sink=harness.Input(),harness.Sink()
    session.input.audio=source;session.output.audio=sink
    @session.on('conversation_item_added')
    def message(e):
        if getattr(e.item,'role',None) in ('user','assistant'):
            messages.append({'role':e.item.role,'text':e.item.text_content})
    @session.on('error')
    def error(e):errors.append(type(e.error).__name__)
    try:
        await session.start(agent=RealtimeAssistant())
        await asyncio.sleep(2)
        pcm=subprocess.check_output(['ffmpeg','-v','error','-i',str(ROOT/'BigApple输出/baidu-lite-validation/input-1.aiff'),'-f','s16le','-ar','16000','-ac','1','-'])
        for offset in range(0,len(pcm),640):
            b=pcm[offset:offset+640].ljust(640,b'\0')
            await source.queue.put(rtc.AudioFrame(b,16000,1,320));await asyncio.sleep(.02)
        for _ in range(1000):
            await source.queue.put(rtc.AudioFrame(bytes(640),16000,1,320));await asyncio.sleep(.02)
            if any(m['role']=='assistant' for m in messages):break
    finally:
        await session.aclose();await model.aclose()
    result={'messages':messages,'errors':errors,'audio_frames':sink.frames,'events':events,'phone_call':False}
    result['ok']=sink.frames>0 and not errors and any(m['role']=='assistant' for m in messages)
    (ROOT/'BigApple输出/baidu-lite-validation/agent-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['ok']:raise SystemExit(1)

if __name__=='__main__':asyncio.run(main())
