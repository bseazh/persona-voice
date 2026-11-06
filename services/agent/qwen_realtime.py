"""Opt-in Qwen beta bridge for pinned LiveKit 1.8.10.

Keeps LiveKit's audio scheduling, cancellation, tools and transcript machinery.
The public http_session hook confines provider differences to the transport.
Explicit generation is restricted to idle turns; normal duplex turns are native
server VAD responses. Business ending is controlled outside model tool selection.
"""
import base64
import asyncio
import collections
import json
import os
import time

import aiohttp
from openai.types.beta.realtime.session import TurnDetection, InputAudioTranscription
from livekit import rtc
from livekit.plugins.openai import realtime
from realtime_control import ResponseRouter

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
    def __init__(self, ws, audit=None, turn_mode='server_vad'):
        self.ws, self.audit = ws, audit
        self.turn_mode = turn_mode
        self.resampler=rtc.AudioResampler(24000,16000,num_channels=1)
        self.pending=collections.deque()
        self.has_user=False
        self.server_turn_pending=False
        self.router=ResponseRouter(audit)
        self.ready=collections.deque()
        self.on_transcript=None
        self.audio_response_id=None

    async def send_str(self, data):
        e=json.loads(data); t=e['type']
        if t=='response.cancel':
            if not self.router.cancel():return
            e['response_id']=self.router.active
        if t=='input_audio_buffer.append' and self.router.muted:return
        if t=='session.update':
            e['session']=session_payload(e['session'])
            turn=e['session'].get('turn_detection')
            if turn is not None and self.turn_mode=='smart_turn_v2':
                # Keep provider-specific modes out of the OpenAI SDK schema.
                e['session']['turn_detection']={'type':'smart_turn_v2','threshold':turn.get('threshold',.5)}
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
            # Qwen requires output_text for assistant context replay (including
            # session.say's actual farewell transcript), not the older 'text'.
        elif t=='response.create':
            response=e.setdefault('response',{})
            # Qwen does not echo OpenAI's response metadata. Only one explicit
            # generation may be outstanding; auto turns are identified separately.
            if self.pending or self.server_turn_pending or self.router.active or self.router.muted:
                raise RuntimeError('Qwen explicit generation requires an idle, unmuted turn')
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
        elif t=='input_audio_buffer.clear':
            self.resampler=rtc.AudioResampler(24000,16000,num_channels=1)
        await self.ws.send_str(json.dumps(e,ensure_ascii=False))
        if self.audit and t=='conversation.item.create' and e.get('item',{}).get('type')=='function_call_output':
            self.audit('wire_tool_output',{'at':time.time(),'call_id':e['item'].get('call_id'),
                'characters':len(e['item'].get('output',''))})
        if self.audit and t in ('session.update', 'response.create'):
            payload=e.get('session',e.get('response',{}))
            self.audit('wire_request',{'type':t,'fields':list(payload),
                'at':time.time(),
                'tool_names':[x.get('name') for x in payload.get('tools',[])],
                'turn_detection':payload.get('turn_detection'),
                'tool_choice':payload.get('tool_choice')})

    async def receive(self):
        while not self.ready:
            msg=await self.ws.receive()
            if msg.type!=aiohttp.WSMsgType.TEXT:return msg
            e=json.loads(msg.data)
            self.ready.extend(self.translate(e))
        e=self.ready.popleft()
        e['type']=EVENTS.get(e['type'],e['type'])
        return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT,json.dumps(e),'')

    def translate(self,e):
        original=e['type']
        if original.startswith('conversation.item.ambient_audio_transcription.'):
            # Ambient/backchannel text must not become a user turn or an end command.
            if self.audit:self.audit('ambient_audio',{'at':time.time(),'type':original,
                'item_id':e.get('item_id'),'text':e.get('delta',e.get('transcript',''))})
            return []
        if self.audit and original=='response.function_call_arguments.done':
            self.audit('wire_tool_arguments_done',{'at':time.time(),'response_id':e.get('response_id'),'call_id':e.get('call_id')})
        if original=='response.created':self.audio_response_id=None
        if (self.audit and original=='response.audio.delta' and e.get('response_id')==self.router.active
                and not self.router.muted and not self.router.cancelling and self.audio_response_id!=e.get('response_id')):
            self.audio_response_id=e.get('response_id')
            self.audit('wire_first_audio',{'at':time.time(),'response_id':self.audio_response_id})
        if self.audit and original=='session.updated':
            self.audit('wire_session',{'tool_names':[x.get('name') for x in e.get('session',{}).get('tools',[])],
                'turn_detection':e.get('session',{}).get('turn_detection')})
        if original=='input_audio_buffer.speech_started':
            self.has_user=True
        if original=='conversation.item.input_audio_transcription.completed' and self.on_transcript:
            self.on_transcript(e.get('transcript',''))
        if original=='input_audio_buffer.speech_stopped':
            self.server_turn_pending=e.get('reason')!='turn_invalid'
        if original=='response.created':
            if self.server_turn_pending:
                self.server_turn_pending=False
            elif self.pending:
                _,metadata=self.pending.popleft()
                e['response']['metadata']=metadata
        if original=='error':
            error=e.get('error',{})
            # Qwen server-VAD may have cancelled/completed the same response
            # just before LiveKit's cancellation arrives. This exact response
            # is an idempotent cancel acknowledgement, not a provider outage.
            if (error.get('param')=='response.cancel' and
                    error.get('message')=='Conversation has no active response.'):
                if self.audit:self.audit('cancel_already_finished',{'type':'response.cancel'})
                return []
            event_id=error.get('event_id')
            self.pending=collections.deque(p for p in self.pending if p[0]!=event_id)
        if self.audit and original in ('input_audio_buffer.speech_started','input_audio_buffer.speech_stopped',
                                       'response.created','response.done'):
            self.audit('realtime_event',{'type':original,'at':time.time(),
                'response_id':e.get('response',{}).get('id'),
                'reason':e.get('reason'),
                'status':e.get('response',{}).get('status')})
        return self.router.feed(e)

    async def close(self):await self.ws.close()


