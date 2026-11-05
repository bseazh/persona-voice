"""Seeduplex 3.0 JSON protocol, through LiveKit's public RealtimeSession API.

No OpenAI event-name compatibility assumptions. Input is paced 20ms PCM16;
output explicitly requests PCM16 (provider's `pcm` output is FLOAT32).
"""
import asyncio
import base64
import json
import time
import uuid
from types import SimpleNamespace

import aiohttp
from livekit import rtc
from livekit.agents import llm, utils
from livekit.agents.types import NOT_GIVEN

URL = 'wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue'
MODEL = '1.2.6.1'
VOICE = 'zh_male_xiaotian_jupiter_bigtts'
GREETING = '你好，我是AI小禾，我们的对话会保存文字转录和摘要。现在方便聊一聊吗？'
FAREWELL = '好的，再见。'


def config(instructions, voice=VOICE):
    return {'model': MODEL, 'instructions': instructions, 'audio': {
        'input': {'format': {'type': 'pcm', 'rate': 16000}},
        'output': {'format': {'type': 'pcm_s16le', 'rate': 24000}, 'voice': voice}}}


class DoubaoError(RuntimeError):
    """Only safe status codes, never raw provider payloads or keys."""


class Connection:
    def __init__(self, key, voice=VOICE):
        self.key, self.voice = key, voice
        self.client = None
        self.ws = None
        self.logid = None
        self.close_confirmed = False

    async def send(self, kind, **fields):
        await self.ws.send_json({'type': kind, 'event_id': uuid.uuid4().hex, **fields})

    async def recv(self):
        message = await self.ws.receive()
        if message.type != aiohttp.WSMsgType.TEXT:
            raise DoubaoError('connection_closed')
        event = json.loads(message.data)
        if event.get('type') == 'error':
            code = str(event.get('error', {}).get('code', event.get('status_code', 'unknown')))
            raise DoubaoError('provider_error_' + ''.join(c for c in code if c.isalnum() or c == '_')[:64])
        return event

    async def connect(self, instructions):
        self.client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        try:
            self.ws = await self.client.ws_connect(URL, headers={'X-Api-Key': self.key}, heartbeat=20)
            self.logid = self.ws._response.headers.get('X-Tt-Logid')
            await self.send('session.create', session=config(instructions, self.voice))
            async with asyncio.timeout(15):
                while (await self.recv()).get('type') != 'session.created':
                    pass
            # Until the audio pump starts, the provider must know the mic is muted.
            await self.send('input_audio_mute.commit')
        except BaseException:
            await self.close()
            raise

    async def close(self):
        # Owner stops its receive task first: exactly one receiver reads close ack.
        if self.ws is not None and not self.ws.closed:
            try:
                await self.send('session.close')
                async with asyncio.timeout(3):
                    while (await self.recv()).get('type') != 'session.closed':
                        pass
                self.close_confirmed = True
            except Exception:
                pass
            await self.ws.close()
        if self.client is not None:
            await self.client.close()


