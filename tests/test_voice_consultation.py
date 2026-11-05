import asyncio
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/agent'))
from consultation_voice import VoiceController, completed_farewell, ConsultationAssistant


class EndingTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_turn_farewell_not_played_twice(self):
        text='好的，那今天就到这里，谢谢你和我聊这些。'
        farewell='好的，那今天就到这里，谢谢你和我聊这些，再见。'
        speech=SimpleNamespace(interrupted=False, chat_items=[
            SimpleNamespace(role='assistant',text_content=text,interrupted=False)])
        events=[]
        played=asyncio.Event()
        session=SimpleNamespace(input=SimpleNamespace(set_audio_enabled=lambda _:None),
            say=lambda *a,**kw:self.fail('must not synthesize duplicate farewell'), shutdown=lambda **kw:None)
        journal=SimpleNamespace(emit=lambda kind,payload=None:events.append(kind),flush=AsyncMock())
        ctx=SimpleNamespace(room=SimpleNamespace(name='consult-test'),api=SimpleNamespace(room=SimpleNamespace(delete_room=AsyncMock())))
        controller=VoiceController(ctx,session,journal)
        assistant=ConsultationAssistant(controller)
        context=SimpleNamespace(disallow_interruptions=lambda:None,wait_for_playout=played.wait,speech_handle=speech)
        task=asyncio.create_task(assistant.finish_consultation(context,farewell))
        await asyncio.sleep(0)
        self.assertFalse(controller.closed)
        played.set()
        await task
        self.assertIn('farewell_reused',events)
        self.assertLess(events.index('farewell_played'),events.index('closed'))
        await controller.finish(farewell)
        self.assertEqual(events.count('closed'),1)

    def test_unrelated_or_interrupted_speech_is_not_reused(self):
        for text,interrupted in [('好的',False),('这是完全不相关的普通回答',False),('谢谢你今天和我聊天',True)]:
            speech=SimpleNamespace(interrupted=False,chat_items=[SimpleNamespace(
                role='assistant',text_content=text,interrupted=interrupted)])
            self.assertIsNone(completed_farewell(speech,'谢谢你今天和我聊天，再见。'))

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
