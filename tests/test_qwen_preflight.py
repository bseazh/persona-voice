"""Adapter contract tests with SDK events; no provider or phone calls."""
import asyncio
from pathlib import Path
import queue
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/agent'))
from livekit import rtc
from livekit.agents import stt
from qwen_streaming_stt import QwenStreamingSTT


class Provider:
    request_id = 'test-request'
    def __init__(self):
        self.items = queue.Queue()
        self.started = False
    def start(self): self.started = True
    def send_audio_frame(self, data): pass
    def results(self):
        while True:
            item = self.items.get(timeout=3)
            if item is None: return
            yield item
    def stop(self): self.items.put(None)
    def close(self): self.stop()
    def text(self, text, final=False):
        self.items.put(SimpleNamespace(get_sentence=lambda: {'text':text},
                                       is_sentence_end=lambda:final))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def run_stream(self, enabled):
        provider = Provider()
        client = SimpleNamespace(audio=SimpleNamespace(asr=SimpleNamespace(
            recognize=lambda **kwargs:provider)), close=lambda:None)
        events, audits = [], []
        with patch('qwen_streaming_stt.dashscope.Client',return_value=client), patch.dict(
                'os.environ', {'VOICE_PREFLIGHT':'on' if enabled else 'off'}):
            engine = QwenStreamingSTT(key='test',audit=lambda k,p:audits.append((k,p)))
            engine.set_user_speaking(True)
            stream = engine.stream()
            async def consume():
                async for event in stream: events.append(event)
            task = asyncio.create_task(consume())
            try:
                stream.push_frame(rtc.AudioFrame(data=b'\0\0'*160, sample_rate=16000,
                                                 num_channels=1,samples_per_channel=160))
                for _ in range(100):
                    if provider.started: break
                    await asyncio.sleep(.005)
                self.assertTrue(provider.started)
                provider.text('这是仍在说话的完整测试句子')
                await asyncio.sleep(.2)
                self.assertFalse(any(e.type==stt.SpeechEventType.PREFLIGHT_TRANSCRIPT for e in events))
                self.assertFalse(any(e.type==stt.SpeechEventType.FINAL_TRANSCRIPT for e in events))
                engine.set_user_speaking(False)
                await asyncio.sleep(.05)
                hints=[e for e in events if e.type==stt.SpeechEventType.PREFLIGHT_TRANSCRIPT]
                self.assertEqual(len(hints),1 if enabled else 0)
                provider.text('这是供应商确认的正式最终文字。',final=True)
                await asyncio.sleep(.05)
                stream.end_input()
                await asyncio.wait_for(task,3)
                finals=[e for e in events if e.type==stt.SpeechEventType.FINAL_TRANSCRIPT]
                self.assertEqual([e.alternatives[0].text for e in finals],['这是供应商确认的正式最终文字。'])
                self.assertEqual(sum(k=='asr_final' for k,p in audits),1)
                self.assertFalse(engine._preflights)
            finally:
                await stream.aclose()
                await engine.aclose()
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)

    async def test_vad_gated_hint_and_unchanged_provider_final(self):
        await self.run_stream(True)

    async def test_rollback_keeps_final_without_hints(self):
        await self.run_stream(False)


if __name__ == '__main__': unittest.main()
