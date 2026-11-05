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
import time
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
from realtime_voice import RealtimeAssistant, RealtimeController

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
        self.first_audio=asyncio.Event()
        self.last_frame_at=None
        self.frame_times=[]

    async def capture_frame(self,frame):
        await super().capture_frame(frame)
        self.last_frame_at=time.monotonic()
        self.frame_times.append(self.last_frame_at)
        self.first_audio.set()
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
    session=AgentSession(llm=model)
    source,sink=Input(),Sink()
    session.input.audio=source
    session.output.audio=sink
    messages=[]
    errors=[]
    handles=[]
    measurements={}
    @session.on('speech_created')
    def speech(e):handles.append(e.speech_handle)
    class ErrorCapture(logging.Handler):
        def emit(self,record):
            if record.levelno>=logging.ERROR:
                errors.append('sdk_log:'+record.name+':'+(record.exc_info[0].__name__ if record.exc_info else record.getMessage().replace(model.key,'[REDACTED]')[:300]))
    error_capture=ErrorCapture(level=logging.ERROR)
    logging.getLogger('livekit').addHandler(error_capture)
    ended=asyncio.Event()
    @session.on('conversation_item_added')
    def message(e):
        if getattr(e.item,'role',None) in ('user','assistant'):
            messages.append({'role':e.item.role,'text':e.item.text_content})
    @session.on('error')
    def error(e):errors.append(type(e.error).__name__+':'+str(e.error).replace(model.key,'[REDACTED]')[:400])
    async def flush():pass
    async def delete_room(request):
        measurements['release_requested_at']=time.monotonic()
        ended.set()
    async def request(action):return {'phone':False,'confirmed':False,'reason':'test_no_real_phone'}
    def emit(kind,payload=None):
        events.append({'type':kind,'data':payload})
        if kind=='ending':measurements['ending_at']=time.monotonic()
    journal=SimpleNamespace(emit=emit,flush=flush,request=request)
    ctx=SimpleNamespace(room=SimpleNamespace(name='probe-no-real-room'),
                        api=SimpleNamespace(room=SimpleNamespace(delete_room=delete_room)))
    controller=RealtimeController(ctx,session,journal,model)
    async def send(text,pcm=None):
        if pcm is None:pcm=await fixture_probe.fixture(text)
        for offset in range(0,len(pcm),640):
            chunk=pcm[offset:offset+640]
            await source.queue.put(rtc.AudioFrame(data=chunk,sample_rate=16000,num_channels=1,samples_per_channel=len(chunk)//2))
            await asyncio.sleep(.02)
        input_end=time.monotonic()
        for _ in range(75):
            await source.queue.put(rtc.AudioFrame(data=bytes(640),sample_rate=16000,num_channels=1,samples_per_channel=320))
            await asyncio.sleep(.02)
        return input_end
    try:
        await session.start(agent=RealtimeAssistant())
        await asyncio.wait_for(session.generate_reply(instructions='请介绍你是AI小禾，会保存文字转录和摘要，简短询问是否方便开始。开场只说这一次。').wait_for_playout(),20)
        frame_start=len(sink.frame_times)
        input_end=await send('请告诉我一天有多少个小时。')
        for _ in range(100):
            if len([m for m in messages if m['role']=='assistant'])>=2:break
            await asyncio.sleep(.1)
        if len(sink.frame_times)>frame_start:
            measurements['question_input_end_to_first_sink_audio_seconds']=round(sink.frame_times[frame_start]-input_end,3)
        interruption=await fixture_probe.fixture('等一下，请只告诉我二加二等于几。')
        sink.first_audio.clear()
        await send('请从一数到二十，每个数字之间停顿一下。')
        await asyncio.wait_for(sink.first_audio.wait(),15)
        measurements['input_overlapped_active_playback']=sink._pending_playback_count>0
        interruption_message_index=len(messages)
        await send('',interruption)
        for _ in range(150):
            if any(m['role']=='assistant' and ('4' in m['text'] or '四' in m['text'])
                   for m in messages[interruption_message_index:]):break
            await asyncio.sleep(.1)
        measurements['interrupted_before_ending']=sum(h.interrupted for h in handles)
        await send('今天就聊到这里吧，再见，请挂断电话。')
        try:await asyncio.wait_for(ended.wait(),25)
        except asyncio.TimeoutError:errors.append('ending_timeout')
    finally:
        await session.aclose()
        await model.aclose()
        logging.getLogger('livekit').removeHandler(error_capture)
    result={'phone_call':False,'actual_room_deleted':False,'audio_sink':'paced_discard_not_speaker',
            'messages':messages,'events':events,'errors':errors,'audio_frames':sink.frames,
            'controller_requested_room_deletion':ended.is_set()}
    result['interrupted_speeches']=sum(h.interrupted for h in handles)
    if 'release_requested_at' in measurements and 'ending_at' in measurements:
        measurements['ending_to_room_release_seconds']=round(measurements.pop('release_requested_at')-measurements.pop('ending_at'),3)
    result['measurements']=measurements
    result['answer_correct']=any(m['role']=='assistant' and ('24' in m['text'] or '二十四' in m['text']) for m in messages)
    result['interrupt_answer_correct']=any(m['role']=='assistant' and ('4' in m['text'] or '四' in m['text']) for m in messages[interruption_message_index:])
    result['ok']=ended.is_set() and not errors and result['answer_correct'] and result['interrupt_answer_correct'] and measurements.get('input_overlapped_active_playback') and measurements.get('interrupted_before_ending',0)>0 and sum(e['type']=='farewell_played' for e in events)==1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['ok']:raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
