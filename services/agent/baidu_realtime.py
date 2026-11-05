"""Baidu Lite protocol adapter reusing the production Qwen/LiveKit bridge."""
import base64
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from dotenv import dotenv_values
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from livekit.plugins.openai import realtime
from openai.types.beta.realtime.session import TurnDetection, InputAudioTranscription
from qwen_realtime import QwenSocket

MODEL = 'audio-mini-realtime-near'
ROOT = Path(__file__).resolve().parents[2]
URL = 'wss://aip.baidubce.com/ws/2.0/speech/v1/realtime'


def numeric_usage(value):
    if isinstance(value, dict):
        return {k:numeric_usage(v) for k,v in value.items() if isinstance(v,(dict,int,float)) and not isinstance(v,bool)}
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) else None


class WireSocket:
    """Translate websocket library API; QwenSocket retains RTC routing."""
    def __init__(self, ws): self.ws = ws
    async def send_str(self, value): await self.ws.send(value)
    async def close(self): await self.ws.close()
    async def receive(self):
        try:
            raw = await self.ws.recv()
            return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, raw, '')
        except ConnectionClosed:
            return aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, None, '')


class BaiduSocket(QwenSocket):
    def __init__(self, ws, audit=None):
        super().__init__(ws,audit)
        self.seen_usage = set()
        self.first_audio = set()

    async def send_str(self, data):
        e=json.loads(data)
        kind=e['type']
        if kind=='session.update':
            # Lite supports neither custom instructions nor business tools.
            await self.ws.send_str(json.dumps({'type':'session.update','session':{
                'input_audio_transcription':{'model':'default'},'voice':'8003'}}))
            return
        if kind=='response.cancel':
            self.router.cancel()
            return
        if kind in ('conversation.item.create','conversation.item.delete','conversation.item.truncate',
                    'input_audio_buffer.commit','input_audio_buffer.clear'):
            return  # Lite owns conversation history and commits.
        if kind=='response.create':
            raise RuntimeError('Baidu Lite requires audio input, not manual response.create')
        await super().send_str(data)

    def translate(self,e):
        kind=e['type']
        if kind=='response.audio.delta':
            e={**e,'delta':''.join(e.get('delta','').split())}
            base64.b64decode(e['delta'],validate=True)
            rid=e.get('response_id')
            if rid not in self.first_audio:
                self.first_audio.add(rid)
                if self.audit:self.audit('realtime_first_audio',{'at':time.time(),'response_id':rid,'route':'baidu-realtime'})
        if kind=='response.done':
            r=e.get('response',{});rid=r.get('id')
            if rid not in self.seen_usage:
                self.seen_usage.add(rid)
                if self.audit:self.audit('baidu_usage',{'at':time.time(),'response_id':rid,
                    'usage':numeric_usage(r.get('usage')),'usage_present':r.get('usage') is not None,
                    'status':r.get('status'),'route':'baidu-realtime'})
        return super().translate(e)


class BaiduTransport:
    def __init__(self,audit=None):
        self.audit=audit;self.sockets=[];self.on_transcript=None

    async def ws_connect(self,*,url,headers):
        credentials=dotenv_values(ROOT/'data/baidu.env')
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as client:
            async with client.post('https://aip.baidubce.com/oauth/2.0/token',data={
                'grant_type':'client_credentials','client_id':credentials['BAIDU_API_KEY'],
                'client_secret':credentials['BAIDU_SECRET_KEY']}) as response:
                auth=await response.json(content_type=None)
        if not auth.get('access_token'):raise RuntimeError('baidu_auth_failed')
        try:
            ws=await connect(URL+'?'+urlencode({'model':MODEL,'access_token':auth['access_token']}),
                             proxy=None,open_timeout=15,max_size=4*1024*1024)
        except Exception:
            raise RuntimeError('baidu_connection_failed') from None
        socket=BaiduSocket(WireSocket(ws),self.audit)
        socket.on_transcript=lambda text:self.on_transcript(text) if self.on_transcript else None
        self.sockets.append(socket)
        if self.audit:self.audit('provider_connected',{'at':time.time(),'model':MODEL,'route':'baidu-realtime'})
        return socket

    async def close(self):
        for socket in self.sockets:await socket.close()


class BaiduRealtime(realtime.RealtimeModel):
    route='baidu-realtime'
    voice='8003'

    def __init__(self,*,audit=None):
        self.transport=BaiduTransport(audit)
        super().__init__(model=MODEL,voice='8003',api_key='server-side-oauth',base_url=URL,
            http_session=self.transport,turn_detection=TurnDetection(type='server_vad'),
            input_audio_transcription=InputAudioTranscription(model='default'))

    @property
    def provider(self):return 'Baidu/Lite'

    def mute_responses(self):
        for socket in self.transport.sockets:socket.router.muted=True

    async def farewell(self):raise RuntimeError('baidu_explicit_farewell_not_supported')

    async def aclose(self):
        await super().aclose()
        await self.transport.close()
