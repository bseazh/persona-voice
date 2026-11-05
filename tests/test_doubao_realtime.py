"""Protocol regressions; local fake provider is not a real-service acceptance test."""
import asyncio
import base64
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from livekit import rtc
from livekit.agents import Agent, AgentSession
from livekit.agents.voice import io

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/agent'))
import doubao_realtime as d


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.model=d.DoubaoRealtime(key='test-only')
        self.session=self.model.session()
        self.events=[]
        self.session.on('generation_created',lambda e:self.events.append(e))

    async def asyncTearDown(self): await self.model.aclose()

    async def test_output_requests_pcm16_not_float32(self):
        self.assertEqual(d.config('x')['audio']['output']['format']['type'],'pcm_s16le')
        self.assertEqual(d.config('x')['audio']['input']['format']['rate'],16000)

    async def test_stale_audio_and_cancel_ack_cannot_reopen_or_close_new_response(self):
        self.session.handle({'type':'response.output_text.delta','response_id':'old','delta':'旧回复'})
        self.session.handle({'type':'response.output_text.delta','response_id':'new','delta':'新回复'})
        self.session.handle({'type':'response.output_audio.delta','response_id':'old','delta':base64.b64encode(b'\x01\x00'*320).decode()})
        self.session.handle({'type':'response.canceled'})
        self.assertEqual(self.session.generation['id'],'new')
        self.assertEqual(len(self.events),2)

    async def test_final_transcript_gates_output_before_next_delta(self):
        seen=[]
        self.model.transport.on_transcript=lambda text:(seen.append(text),self.model.mute_responses())
        self.session.handle({'type':'conversation.item.input_audio_transcription.completed','item_id':'user','transcript':'好的再见'})
        self.session.handle({'type':'response.output_text.delta','response_id':'late','delta':'重复告别'})
        self.assertEqual(seen,['好的再见']);self.assertEqual(self.events,[])

    async def test_completed_response_drops_duplicate_audio(self):
        self.session.handle({'type':'response.output_text.delta','response_id':'a','delta':'你好'})
        self.session.handle({'type':'response.output_audio.done','response_id':'a'})
        self.session.handle({'type':'response.output_text.delta','response_id':'a','delta':'重复'})
        self.assertEqual(len(self.events),1);self.assertIsNone(self.session.generation)

    async def test_audio_pacing_and_mute_after_gap(self):
        sent=[]
        async def send(kind,**fields):sent.append((kind,time.monotonic(),fields))
        self.session.conn.send=send
        task=asyncio.create_task(self.session.pump())
        try:
            for _ in range(3):self.session.audio.put_nowait(b'\0'*640)
            await asyncio.sleep(.23)
        finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
        audio=[e for e in sent if e[0]=='input_audio_buffer.append']
        self.assertEqual(len(audio),3)
        self.assertTrue(all(b[1]-a[1]>=.018 for a,b in zip(audio,audio[1:])))
        self.assertEqual(sent[0][0],'input_audio_unmute.commit')
        self.assertEqual(sent[-1][0],'input_audio_mute.commit')

    async def test_audio_queue_is_bounded(self):
        self.session.resampler=type('Passthrough',(),{'push':lambda _,frame:[frame]})()
        self.session.on('error',lambda e:None)
        self.session.push_audio(rtc.AudioFrame(b'\0'*640*102,16000,1,320*102))
        self.assertIsNotNone(self.session.failed)
        self.assertLessEqual(self.session.audio.qsize(),100)


class Sink(io.AudioOutput):
    def __init__(self):
        super().__init__(label='test',capabilities=io.AudioOutputCapabilities(pause=False))
        self.frames=0
    async def capture_frame(self,frame):
        await super().capture_frame(frame)
        self.frames+=1
    def flush(self):
        super().flush()
        if self._pending_playback_count:self.on_playback_finished(playback_position=.04,interrupted=False)
    def clear_buffer(self):
        super().flush()
        if self._pending_playback_count:self.on_playback_finished(playback_position=0,interrupted=True)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_livekit_opening_audio_transcript_and_graceful_close(self):
        events=[]
        async def handler(request):
            self.assertEqual(request.headers.get('X-Api-Key'),'test-only')
            ws=web.WebSocketResponse();await ws.prepare(request)
            answered=False
            async for msg in ws:
                e=msg.json();events.append(e['type'])
                if e['type']=='session.create':
                    self.assertEqual(e['session']['audio']['output']['format']['type'],'pcm_s16le')
                    await ws.send_json({'type':'session.created','session':{'id':'test'}})
                elif e['type']=='speech_text_buffer.commit':
                    await ws.send_json({'type':'response.output_audio.delta','response_id':'r1','delta':base64.b64encode(b'\x01\x00'*960).decode()})
                    await ws.send_json({'type':'response.output_audio.done','response_id':'r1'})
                elif e['type']=='input_audio_buffer.append' and not answered:
                    answered=True
                    await ws.send_json({'type':'conversation.item.input_audio_transcription.started','item_id':'u1'})
                    await ws.send_json({'type':'conversation.item.input_audio_transcription.completed','item_id':'u1','transcript':'二加二是多少'})
                    await ws.send_json({'type':'response.output_text.delta','response_id':'r2','delta':'四。'})
                    await ws.send_json({'type':'response.output_text.done','response_id':'r2','text':'四。'})
                    await ws.send_json({'type':'response.output_audio.delta','response_id':'r2','delta':base64.b64encode(b'\x01\x00'*960).decode()})
                    await ws.send_json({'type':'response.output_audio.done','response_id':'r2'})
                elif e['type']=='session.close':
                    await ws.send_json({'type':'session.closed'});break
            return ws
        app=web.Application();app.router.add_get('/',handler)
        runner=web.AppRunner(app);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        model=d.DoubaoRealtime(key='test-only');session=AgentSession(llm=model);sink=Sink()
        session.output.audio=sink
        messages=[]
        session.on('conversation_item_added',lambda e:messages.append(getattr(e.item,'text_content',None)))
        try:
            with patch.object(d,'URL',f'http://127.0.0.1:{port}/'):
                await session.start(agent=Agent(instructions='测试'))
                await asyncio.wait_for(session.generate_reply().wait_for_playout(),5)
                self.assertGreater(sink.frames,0)
                self.assertIn(d.GREETING,messages)
                model.sessions[0].push_audio(rtc.AudioFrame(b'\x01\x00'*640,16000,1,640))
                async with asyncio.timeout(3):
                    while '四。' not in messages: await asyncio.sleep(.01)
                self.assertIn('二加二是多少',messages)
                await session.aclose()
                await model.aclose()
                self.assertTrue(model.sessions[0].conn.close_confirmed)
                self.assertIn('session.close',events)
        finally:
            await session.aclose();await model.aclose();await runner.cleanup()


if __name__=='__main__':unittest.main()
