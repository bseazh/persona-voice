import asyncio
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/agent'))
from consultation_voice import VoiceController


class EndingTests(unittest.IsolatedAsyncioTestCase):
    async def test_archive_waits_for_farewell_playback(self):
        played=asyncio.Event()
        events=[]
        session=SimpleNamespace(input=SimpleNamespace(set_audio_enabled=lambda enabled:events.append(('input',enabled))),
            say=lambda text,allow_interruptions:SimpleNamespace(wait_for_playout=played.wait),
            shutdown=lambda **kwargs:events.append(('shutdown',None)))
        journal=SimpleNamespace(emit=lambda kind,payload=None:events.append((kind,payload)),flush=AsyncMock())
        delete=AsyncMock()
        ctx=SimpleNamespace(room=SimpleNamespace(name='consult-test'),api=SimpleNamespace(room=SimpleNamespace(delete_room=delete)))
        controller=VoiceController(ctx,session,journal)
        task=asyncio.create_task(controller.finish('这是模型生成结束语的测试输入'))
        await asyncio.sleep(0)
        self.assertFalse(controller.closed)
        self.assertNotIn('closed',[kind for kind,_ in events])
        played.set()
        await task
        kinds=[kind for kind,_ in events]
        self.assertLess(kinds.index('farewell_played'),kinds.index('closed'))
        self.assertLess(kinds.index('closed'),kinds.index('shutdown'))
        delete.assert_awaited_once()
        await controller.close_room('duplicate')
        self.assertEqual(kinds.count('closed'),1)

    async def test_failed_playback_is_not_claimed_as_played(self):
        async def fail():raise RuntimeError('audio failure')
        events=[]
        session=SimpleNamespace(input=SimpleNamespace(set_audio_enabled=lambda _:None),
            say=lambda *a,**kw:SimpleNamespace(wait_for_playout=fail),shutdown=lambda **kw:None)
        journal=SimpleNamespace(emit=lambda kind,payload=None:events.append((kind,payload)),flush=AsyncMock())
        ctx=SimpleNamespace(room=SimpleNamespace(name='consult-test'),api=SimpleNamespace(room=SimpleNamespace(delete_room=AsyncMock())))
        await VoiceController(ctx,session,journal).finish('再见')
        self.assertNotIn('farewell_played',[kind for kind,_ in events])
        self.assertEqual([payload['reason'] for kind,payload in events if kind=='closed'],['farewell_playback_failed'])

if __name__=='__main__':unittest.main()
