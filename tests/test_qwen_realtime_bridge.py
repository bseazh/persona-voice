import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/agent'))
from qwen_realtime import QwenSocket


class BridgeTests(unittest.TestCase):
    def test_cancel_race_is_idempotent_but_other_provider_errors_are_not_hidden(self):
        socket=QwenSocket(None)
        expected={'type':'error','error':{'param':'response.cancel','message':'Conversation has no active response.'}}
        self.assertEqual(socket.translate(expected),[])
        unauthorized={'type':'error','error':{'param':'response.cancel','message':'Unauthorized'}}
        self.assertEqual(socket.translate(unauthorized),[unauthorized])


if __name__=='__main__':unittest.main()