async def synthesize_control(key, text, voice=VOICE):
    """Bounded real-provider speech for greeting/tests/farewell, not canned audio."""
    conn = Connection(key, voice)
    frames = []
    try:
        async with asyncio.timeout(25):
            await conn.connect('请准确朗读提交的文字，不添加其他内容。')
            await conn.send('speech_text_buffer.commit', speech_id=uuid.uuid4().hex, text=text)
            size = 0
            while True:
                e = await conn.recv()
                if e.get('type') == 'response.output_audio.delta':
                    raw = base64.b64decode(e['delta'], validate=True)
                    size += len(raw)
                    if len(raw) % 2 or size > 24000 * 2 * 15:
                        raise DoubaoError('invalid_or_excess_audio')
                    if raw:
                        frames.append(rtc.AudioFrame(raw, 24000, 1, len(raw)//2))
                elif e.get('type') == 'response.output_audio.done':
                    break
            if not frames:
                raise DoubaoError('empty_audio')
        return text, frames, conn.logid
    finally:
        await conn.close()


class DoubaoRealtime(llm.RealtimeModel):
    route = 'doubao-realtime'

    def __init__(self, *, key, voice=VOICE, audit=None):
        super().__init__(capabilities=llm.RealtimeCapabilities(
            message_truncation=False, turn_detection=True, user_transcription=True,
            auto_tool_reply_generation=False, audio_output=True, manual_function_calls=False,
            mutable_instructions=True))
        self.key, self.voice, self.audit = key, voice, audit
        self.transport = SimpleNamespace(on_transcript=None)
        self.sessions = []
        self.muted = False

    @property
    def model(self): return MODEL

    @property
    def provider(self): return 'Volcengine/Seeduplex'

    def session(self, *, turn_detection_disabled=False):
        if turn_detection_disabled:
            raise ValueError('Seeduplex uses native turn detection')
        result = DoubaoSession(self)
        self.sessions.append(result)
        return result

    def mute_responses(self):
        self.muted = True
        for session in self.sessions:
            session.interrupt()

    async def farewell(self):
        text, frames, _ = await synthesize_control(self.key, FAREWELL, self.voice)
        return text, frames

    async def aclose(self):
        await asyncio.gather(*(s.aclose() for s in self.sessions))


class DoubaoSession(llm.RealtimeSession):
    def __init__(self, model):
        super().__init__(model)
        self.owner = model
        self.conn = Connection(model.key, model.voice)
        self._chat_ctx = llm.ChatContext()
        self._tools = llm.ToolContext([])
        self.instructions = ''
        self.task = None
        self.ready = asyncio.Event()
        self.closed = False
        self.failed = None
        self.audio = asyncio.Queue(maxsize=100)
        self.resampler = None
        self.partial = bytearray()
        self.generation = None
        self.audio_response = None
        self.blocked = set()
        self.pending = None
        self.pending_text = None
        self.user_id = None
        self.user_text = ''
        self.started = None
        self.tasks = set()
        self.close_lock = asyncio.Lock()

    @property
    def chat_ctx(self): return self._chat_ctx

    @property
    def tools(self): return self._tools

    def audit(self, kind, **payload):
        if self.owner.audit:
            self.owner.audit(kind, {'route': self.owner.route, 'at': time.time(), **payload})

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception() and not self.closed:
                self.fail(t.exception())
        task.add_done_callback(done)
        return task

    def fail(self, error):
        if self.failed or self.closed: return
        self.failed = error
        self.ready.set()
        self.audit('provider_failure', error_type=type(error).__name__,
                   code=str(error)[:80] if isinstance(error,DoubaoError) else None)
        self.emit('error', llm.RealtimeModelError(timestamp=time.time(), label=self.owner.label,
            error=DoubaoError('Seeduplex connection failed; verify key, entitlement and audio input'), recoverable=False))
        if self.pending and not self.pending.done():
            self.pending.set_exception(DoubaoError('generation_failed'))
        self.end_generation()

    async def update_instructions(self, instructions):
        self.instructions = instructions
        if self.task is None:
            self.task = self.spawn(self.run())
        else:
            await self.wait_ready()
            await self.conn.send('session.update', session={'instructions': instructions})

    async def update_chat_ctx(self, chat_ctx):
        # Provider manages native conversation history. No unsupported OpenAI item replay.
        self._chat_ctx = chat_ctx.copy()

    async def update_tools(self, tools):
        if tools: raise llm.RealtimeError('Seeduplex business tools not enabled in this route')

    def update_options(self, *, tool_choice=NOT_GIVEN): pass

    def push_video(self, frame): raise NotImplementedError('Audio only')

    async def wait_ready(self):
        await asyncio.wait_for(self.ready.wait(), 20)
        if self.failed or self.closed: raise DoubaoError('session_unavailable')

    def push_audio(self, frame):
        if self.closed or self.failed or self.owner.muted: return
        if frame.num_channels != 1: raise ValueError('Mono audio required')
        if self.resampler is None:
            self.resampler = rtc.AudioResampler(frame.sample_rate, 16000, num_channels=1)
        for converted in self.resampler.push(frame):
            self.partial.extend(bytes(converted.data))
        while len(self.partial) >= 640:
            packet = bytes(self.partial[:640]); del self.partial[:640]
            try: self.audio.put_nowait(packet)
            except asyncio.QueueFull:
                self.fail(DoubaoError('input_backpressure'))
                return

    async def pump(self):
        muted = True
        next_send = time.monotonic()
        while True:
            try:
                packet = await asyncio.wait_for(self.audio.get(), .15)
            except asyncio.TimeoutError:
                if not muted:
                    await self.conn.send('input_audio_mute.commit')
                    muted = True
                continue
            if self.owner.muted: continue
            if muted:
                await self.conn.send('input_audio_unmute.commit')
                muted = False
                next_send = time.monotonic()
            await asyncio.sleep(max(0, next_send-time.monotonic()))
            await self.conn.send('input_audio_buffer.append', audio=base64.b64encode(packet).decode())
            next_send = time.monotonic() + .02

    async def run(self):
        try:
            await self.conn.connect(self.instructions)
            self.audit('provider_connected', model=MODEL, logid=self.conn.logid)
            self.ready.set()
            self.spawn(self.pump())
            while not self.closed:
                self.handle(await self.conn.recv())
        except asyncio.CancelledError: raise
        except Exception as error: self.fail(error)

    def begin_generation(self, response_id):
        if self.generation and self.generation['id'] == response_id: return
        if self.generation: self.blocked.add(self.generation['id'])
        self.end_generation()
        messages, functions, text, audio = (utils.aio.Chan() for _ in range(4))
        modalities = asyncio.get_running_loop().create_future(); modalities.set_result(['audio', 'text'])
        messages.send_nowait(llm.MessageGeneration(response_id, text, audio, modalities))
        messages.close(); functions.close()
        explicit = self.pending is not None and not self.pending.done()
        event = llm.GenerationCreatedEvent(messages, functions, explicit, response_id)
        self.generation = {'id':response_id, 'text':text, 'audio':audio,
                           'transcript':'', 'first_audio':False, 'started':time.time()}
        self.audit('realtime_event', type='response.created', response_id=response_id)
        if explicit:
            self.pending.set_result(event)
            # Prescribed greeting has no generated text delta on some providers.
            if self.pending_text:
                text.send_nowait(self.pending_text)
                self.generation['transcript'] = self.pending_text
            self.pending = None; self.pending_text = None
        self.emit('generation_created', event)

    def end_generation(self):
        if self.generation:
            g = self.generation
            g['text'].close(); g['audio'].close()
            self.audit('realtime_event', type='response.finished', response_id=g['id'])
            self.generation = None

    def handle(self, e):
        kind = e.get('type', '')
        if kind.endswith('input_audio_transcription.started'):
            self.started = time.time(); self.user_id = e.get('item_id') or uuid.uuid4().hex; self.user_text = ''
            self.emit('input_speech_started', llm.InputSpeechStartedEvent())
            self.audit('realtime_event', type=kind, item_id=self.user_id)
        elif kind.endswith('input_audio_transcription.delta'):
            self.user_text += e.get('delta', '')
            self.emit('input_audio_transcription_completed', llm.InputTranscriptionCompleted(
                e.get('item_id') or self.user_id or uuid.uuid4().hex, self.user_text, False))
        elif kind.endswith('input_audio_transcription.completed'):
            text = e.get('transcript') or e.get('text') or self.user_text
            if self.owner.transport.on_transcript: self.owner.transport.on_transcript(text)
            self.emit('input_speech_stopped', llm.InputSpeechStoppedEvent(user_transcription_enabled=True))
            self.emit('input_audio_transcription_completed', llm.InputTranscriptionCompleted(
                e.get('item_id') or self.user_id or uuid.uuid4().hex, text, True, turn_started_at=self.started))
            self.audit('realtime_event', type=kind, item_id=e.get('item_id'))
        elif kind.endswith('input_audio_transcription.failed'):
            raise DoubaoError('transcription_failed')
        elif kind == 'response.canceled':
            # A delayed cancel ack must not close a newer response.
            self.audit('realtime_event', type=kind)
        elif kind.startswith('response.output_'):
            rid = e.get('response_id')
            if kind == 'response.output_audio.started':
                # Real Seeduplex audio deltas omit response_id. Bind them only
                # to the immediately preceding identified audio-start boundary.
                self.audio_response = rid if rid and rid not in self.blocked and not self.owner.muted else None
                return
            if kind == 'response.output_audio.delta' and not rid:
                rid = self.audio_response
                if not rid:
                    self.audit('realtime_audio_dropped', reason='no_active_audio_boundary')
                    return
            if not rid:
                raise DoubaoError('missing_response_id')
            if rid in self.blocked or self.owner.muted: return
            if kind in ('response.output_audio.delta', 'response.output_text.delta'):
                self.begin_generation(rid)
                g = self.generation
                if kind.endswith('audio.delta'):
                    raw = base64.b64decode(e['delta'], validate=True)
                    if len(raw) % 2: raise DoubaoError('invalid_pcm16')
                    if raw:
                        if not g['first_audio']:
                            self.audit('realtime_first_audio', response_id=rid)
                            g['first_audio'] = True
                        g['audio'].send_nowait(rtc.AudioFrame(raw, 24000, 1, len(raw)//2))
                else:
                    g['text'].send_nowait(e.get('delta', ''))
                    g['transcript'] += e.get('delta', '')
            elif kind == 'response.output_audio.done' and self.generation and self.generation['id'] == rid:
                if self.audio_response == rid: self.audio_response = None
                self.blocked.add(rid)
                self.end_generation()
            elif kind == 'response.output_text.done' and self.generation and self.generation['id'] == rid:
                final = e.get('text', '')
                previous = self.generation['transcript']
                if final.startswith(previous) and len(final) > len(previous):
                    self.generation['text'].send_nowait(final[len(previous):])
                    self.generation['transcript'] = final
        elif kind == 'session.closed' and not self.closed:
            raise DoubaoError('unexpected_session_closed')

    def generate_reply(self, *, instructions=NOT_GIVEN, tool_choice=NOT_GIVEN, tools=NOT_GIVEN):
        # Native opening is speech_text_buffer.commit, not unsupported response.create.
        future = asyncio.get_running_loop().create_future()
        if self.pending or self.generation or self.owner.muted:
            future.set_exception(llm.RealtimeError('Seeduplex opening requires an idle session'))
            return future
        self.pending, self.pending_text = future, GREETING
        async def opening():
            try:
                await self.wait_ready()
                await self.conn.send('speech_text_buffer.commit', speech_id=uuid.uuid4().hex, text=GREETING)
                await asyncio.wait_for(asyncio.shield(future), 20)
            except Exception:
                if not future.done(): future.set_exception(llm.RealtimeError('Seeduplex opening timed out'))
                self.pending = None; self.pending_text = None
                raise
        self.spawn(opening())
        return future

    def commit_audio(self): self.spawn(self.conn.send('input_audio_buffer.commit'))

    def clear_audio(self):
        self.partial.clear()
        while not self.audio.empty(): self.audio.get_nowait()

    def interrupt(self):
        self.audio_response = None
        if self.generation:
            self.blocked.add(self.generation['id'])
            self.end_generation()
            if self.conn.ws and not self.conn.ws.closed:
                self.spawn(self.conn.send('response.cancel'))

    def truncate(self, **kwargs): pass  # capability explicitly false

    async def aclose(self):
        async with self.close_lock:
            if self.closed: return
            self.closed = True; self.ready.set()
            for task in tuple(self.tasks): task.cancel()
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
            self.end_generation()
            if self.pending and not self.pending.done(): self.pending.cancel()
            await self.conn.close()
            self.audit('provider_closed', confirmed=self.conn.close_confirmed)
