"""Real provider + production consultation controller, with a timed audio sink.

No phone is dialled. Room deletion is captured locally, not sent to LiveKit.
This cannot verify handset playback or actual SIM hangup.
"""
import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import AgentSession
from livekit.agents.voice import io

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
sys.path.insert(0,str(ROOT/'services/agent'))
from qwen_realtime import QwenRealtime
from qwen_tts import QwenTTS
from consultation_voice import ConsultationAssistant, VoiceController

spec=importlib.util.spec_from_file_location('fixture_probe',ROOT/'scripts/probe-qwen-realtime.py')
fixture_probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_probe)


class Input(io.AudioInput):
    def __init__(self):
        super().__init__(label='synthetic-test-input')
        self.queue=asyncio.Queue()

    async def __anext__(self):
        return await self.queue.get()


class Sink(io.AudioOutput):
    def __init__(self):
        super().__init__(label='timed-test-sink',capabilities=io.AudioOutputCapabilities(pause=False))
        self.seconds=0
        self.frames=0

    async def capture_frame(self,frame):
        await super().capture_frame(frame)
        duration=frame.samples_per_channel/frame.sample_rate
        await asyncio.sleep(duration)
        self.seconds+=duration
        self.frames+=1

    def flush(self):
        super().flush()
        if self._pending_playback_count:
            self.on_playback_finished(playback_position=self.seconds,interrupted=False)
        self.seconds=0

    def clear_buffer(self):
        super().flush()
        if self._pending_playback_count:
            self.on_playback_finished(playback_position=self.seconds,interrupted=True)
        self.seconds=0


async def main():
    events=[]
    model=QwenRealtime()
    tts=QwenTTS()
    session=AgentSession(llm=model,tts=tts)
    source,sink=Input(),Sink()
    session.input.audio=source
    session.output.audio=sink
    messages=[]
    errors=[]
    class ErrorCapture(logging.Handler):
        def emit(self,record):
            if record.levelno>=logging.ERROR:
                errors.append('sdk_log:'+record.name+':'+(record.exc_info[0].__name__ if record.exc_info else 'error'))
    error_capture=ErrorCapture(level=logging.ERROR)
    logging.getLogger('livekit').addHandler(error_capture)
    ended=asyncio.Event()
    @session.on('conversation_item_added')
    def message(e):
        if getattr(e.item,'role',None) in ('user','assistant'):
            messages.append({'role':e.item.role,'text':e.item.text_content})
    @session.on('error')
    def error(e):errors.append(type(e.error).__name__)
    async def flush():pass
    async def delete_room(request):ended.set()
    journal=SimpleNamespace(emit=lambda kind,payload=None:events.append({'type':kind,'data':payload}),flush=flush)
    ctx=SimpleNamespace(room=SimpleNamespace(name='probe-no-real-room'),
                        api=SimpleNamespace(room=SimpleNamespace(delete_room=delete_room)))
    controller=VoiceController(ctx,session,journal)
    async def send(text):
        pcm=await fixture_probe.fixture(text)
        for offset in range(0,len(pcm),640):
            chunk=pcm[offset:offset+640]
            await source.queue.put(rtc.AudioFrame(data=chunk,sample_rate=16000,num_channels=1,samples_per_channel=len(chunk)//2))
            await asyncio.sleep(.02)
        for _ in range(75):
            await source.queue.put(rtc.AudioFrame(data=bytes(640),sample_rate=16000,num_channels=1,samples_per_channel=320))
            await asyncio.sleep(.02)
    try:
        await session.start(agent=ConsultationAssistant(controller))
        await asyncio.wait_for(session.generate_reply(instructions='只说你好。').wait_for_playout(),20)
        await send('请告诉我一天有多少个小时。')
        for _ in range(100):
            if len([m for m in messages if m['role']=='assistant'])>=2:break
            await asyncio.sleep(.1)
        await send('今天就聊到这里吧，再见，请挂断电话。')
        try:await asyncio.wait_for(ended.wait(),25)
        except asyncio.TimeoutError:errors.append('ending_timeout')
    finally:
        await session.aclose()
        await model.aclose()
        await tts.aclose()
        logging.getLogger('livekit').removeHandler(error_capture)
    result={'phone_call':False,'actual_room_deleted':False,'audio_sink':'paced_discard_not_speaker',
            'messages':messages,'events':events,'errors':errors,'audio_frames':sink.frames,
            'controller_requested_room_deletion':ended.is_set()}
    result['ok']=ended.is_set() and not errors and any(e['type']=='farewell_played' for e in events)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['ok']:raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
