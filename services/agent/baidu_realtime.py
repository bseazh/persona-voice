"""Baidu Lite native speech; public LiveKit generation channels, provider usage audit."""
import asyncio
import base64
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from dotenv import dotenv_values
from websockets.asyncio.client import connect
from livekit.agents import llm
from doubao_realtime import DoubaoRealtime, DoubaoSession

MODEL = 'audio-mini-realtime-near'
ROOT = Path(__file__).resolve().parents[2]


class BaiduConnection:
    def __init__(self):
        self.ws = None
        self.logid = None
        self.close_confirmed = False

    async def send(self, kind, **fields):
        await self.ws.send(json.dumps({'type': kind, **fields}, ensure_ascii=False))

    async def recv(self):
        event = json.loads(await self.ws.recv())
        if event.get('type') == 'error':
            # Never include raw URLs, credentials or provider response bodies.
            raise RuntimeError('baidu_provider_error')
        return event

    async def connect(self, instructions=''):
        credentials = dotenv_values(ROOT / 'data/baidu.env')
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as client:
            async with client.post('https://aip.baidubce.com/oauth/2.0/token', data={
                'grant_type': 'client_credentials',
                'client_id': credentials['BAIDU_API_KEY'],
                'client_secret': credentials['BAIDU_SECRET_KEY']}) as response:
                auth = await response.json(content_type=None)
        token = auth.get('access_token')
        if not token: raise RuntimeError('baidu_auth_failed')
        url = 'wss://aip.baidubce.com/ws/2.0/speech/v1/realtime?' + urlencode({'model':MODEL,'access_token':token})
        self.ws = await connect(url, proxy=None, open_timeout=15, max_size=4*1024*1024)
        await self.send('session.update', session={'input_audio_transcription':{'model':'default'},'voice':'8003'})
        async with asyncio.timeout(15):
            while True:
                e = await self.recv()
                if e['type'] == 'session.created': self.logid = e.get('session',{}).get('id')
                if e['type'] == 'session.updated': break

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
            self.close_confirmed = True


class BaiduRealtime(DoubaoRealtime):
    route = 'baidu-realtime'

    def __init__(self, *, audit=None):
        super().__init__(key='', voice='8003', audit=audit)
        self._capabilities.mutable_instructions = False

    @property
    def model(self): return MODEL

    @property
    def provider(self): return 'Baidu/Lite'

    def session(self, *, turn_detection_disabled=False):
        if turn_detection_disabled: raise ValueError('Baidu requires native VAD')
        result = BaiduSession(self)
        self.sessions.append(result)
        return result

    async def farewell(self):
        # Lite documents no explicit speech-generation command. Controller closes
        # after native goodbye when available; operator timeout closes without
        # inventing a provider-generated farewell or calling another paid TTS.
        raise RuntimeError('baidu_explicit_farewell_not_supported')


class BaiduSession(DoubaoSession):
    def __init__(self, model):
        super().__init__(model)
        self.conn = BaiduConnection()
        self.response_ids = set()
        self.input_bytes = 0
        self.output_bytes = 0

    async def update_instructions(self, instructions):
        # Lite has no custom system-prompt support; do not claim templates apply.
        if self.task is None: self.task = self.spawn(self.run())

    async def pump(self):
        while True:
            packet = await self.audio.get()
            if self.owner.muted: continue
            await self.conn.send('input_audio_buffer.append', audio=base64.b64encode(packet).decode())
            self.input_bytes += len(packet)

    async def run(self):
        try:
            await self.conn.connect()
            self.audit('provider_connected', model=MODEL, provider_session_id=self.conn.logid)
            self.ready.set()
            self.spawn(self.pump())
            while not self.closed: self.handle(await self.conn.recv())
        except asyncio.CancelledError: raise
        except Exception as error: self.fail(error)

    def handle(self, e):
        kind = e.get('type','')
        if kind == 'input_audio_buffer.speech_started':
            self.interrupt()
            self.started = time.time()
            self.user_id = e.get('item_id')
            self.user_text = ''
            self.emit('input_speech_started', llm.InputSpeechStartedEvent())
            self.audit('realtime_event', type=kind, item_id=self.user_id)
        elif kind == 'input_audio_buffer.speech_stopped':
            self.emit('input_speech_stopped', llm.InputSpeechStoppedEvent(user_transcription_enabled=True))
            self.audit('realtime_event', type=kind, item_id=e.get('item_id'))
        elif kind.endswith('input_audio_transcription.completed'):
            text = e.get('transcript','')
            # Native goodbye is allowed to finish; do not cancel it on transcript.
            if self.owner.transport.on_transcript: self.owner.transport.on_transcript(text)
            self.emit('input_audio_transcription_completed', llm.InputTranscriptionCompleted(
                e.get('item_id') or self.user_id, text, True, turn_started_at=self.started))
            self.audit('realtime_event', type=kind, item_id=e.get('item_id'))
        elif kind.endswith('input_audio_transcription.delta'):
            self.user_text += e.get('delta','')
            self.emit('input_audio_transcription_completed', llm.InputTranscriptionCompleted(
                e.get('item_id') or self.user_id, self.user_text, False))
        elif kind == 'response.created':
            rid = e['response']['id']
            if not self.owner.muted: self.begin_generation(rid)
        elif kind in ('response.audio.delta','response.audio_transcript.delta','response.audio_transcript.done'):
            rid = e.get('response_id')
            if self.owner.muted or rid in self.blocked or not self.generation or self.generation['id'] != rid: return
            mapped = {'response.audio.delta':'response.output_audio.delta',
                      'response.audio_transcript.delta':'response.output_text.delta',
                      'response.audio_transcript.done':'response.output_text.done'}[kind]
            if kind == 'response.audio.delta':
                # Baidu may line-wrap base64; normalize whitespace, retain strict validation.
                e = {**e, 'delta': ''.join(e['delta'].split())}
                self.output_bytes += len(base64.b64decode(e['delta'], validate=True))
            super().handle({**e,'type':mapped,'text':e.get('transcript','')})
        elif kind == 'response.done':
            response = e.get('response',{})
            rid = response.get('id')
            if rid not in self.response_ids:
                self.response_ids.add(rid)
                # Preserve numeric usage only; no personal content or raw secrets.
                self.audit('baidu_usage', response_id=rid, status=response.get('status'),
                           usage=numeric_usage(response.get('usage')), usage_present=response.get('usage') is not None)
            if self.generation and self.generation['id'] == rid: self.end_generation()
        elif kind.endswith('input_audio_transcription.failed'):
            raise RuntimeError('baidu_transcription_failed')

    def interrupt(self):
        # Provider VAD cancels generation itself. No undocumented response.cancel.
        if self.generation:
            self.blocked.add(self.generation['id'])
            self.end_generation()

    def commit_audio(self): pass  # server_vad performs commits

    def generate_reply(self, **kwargs):
        raise llm.RealtimeError('Baidu Lite requires audio input; no manual opening')

    async def aclose(self):
        if not self.closed:
            self.audit('baidu_transport_usage', input_pcm_bytes=self.input_bytes,
                       output_pcm_bytes=self.output_bytes, input_seconds=self.input_bytes/32000,
                       output_seconds=self.output_bytes/48000, tokens_inferred=False)
        await super().aclose()


def numeric_usage(value):
    if isinstance(value, dict): return {k:numeric_usage(v) for k,v in value.items() if isinstance(v,(dict,int,float)) and not isinstance(v,bool)}
    if isinstance(value,(int,float)) and not isinstance(value,bool): return value
    return None