class QwenTransport:
    def __init__(self,audit=None,turn_mode='server_vad'):
        self.client=aiohttp.ClientSession()
        self.audit=audit
        self.sockets=[]
        self.on_transcript=None
        self.turn_mode=turn_mode
    async def ws_connect(self,*,url,headers):
        socket=QwenSocket(await self.client.ws_connect(url,headers=headers),self.audit,self.turn_mode)
        socket.on_transcript=lambda text:self.on_transcript(text) if self.on_transcript else None
        self.sockets.append(socket)
        return socket
    async def close(self):await self.client.close()


class QwenRealtime(realtime.RealtimeModel):
    def __init__(self, *, key=None, audit=None):
        self.turn_mode=os.getenv('QWEN_TURN_MODE','smart_turn_v2')
        if self.turn_mode not in ('server_vad','smart_turn_v2'):
            raise ValueError('QWEN_TURN_MODE must be server_vad or smart_turn_v2')
        self.transport=QwenTransport(audit,self.turn_mode)
        self.key=key or os.environ['DASHSCOPE_API_KEY']
        super().__init__(model=MODEL,voice='longanqian',
            api_key=self.key,base_url=URL,
            http_session=self.transport,
            turn_detection=TurnDetection(type='server_vad',threshold=.5,silence_duration_ms=500),
            # Capability flag only: the wire bridge leaves Qwen's native transcription on.
            input_audio_transcription=InputAudioTranscription(model=MODEL))

    @property
    def provider(self):return 'DashScope/Qwen Realtime'

    def mute_responses(self):
        for socket in self.transport.sockets:socket.router.muted=True

    async def farewell(self, reason=None):
        """A bounded, separate native-realtime utterance; no standalone TTS.

        Buffer only this short final utterance so the transcript saved for it
        is the provider's actual spoken text, not an assumed script.
        """
        async with asyncio.timeout(15):
            async with self.transport.client.ws_connect(URL+'?model='+MODEL,
                    headers={'Authorization':'Bearer '+self.key}) as ws:
                await ws.send_json({'type':'session.update','session':{
                    'modalities':['text','audio'],'voice':'longanqian','turn_detection':None,
                    'instructions':'你是中文AI助手。对话已结束。只说一句简短告别，不提问、不解释、不调用工具。'}})
                await ws.send_json({'type':'conversation.item.create','item':{
                    'type':'message','role':'user','content':[{'type':'input_text','text':
                        '请简短告别，说：通话时间快到了，我们先聊到这里，再见。' if reason=='duration_limit' else '请简短告别，说：好的，再见。'}]}})
                await ws.send_json({'type':'response.create'})
                frames=[]
                transcript=''
                async for msg in ws:
                    if msg.type!=aiohttp.WSMsgType.TEXT:raise RuntimeError('farewell_socket_closed')
                    e=json.loads(msg.data)
                    if e['type']=='error':raise RuntimeError('farewell_provider_error')
                    if e['type']=='response.audio.delta':
                        pcm=base64.b64decode(e['delta'])
                        frames.append(rtc.AudioFrame(data=pcm,sample_rate=24000,num_channels=1,samples_per_channel=len(pcm)//2))
                    if e['type']=='response.audio_transcript.done':transcript=e.get('transcript','')
                    if e['type']=='response.done':
                        if e['response'].get('status')!='completed' or not frames or not transcript:
                            raise RuntimeError('farewell_incomplete')
                        return transcript,frames
        raise RuntimeError('farewell_missing')

    async def aclose(self):
        await super().aclose()
        await self.transport.close()
