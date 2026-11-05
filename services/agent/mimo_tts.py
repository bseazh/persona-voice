"""MiMo sentence input / SSE PCM output. LiveKit supplies sentence adaptation."""
import base64
import json
import os
import uuid

import aiohttp
from livekit.agents import APIConnectionError, DEFAULT_API_CONNECT_OPTIONS, tts

MODEL = 'mimo-v2.5-tts'
VOICE = 'mimo_default'
URL = 'https://api.xiaomimimo.com/v1/chat/completions'


async def pcm_chunks(client, key, text, usage=None):
    """Closing this generator closes the response, including on interruption."""
    body = {'model': MODEL, 'messages': [{'role': 'assistant', 'content': text}],
            'audio': {'format': 'pcm16', 'voice': VOICE}, 'stream': True}
    async with client.post(URL, json=body,
                           headers={'Authorization': 'Bearer ' + key}) as response:
        if response.status != 200:
            raise APIConnectionError(f'MiMo TTS HTTP {response.status}')
        count = 0
        finished = False
        async for line in response.content:
            if not line.startswith(b'data:'):
                continue
            raw = line[5:].strip()
            if raw == b'[DONE]':
                finished = True
                break
            event = json.loads(raw)
            if usage is not None and event.get('usage'):
                usage.update({k:v for k,v in event['usage'].items() if isinstance(v,(int,float))})
            if event.get('error'):
                raise APIConnectionError('MiMo TTS provider error')
            for choice in event.get('choices', []):
                reason = choice.get('finish_reason')
                if reason not in (None, 'stop'):
                    raise APIConnectionError('MiMo TTS incomplete output')
                if reason == 'stop':
                    finished = True
                data = (choice.get('delta', {}).get('audio') or {}).get('data')
                if data:
                    chunk = base64.b64decode(data, validate=True)
                    if len(chunk) % 2:
                        raise APIConnectionError('MiMo TTS invalid PCM alignment')
                    count += len(chunk)
                    yield chunk
        if not count or not finished:
            raise APIConnectionError('MiMo TTS empty or truncated stream')


class MiMoTTS(tts.TTS):
    def __init__(self, *, audit=None):
        # Input is NOT duplex. LiveKit StreamAdapter handles sentence boundaries.
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False),
                         sample_rate=24000, num_channels=1)
        self.key = os.environ['MIMO_API_KEY']
        self._http = None
        self.audit = audit

    @property
    def model(self):
        return MODEL

    @property
    def provider(self):
        return 'Xiaomi/MiMo'

    def client(self):
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(
                total=45, connect=10, sock_read=15), read_bufsize=1024 * 1024)
        return self._http

    def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return MiMoSpeech(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self):
        if self._http is not None:
            await self._http.close()


class MiMoSpeech(tts.ChunkedStream):
    async def _run(self, output_emitter):
        output_emitter.initialize(request_id=uuid.uuid4().hex, sample_rate=24000,
                                  num_channels=1, mime_type='audio/pcm', frame_size_ms=20)
        usage = {}
        received = 0
        complete = False
        attempt = uuid.uuid4().hex
        chunks = pcm_chunks(self._tts.client(), self._tts.key, self._input_text, usage)
        try:
            async for chunk in chunks:
                received += len(chunk)
                output_emitter.push(chunk)
            complete = True
        except APIConnectionError:
            raise
        except Exception as error:
            # Do not leak request text, authorization headers or provider bodies.
            raise APIConnectionError(f'MiMo TTS failed ({type(error).__name__})') from None
        finally:
            await chunks.aclose()
            if self._tts.audit:
                self._tts.audit('provider_usage', {'provider': self._tts.provider,
                    'model': MODEL, 'attempt_id': attempt, 'phase': 'output_closed',
                    'input_characters': len(self._input_text), 'received_audio_seconds': received / 48000,
                    'complete': complete, 'usage': usage,
                    'billing_basis': 'received_audio_not_invoice'})
