import asyncio
from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/agent'))
from qwen_tts import QwenTTS


class FakeSession:
    def __init__(self):
        self.audio = queue.Queue()
        self.text = []
        self.closed = False
    def start(self): return self
    def send_text(self, text): self.text.append(text)
    def flush(self): self.audio.put(b'\x01\x01' * 2400)
    def stop(self):
        self.flush()
        self.audio.put(None)
    def audio_chunks(self):
        while True:
            item = self.audio.get(timeout=3)
            if item is None: return
            yield item
    def close(self):
        self.closed = True
        self.audio.put(None)


class FakeClient:
    def __init__(self, **kwargs):
        self.audio = self
        self.tts = self
        self.sessions = []
        self.closed = False
    def connect(self, **kwargs):
        s = FakeSession(); self.sessions.append(s); return s
    def close(self): self.closed = True


class DuplexTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_before_end_input_without_reconnecting_per_sentence(self):
        client = FakeClient()
        with patch('qwen_tts.dashscope.Client', return_value=client), patch.dict('os.environ', {'QWEN_TTS_MODE':'duplex-v1'}):
            engine = QwenTTS(key='test')
            stream = engine.stream()
            frames = []; first = asyncio.Event()
            async def consume():
                async for event in stream:
                    frames.append(event); first.set()
            task = asyncio.create_task(consume())
            stream.push_text('这是第一段测试文字，')
            await asyncio.wait_for(first.wait(), 2)
            self.assertFalse(task.done(), 'audio must arrive before end_input')
            stream.push_text('这是继续生成的回答。')
            stream.end_input()
            await asyncio.wait_for(task, 3)
            await stream.aclose()
            self.assertEqual(len(client.sessions), 1)
            self.assertEqual(''.join(client.sessions[0].text), '这是第一段测试文字，这是继续生成的回答。')
            self.assertEqual(len({f.segment_id for f in frames}), 1)
            self.assertTrue(all(s.closed for s in client.sessions))
            self.assertTrue(client.closed)
            await engine.aclose()

    async def test_interruption_closes_pending_reader(self):
        client = FakeClient()
        with patch('qwen_tts.dashscope.Client', return_value=client), patch.dict('os.environ', {'QWEN_TTS_MODE':'duplex-v1'}):
            engine = QwenTTS(key='test'); stream = engine.stream()
            stream.push_text('尚未结束')
            for _ in range(100):
                if client.sessions and client.sessions[0].text: break
                await asyncio.sleep(.005)
            self.assertTrue(client.sessions[0].text)
            await asyncio.wait_for(stream.aclose(), 2)
            self.assertTrue(client.sessions[0].closed)
            self.assertTrue(client.closed)
            await engine.aclose()

if __name__ == '__main__': unittest.main()
