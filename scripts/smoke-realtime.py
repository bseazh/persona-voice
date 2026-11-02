"""Opt-in production roundtrip test; uses configured API credits and a new room.

Run with .venv-agent/bin/python scripts/smoke-realtime.py from the repository root.
Only synthesized fixture speech is published; no system microphone is opened.
"""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import time

import aiohttp
from dotenv import load_dotenv
from livekit import rtc

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
sys.path.insert(0, str(ROOT / 'services/agent'))
from qwen_tts import QwenTTS


async def fixture(text):
    engine = QwenTTS()
    async with engine.synthesize(text) as stream:
        pcm = b''.join([bytes(event.frame.data) async for event in stream])
    await engine.aclose()
    return subprocess.check_output(['ffmpeg', '-v', 'error', '-f', 's16le', '-ar', '24000',
        '-ac', '1', '-i', 'pipe:0', '-ar', '16000', '-f', 's16le', 'pipe:1'], input=pcm)


async def main():
    first = await fixture('请详细介绍北京的三个旅游景点。')
    second = await fixture('停一下，请只回答：测试成功。')
    async with aiohttp.ClientSession() as client:
        async with client.post('https://phone.hehaizhao.site/api/token',
            json={'accessCode': os.environ['VOICE_ACCESS_CODE']}) as response:
            response.raise_for_status()
            details = await response.json()
    room = rtc.Room()
    started = time.monotonic()
    state = {'phase': 0, 'partials': 0, 'finals': 0, 'reply_audio': 0,
             'interrupted': False, 'success': False, 'agent': ''}
    tasks = []
    queue = asyncio.Queue()

    def log(*args):
        print(round(time.monotonic() - started, 2), *args, flush=True)

    @room.on('transcription_received')
    def transcript(segments, participant, publication):
        for segment in segments:
            local = participant.identity == room.local_participant.identity
            if local:
                state['finals' if segment.final else 'partials'] += 1
            if segment.final:
                log('user' if local else 'agent', segment.text)
            if not local and state['phase'] == 2 and '测试成功' in segment.text:
                state['success'] = True

    @room.on('participant_attributes_changed')
    def attributes(changed, participant):
        if 'lk.agent.state' in changed:
            state['agent'] = changed['lk.agent.state']
            log('agent_state', state['agent'])
            if state['phase'] == 2 and state['agent'] in ('listening', 'thinking'):
                state['interrupted'] = True

    async def audio(track):
        async for event in rtc.AudioStream(track):
            if any(abs(value) > 100 for value in event.frame.data):
                if state['phase'] == 1 and state['finals'] >= 1:
                    state['reply_audio'] += 1
                if state['phase'] == 2:
                    state['second_audio'] = state.get('second_audio', 0) + 1

    @room.on('track_subscribed')
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(audio(track)))

    async def until(predicate, timeout=45):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.05)

    try:
        await room.connect(details['serverUrl'], details['participantToken'])
        source = rtc.AudioSource(16000, 1)
        track = rtc.LocalAudioTrack.create_audio_track('fixture-microphone', source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        await room.local_participant.publish_track(track, options)

        async def feed():
            while True:
                frame = queue.get_nowait() if not queue.empty() else bytes(640)
                await source.capture_frame(rtc.AudioFrame(frame, 16000, 1, 320))

        tasks.append(asyncio.create_task(feed()))
        await until(lambda: state['agent'] == 'listening')
        await asyncio.sleep(1)
        state['phase'] = 1
        for i in range(0, len(first), 640):
            queue.put_nowait(first[i:i + 640].ljust(640, b'\0'))
        await until(lambda: state['reply_audio'] >= 70 and state['agent'] == 'speaking')
        state['phase'] = 2
        log('interrupting_with_second_utterance')
        for i in range(0, len(second), 640):
            queue.put_nowait(second[i:i + 640].ljust(640, b'\0'))
        await until(lambda: state['success'] and state.get('second_audio', 0) > 70 and state['finals'] >= 2)
        assert state['partials'] > 0, 'No partial transcripts received'
        assert state['interrupted'], 'Agent did not leave speaking state after interruption'
        log('PASS', state)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await room.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
