import sys
from pathlib import Path
import unittest
import json
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/agent'))
from qwen_realtime import QwenSocket


class BridgeTests(unittest.TestCase):
    def test_invalid_turn_does_not_block_later_explicit_response(self):
        socket=QwenSocket(None,turn_mode='smart_turn_v2')
        socket.server_turn_pending=True
        event={'type':'input_audio_buffer.speech_stopped','reason':'turn_invalid'}
        self.assertEqual(socket.translate(event),[event])
        self.assertFalse(socket.server_turn_pending)

    def test_ambient_text_is_audit_only_not_user_or_end_command(self):
        events=[]
        socket=QwenSocket(None,lambda k,p:events.append((k,p)),turn_mode='smart_turn_v2')
        socket.on_transcript=lambda text:self.fail('Ambient text became a user turn')
        self.assertEqual(socket.translate({'type':'conversation.item.ambient_audio_transcription.delta',
            'delta':'嗯'}),[])
        self.assertEqual(events[0][0],'ambient_audio')

    def test_cancel_race_is_idempotent_but_other_provider_errors_are_not_hidden(self):
        socket=QwenSocket(None)
        expected={'type':'error','error':{'param':'response.cancel','message':'Conversation has no active response.'}}
        self.assertEqual(socket.translate(expected),[])
        unauthorized={'type':'error','error':{'param':'response.cancel','message':'Unauthorized'}}
        self.assertEqual(socket.translate(unauthorized),[unauthorized])

class ModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mode_override_preserves_manual_mode_and_partial_updates(self):
        ws=AsyncMock()
        socket=QwenSocket(ws,turn_mode='smart_turn_v2')
        for source in ({'audio':{'input':{'turn_detection':{'type':'server_vad','threshold':.5,'silence_duration_ms':500}}}},
                       {'instructions':'test'}, {'audio':{'input':{'turn_detection':None}}}):
            await socket.send_str(json.dumps({'type':'session.update','session':source}))
        sent=[json.loads(c.args[0])['session'] for c in ws.send_str.call_args_list]
        self.assertEqual(sent[0]['turn_detection'],{'type':'smart_turn_v2','threshold':.5})
        self.assertNotIn('turn_detection',sent[1])
        self.assertIsNone(sent[2]['turn_detection'])


if __name__=='__main__':unittest.main()
