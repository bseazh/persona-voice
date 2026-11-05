import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

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
        c.transcript('请挂断电话。');c.transcript('再见');c.request_end('operator_end')
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


if __name__=='__main__':unittest.main()
