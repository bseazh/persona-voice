import asyncio
import base64
import json
import sys
import unittest
from pathlib import Path

from aiohttp import web, ClientSession
from livekit.agents import APIConnectionError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/agent'))
import mimo_tts


class MiMoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.lines = []
        self.status = 200
        async def handler(request):
            self.request = await request.json()
            self.auth = request.headers.get('Authorization')
            return web.Response(status=self.status, body=b''.join(self.lines),
                                content_type='text/event-stream')
        app = web.Application()
        app.router.add_post('/', handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.old_url = mimo_tts.URL
        mimo_tts.URL = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])
        self.client = ClientSession()

    async def asyncTearDown(self):
        mimo_tts.URL = self.old_url
        await self.client.close()
        await self.runner.cleanup()

    def audio(self, data):
        return b'data: ' + json.dumps({'choices': [{'delta': {
            'audio': {'data': base64.b64encode(data).decode()}}}]}).encode() + b'\n\n'

    async def collect(self):
        return [c async for c in mimo_tts.pcm_chunks(self.client, 'test-key', '测试')]

    async def test_pcm_and_request(self):
        self.lines = [self.audio(b'\x01\x00' * 20), b'data: [DONE]\n\n']
        self.assertEqual(await self.collect(), [b'\x01\x00' * 20])
        self.assertEqual(self.request['messages'], [{'role': 'assistant', 'content': '测试'}])
        self.assertTrue(self.request['stream'])
        self.assertEqual(self.auth, 'Bearer test-key')

    async def test_truncated_stream_rejected(self):
        self.lines = [self.audio(b'\x01\x00')]
        with self.assertRaises(APIConnectionError): await self.collect()

    async def test_empty_stream_rejected(self):
        self.lines = [b'data: [DONE]\n\n']
        with self.assertRaises(APIConnectionError): await self.collect()

    async def test_http_failure_redacted(self):
        self.status = 401
        self.lines = [b'secret provider detail']
        with self.assertRaisesRegex(APIConnectionError, 'HTTP 401') as raised:
            await self.collect()
        self.assertNotIn('secret', str(raised.exception))

    async def test_close_early_returns_connection(self):
        self.lines = [self.audio(b'\x01\x00'), self.audio(b'\x02\x00'), b'data: [DONE]\n\n']
        stream = mimo_tts.pcm_chunks(self.client, 'test-key', '测试')
        self.assertEqual(await anext(stream), b'\x01\x00')
        await stream.aclose()
        self.assertFalse(self.client.connector._acquired)


if __name__ == '__main__': unittest.main()
