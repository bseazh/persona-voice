"""EXPERIMENTAL: Qwen beta bridge for pinned LiveKit 1.8.10; NOT production-ready.

Keeps LiveKit's audio scheduling, cancellation, tools and transcript machinery.
The public http_session hook confines provider differences to the transport.
Known blockers: late events after cancellation, automatic ending reliability,
and correlation of concurrent server VAD / explicit responses. Only probes use it.
"""
import base64
import collections
import json
import os
import time

import aiohttp
from openai.types.beta.realtime.session import TurnDetection, InputAudioTranscription
from livekit import rtc
from livekit.plugins.openai import realtime

MODEL = 'qwen-audio-3.1-realtime-flash'
URL = 'wss://ws-kc0oqyijpss62nix.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime'
EVENTS = {
    'response.audio.delta':'response.output_audio.delta',
    'response.audio.done':'response.output_audio.done',
    'response.audio_transcript.delta':'response.output_audio_transcript.delta',
    'response.audio_transcript.done':'response.output_audio_transcript.done',
    'response.text.delta':'response.output_text.delta',
    'response.text.done':'response.output_text.done',
    'conversation.item.created':'conversation.item.added',
}


def session_payload(source):
    result = {k:source[k] for k in ('instructions','tools','tool_choice') if k in source}
    if 'output_modalities' in source:
        result['modalities'] = ['text','audio'] if 'audio' in source['output_modalities'] else ['text']
    audio=source.get('audio',{})
    if 'voice' in audio.get('output',{}):result['voice']=audio['output']['voice']
    if 'turn_detection' in audio.get('input',{}):
        turn=audio['input']['turn_detection']
        result['turn_detection'] = None if turn is None else {
            k:turn[k] for k in ('type','threshold','silence_duration_ms','prefix_padding_ms') if k in turn}
    return result


class QwenSocket:
    def __init__(self, ws, audit=None):
        self.ws, self.audit = ws, audit
        self.resampler=rtc.AudioResampler(24000,16000,num_channels=1)
        self.pending=collections.deque()
        self.has_user=False
        self.server_turn_pending=False

    async def send_str(self, data):
        e=json.loads(data); t=e['type']
        if t=='session.update':
            e['session']=session_payload(e['session'])
        elif t=='input_audio_buffer.append':
            pcm=base64.b64decode(e['audio'])
            frame=rtc.AudioFrame(data=pcm,sample_rate=24000,num_channels=1,samples_per_channel=len(pcm)//2)
            pcm=b''.join(bytes(f.data) for f in self.resampler.push(frame))
            if not pcm:return
            e['audio']=base64.b64encode(pcm).decode()
        elif t=='conversation.item.create':
            if e.get('previous_item_id')=='root':e.pop('previous_item_id')
            item=e['item']
            if item.get('role')=='user':self.has_user=True
            for part in item.get('content',[]):
                if part.get('type')=='output_text':part['type']='text'
        elif t=='response.create':
            response=e.setdefault('response',{})
            # Qwen does not echo OpenAI's response metadata. Only one explicit
            # generation may be outstanding; auto turns are identified separately.
            if self.pending:
                raise RuntimeError('Qwen explicit response already pending')
            if isinstance(response.get('tool_choice'),dict):
                raise ValueError('Qwen supports auto/none/required tool_choice, not named forcing')
            metadata=response.pop('metadata',{}) or {}
            self.pending.append((e.get('event_id'),metadata))
            response.pop('output_modalities',None)
            if not self.has_user:
                await self.ws.send_str(json.dumps({'type':'conversation.item.create','item':{
                    'type':'message','role':'user','content':[{'type':'input_text',
                    'text':'请按系统要求简短开场。'}]}}))
                self.has_user=True
        await self.ws.send_str(json.dumps(e,ensure_ascii=False))
        if self.audit and t in ('session.update', 'response.create'):
            payload=e.get('session',e.get('response',{}))
            self.audit('wire_request',{'type':t,'fields':list(payload),
                'tool_names':[x.get('name') for x in payload.get('tools',[])],
                'tool_choice':payload.get('tool_choice')})

    async def receive(self):
        msg=await self.ws.receive()
        if msg.type!=aiohttp.WSMsgType.TEXT:return msg
        e=json.loads(msg.data); original=e['type']
        if self.audit and original=='session.updated':
            self.audit('wire_session',{'tool_names':[x.get('name') for x in e.get('session',{}).get('tools',[])]})
        if original=='input_audio_buffer.speech_started':self.has_user=True
        if original=='input_audio_buffer.speech_stopped':self.server_turn_pending=True
        if original=='response.created':
            if self.server_turn_pending:
                self.server_turn_pending=False
            elif self.pending:
                _,metadata=self.pending.popleft()
                e['response']['metadata']=metadata
        if original=='error':
            error=e.get('error',{})
            event_id=error.get('event_id')
            self.pending=collections.deque(p for p in self.pending if p[0]!=event_id)
        if self.audit and original in ('input_audio_buffer.speech_started','input_audio_buffer.speech_stopped',
                                       'response.created','response.done'):
            self.audit('realtime_event',{'type':original,'at':time.time(),
                'response_id':e.get('response',{}).get('id'),
                'status':e.get('response',{}).get('status')})
        e['type']=EVENTS.get(original,original)
        return aiohttp.WSMessage(msg.type,json.dumps(e),msg.extra)

    async def close(self):await self.ws.close()


class QwenTransport:
    def __init__(self,audit=None):
        self.client=aiohttp.ClientSession()
        self.audit=audit
    async def ws_connect(self,*,url,headers):
        return QwenSocket(await self.client.ws_connect(url,headers=headers),self.audit)
    async def close(self):await self.client.close()


class QwenRealtime(realtime.RealtimeModel):
    def __init__(self, *, key=None, audit=None):
        self.transport=QwenTransport(audit)
        super().__init__(model=MODEL,voice='longanqian',
            api_key=key or os.environ['DASHSCOPE_API_KEY'],base_url=URL,
            http_session=self.transport,
            turn_detection=TurnDetection(type='server_vad',threshold=.5,silence_duration_ms=500),
            # Capability flag only: the wire bridge leaves Qwen's native transcription on.
            input_audio_transcription=InputAudioTranscription(model=MODEL))

    @property
    def provider(self):return 'DashScope/Qwen Realtime'

    async def aclose(self):
        await super().aclose()
        await self.transport.close()
