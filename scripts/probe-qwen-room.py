"""Public workspace -> actual LiveKit room -> Qwen -> persisted transcript.

No phone/SIP participant. Consumes API credits; creates a labelled test session.
Credentials are loaded on the server, never printed or put in process arguments.
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import time

import aiohttp
from dotenv import load_dotenv
from livekit import rtc

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
spec=importlib.util.spec_from_file_location('fixture',ROOT/'scripts/probe-qwen-realtime.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--ending',choices=['natural','operator'],default='natural')
    parser.add_argument('--route',choices=['qwen-realtime','doubao-realtime','pipeline-mimo','pipeline-mimo-all'],default='qwen-realtime')
    parser.add_argument('--followup',action='store_true',help='Add a second real audio question before ending')
    args=parser.parse_args()
    origin='https://phone.hehaizhao.site'
    question=await fixture.fixture('请告诉我一天有多少个小时。')
    goodbye=await fixture.fixture('今天就聊到这里吧，再见，请挂断电话。')
    followup=await fixture.fixture('请告诉我二加二等于几，只回答数字。') if args.followup else None
    room=rtc.Room()
    tasks=[]
    state={'agent':'','audio_frames':0,'disconnected':False}
    report={'phone_call':False,'endpoint':'real_livekit_client_not_handset','ending':args.ending}
    queue=asyncio.Queue()
    @room.on('participant_attributes_changed')
    def attributes(changed,participant):
        if 'lk.agent.state' in changed:state['agent']=changed['lk.agent.state']
    @room.on('disconnected')
    def disconnected(reason):state['disconnected']=True
    async def receive(track):
        async for event in rtc.AudioStream(track):
            if any(abs(value)>100 for value in event.frame.data):state['audio_frames']+=1
    @room.on('track_subscribed')
    def subscribed(track,publication,participant):
        if track.kind==rtc.TrackKind.KIND_AUDIO:tasks.append(asyncio.create_task(receive(track)))
    async def until(predicate,timeout=45):
        async with asyncio.timeout(timeout):
            while not predicate():await asyncio.sleep(.1)
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(),timeout=aiohttp.ClientTimeout(total=30)) as client:
        async def request(path,body=None):
            async with client.request('GET' if body is None else 'POST',origin+'/api/consult/'+path,
                json=body,headers={'Origin':origin,'X-Consultation':'1'}) as response:
                if response.status>=400:raise RuntimeError(f'workspace_{path.split("?")[0]}_{response.status}')
                return await response.json()
        await request('login',{'password':os.environ['CONSULTATION_ADMIN_PASSWORD']})
        session=await request('create',{'title':'[自动验收] '+args.route+' '+args.ending,
            'mode':'voice','voiceRoute':args.route,'consent':True})
        sid=session['id'];report['session_id']=sid
        try:
            details=await request('voice-token',{'id':sid})
            await room.connect(details['serverUrl'],details['participantToken'])
            source=rtc.AudioSource(16000,1,queue_size_ms=100)
            track=rtc.LocalAudioTrack.create_audio_track('generic-fixture',source)
            options=rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            await room.local_participant.publish_track(track,options)
            async def feed():
                while True:
                    pcm=queue.get_nowait() if not queue.empty() else bytes(640)
                    await source.capture_frame(rtc.AudioFrame(pcm,16000,1,320))
            tasks.append(asyncio.create_task(feed()))
            async def send(pcm):
                for offset in range(0,len(pcm),640):queue.put_nowait(pcm[offset:offset+640].ljust(640,b'\0'))
                await until(lambda:queue.empty())
                # The feeder continuously supplies silence, so waiting for an
                # entirely empty source would never finish. Its queue is 100ms.
                await asyncio.sleep(.15)
            await until(lambda:state['audio_frames']>0 and state['agent']=='listening')
            await send(question)
            for _ in range(60):
                current=await request('session?id='+sid)
                if any(m['role']=='assistant' and ('24' in m['text'] or '二十四' in m['text']) for m in current['messages']):break
                await asyncio.sleep(.5)
            else:raise RuntimeError('answer_not_persisted')
            if followup is not None:
                await until(lambda:state['agent']=='listening')
                count=len(current['messages'])
                await send(followup)
                for _ in range(60):
                    current=await request('session?id='+sid)
                    if any(m['role']=='assistant' and m['text'].strip('。！.! ') in ('4','四') for m in current['messages'][count:]):break
                    await asyncio.sleep(.5)
                else:raise RuntimeError('followup_answer_not_persisted')
                report['followup_answer_confirmed']=True
            end_start=time.monotonic()
            if args.ending=='natural':await send(goodbye)
            else:await request('voice-end',{'id':sid})
            await until(lambda:state['disconnected'],45)
            report['end_request_to_client_disconnect_seconds']=round(time.monotonic()-end_start,3)
            for _ in range(30):
                current=await request('session?id='+sid)
                if current['status']=='closed':break
                await asyncio.sleep(.5)
            events=await request('events?id='+sid)
            report.update({'voice_route':current['voice_route'],'status':current['status'],
                'messages':[{'role':m['role'],'text':m['text']} for m in current['messages']],
                'audio_frames':state['audio_frames'],'client_disconnected':state['disconnected'],
                'farewell_count':sum(e['kind']=='voice.farewell_played' for e in events),
                'error_kinds':[e['kind'] for e in events if e['kind'] in ('voice.error','voice.farewell_failed')],
                'room_release':[e['payload'] for e in events if e['kind']=='voice.room_release']})
            released = any(e.get('confirmed') for e in report['room_release']) if args.route in ('qwen-realtime','doubao-realtime') else state['disconnected']
            report['benchmark_config']=[e['payload'] for e in events if e['kind']=='voice.benchmark_config']
            report['ok']=current['status']=='closed' and current['voice_route']==args.route and report['farewell_count']==1 and not report['error_kinds'] and released
        except Exception as error:
            report.update(ok=False,error_type=type(error).__name__,error=str(error)[:200])
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            await room.disconnect()
            if not report.get('ok'):
                try:await request('voice-abort',{'id':sid})
                except Exception:pass
            await request('logout',{})
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['ok']:raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
