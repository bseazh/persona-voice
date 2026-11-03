import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('phone_transcript', Path(__file__).resolve().parents[1] / 'services/agent/phone_transcript.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Session:
    def __init__(self):
        self.handlers = {}
    def on(self, name):
        def register(callback):
            self.handlers[name] = callback
            return callback
        return register

class TranscriptTests(unittest.TestCase):
    def test_phone_only_and_dedup_and_close(self):
        # Use a test directory under the ignored project artifact directory.
        base = Path(__file__).resolve().parents[1] / 'BigApple输出'
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder, patch.object(module, 'DIRECTORY', Path(folder)):
            web = Session()
            module.attach_phone_transcript(web, 'persona-browser')
            self.assertFalse(web.handlers)
            session = Session()
            module.attach_phone_transcript(session, 'sim-ai-test')
            item = SimpleNamespace(id='1', role='user', text_content='<script>test</script>', interrupted=False)
            for _ in range(2):
                session.handlers['conversation_item_added'](SimpleNamespace(item=item))
            path = Path(folder) / 'sim-ai-test.json'
            state = json.loads(path.read_text())
            self.assertEqual(len(state['messages']), 1)
            self.assertEqual(state['messages'][0]['role'], 'user')
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            session.handlers['close'](None)
            self.assertFalse(json.loads(path.read_text())['active'])

if __name__ == '__main__':
    unittest.main()
