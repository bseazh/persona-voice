import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/agent'))
from realtime_voice import RealtimeController


class EndingTests(unittest.IsolatedAsyncioTestCase):
    def setup_controller(self,playout,delete=None):
        self.events=[]
        self.says=[]
        async def interrupt(**kw):pass
        def say(text,**kw):
            self.says.append(text)
            return SimpleNamespace(wait_for_playout=playout,interrupted=False,exception=lambda:None)
        session=SimpleNamespace(input=SimpleNamespace(set_audio_enabled=lambda _:None),
            interrupt=interrupt,say=say,shutdown=lambda **kw:None)
        model=SimpleNamespace(transport=SimpleNamespace(on_transcript=None),
            mute_responses=lambda:None,farewell=AsyncMock(return_value=('好的，再见。',[])))
        journal=SimpleNamespace(emit=lambda kind,payload=None:self.events.append(kind),
            request=AsyncMock(return_value={'phone':False}),flush=AsyncMock())
        self.delete=delete or AsyncMock()
        ctx=SimpleNamespace(room=SimpleNamespace(name='test'),api=SimpleNamespace(room=SimpleNamespace(delete_room=self.delete)))
        return RealtimeController(ctx,session,journal,model)

    async def test_duplicate_end_plays_once_and_release_waits_for_playout(self):
        played=asyncio.Event()
        c=self.setup_controller(played.wait)
        c.transcript('嗯好的好的那就这样拜。');c.transcript('再见');c.request_end('operator_end')
        await asyncio.sleep(.01)
        self.delete.assert_not_awaited()
        played.set();await c.end_task
        self.assertEqual(len(self.says),1)
        self.assertLess(self.events.index('farewell_played'),self.events.index('room_release'))
        self.delete.assert_awaited_once()

    async def test_playback_failure_still_requests_release_without_claiming_success(self):
        async def fail():raise RuntimeError('sink_failed')
        c=self.setup_controller(fail)
        c.request_end('operator_end');await c.end_task
        self.assertNotIn('farewell_played',self.events)
        self.assertIn('farewell_failed',self.events)
        self.delete.assert_awaited_once()

    async def test_negated_command_does_not_start_ending(self):
        c=self.setup_controller(AsyncMock())
        c.transcript('不要挂断电话。')
        self.assertFalse(c.finishing)
        self.assertIsNone(c.end_task)

    async def test_phone_deadline_never_extended_and_web_not_limited(self):
        c=self.setup_controller(AsyncMock())
        self.assertFalse(c.phone_wrapup_due())
        with patch('realtime_voice.time.monotonic',return_value=100):
            c.update_phone_deadline(180)
            self.assertFalse(c.phone_wrapup_due())
        with patch('realtime_voice.time.monotonic',return_value=241):
            c.update_phone_deadline(180)
            self.assertEqual(c.phone_deadline,280)
            self.assertTrue(c.phone_wrapup_due())
        c.update_phone_deadline(None)
        c.update_phone_deadline(-1)
        self.assertEqual(c.phone_deadline,280)

    async def test_timed_end_drains_then_farewell_before_release(self):
        played=asyncio.Event()
        c=self.setup_controller(AsyncMock())
        c.session.current_speech=SimpleNamespace(wait_for_playout=played.wait)
        c.request_end('phone_duration_limit')
        await asyncio.sleep(.01)
        c.model.farewell.assert_not_awaited()
        self.delete.assert_not_awaited()
        played.set()
        await c.end_task
        c.model.farewell.assert_awaited_once_with(reason='duration_limit')
        self.assertLess(self.events.index('farewell_played'),self.events.index('room_release'))


if __name__=='__main__':unittest.main()
