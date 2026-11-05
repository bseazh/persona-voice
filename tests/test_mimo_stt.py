import base64
import io
import os
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from aiohttp import web
from livekit import rtc
from livekit.agents import APIConnectionError, DEFAULT_API_CONNECT_OPTIONS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/agent'))
import mimo_stt


class ASRTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.result = {'id': 'test-id', 'choices': [{'finish_reason': 'stop',
            'message': {'content': '测试'}}], 'usage': {'prompt_tokens': 4}}
        async def handler(request):
            self.body = await request.json()
            return web.json_response(self.result)
        app = web.Application(); app.router.add_post('/', handler)
        self.runner = web.AppRunner(app); await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0); await site.start()
        self.original = mimo_stt.URL
        mimo_stt.URL = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])
        self.events = []
        with patch.dict(os.environ, {'MIMO_API_KEY': 'test-key'}):
            self.engine = mimo_stt.MiMoSTT(audit=lambda k,v:self.events.append((k,v)))

    async def asyncTearDown(self):
        await self.engine.aclose(); await self.runner.cleanup(); mimo_stt.URL=self.original

    async def recognize(self):
        return await self.engine._recognize_impl(rtc.AudioFrame(bytes(32000),16000,1,16000),
            language='zh',conn_options=DEFAULT_API_CONNECT_OPTIONS)

    async def test_wav_and_usage_not_double_counted(self):
        r = await self.recognize()
        self.assertEqual(r.alternatives[0].text, '测试')
        data=self.body['messages'][0]['content'][0]['input_audio']['data'].split(',')[1]
        with wave.open(io.BytesIO(base64.b64decode(data))) as f:
            self.assertEqual(f.getframerate(),16000);self.assertEqual(f.getnframes(),16000)
        submitted=[v for k,v in self.events if v.get('phase')=='submitted']
        self.assertEqual(sum(v['input_audio_seconds'] for v in submitted),1)
        self.assertFalse(self.engine.capabilities.streaming)

    async def test_truncated_recognition_rejected(self):
        self.result['choices'][0]['finish_reason']='length'
        with self.assertRaises(APIConnectionError):await self.recognize()

    async def test_empty_transcript_is_not_fabricated(self):
        self.result['choices'][0]['message']['content']=''
        self.assertEqual((await self.recognize()).alternatives,[])


if __name__=='__main__':unittest.main()
