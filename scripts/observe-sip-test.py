"""Observe a new SIP test room for 45s; never dial or record raw audio."""
import asyncio
import array
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from livekit import api, rtc

load_dotenv(Path(__file__).resolve().parents[1] / '.env')

async def main():
    room = rtc.Room()
    counts = {}
    tasks = []

    async def audio(track, identity):
        counts[identity] = {'frames': 0, 'peak': 0}
        stream = rtc.AudioStream(track)
        try:
            async for event in stream:
                stats = counts[identity]
                stats['frames'] += 1
                samples = array.array('h', event.frame.data.tobytes())
                stats['peak'] = max(stats['peak'], max(map(abs, samples), default=0))
        finally:
            await stream.aclose()

    @room.on('track_subscribed')
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(audio(track, participant.identity)))

    @room.on('transcription_received')
    def transcription(segments, participant, publication):
        for segment in segments:
            if segment.final:
                print(json.dumps({'speaker': participant.identity if participant else None, 'text': segment.text}, ensure_ascii=False), flush=True)

    async with api.LiveKitAPI() as client:
        for _ in range(60):
            rooms = await client.room.list_rooms(api.ListRoomsRequest())
            matches = [r for r in rooms.rooms if r.name.startswith('sim-ai-') and r.num_participants > 0]
            if matches:
                name = max(matches, key=lambda r: r.creation_time).name
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError('No active SIP test room')
        token = api.AccessToken().with_identity('sip-test-observer').with_grants(api.VideoGrants(room_join=True, room=name, can_publish=False)).to_jwt()
        await room.connect(os.environ['LIVEKIT_URL'], token)
        print('Observing ' + name, flush=True)
        try:
            await asyncio.sleep(45)
        finally:
            await room.disconnect()
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    raise result
        print(json.dumps({'audio': counts}), flush=True)

if __name__ == '__main__':
    asyncio.run(main())
