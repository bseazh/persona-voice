"""DashScope duplex streaming with an explicit legacy rollback mode."""
import asyncio
import os
import re
import uuid

import dashscope
from livekit.agents import APIConnectionError, DEFAULT_API_CONNECT_OPTIONS, tts


def tts_mode():
    mode = os.getenv('QWEN_TTS_MODE', 'duplex-v1')
    if mode not in ('duplex-v1', 'sentence'):
        raise ValueError('QWEN_TTS_MODE must be duplex-v1 or sentence')
    return mode


class QwenTTS(tts.TTS):
    def __init__(self, *, key=None, workspace=None):
        self.mode = tts_mode()
        super().__init__(capabilities=tts.TTSCapabilities(streaming=self.mode == 'duplex-v1'),
                         sample_rate=24000, num_channels=1)
        self.key = key or os.getenv('DASHSCOPE_TTS_API_KEY') or os.environ['DASHSCOPE_API_KEY']
        self.workspace = (os.getenv('DASHSCOPE_TTS_WORKSPACE') or os.getenv('DASHSCOPE_WORKSPACE','')) if workspace is None else workspace
        self.voice = os.getenv('QWEN_TTS_VOICE', 'longanhuan_v3.1')

    @property
    def model(self):
        return os.getenv('QWEN_TTS_MODEL', 'qwen-audio-3.1-tts-flash')

    @property
    def provider(self):
        return 'DashScope'

    def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        if self.mode == 'duplex-v1':
            return self._synthesize_with_stream(text, conn_options=conn_options)
        return QwenSpeech(tts=self, input_text=text, conn_options=conn_options)

    def stream(self, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return QwenDuplex(tts=self, conn_options=conn_options)


class QwenDuplex(tts.SynthesizeStream):
    async def _run(self, output_emitter):
        engine = self._tts
        client = dashscope.Client(api_key=engine.key, workspace=engine.workspace,
                                 region='cn-beijing', timeout=10)
        session = None
        receiver = None
        starting = None
        buffered_chars = 0
        output_emitter.initialize(request_id=uuid.uuid4().hex, sample_rate=24000,
                                  num_channels=1, mime_type='audio/pcm',
                                  frame_size_ms=20, stream=True)

        async def receive(active):
            chunks = active.audio_chunks()
            while True:
                chunk = await asyncio.to_thread(next, chunks, None)
                if chunk is None:
                    return
                output_emitter.push(chunk)

        async def finish_segment():
            nonlocal session, receiver, buffered_chars
            if session is None:
                return
            await asyncio.to_thread(session.stop)
            await receiver
            output_emitter.end_segment()
            await asyncio.to_thread(session.close)
            session, receiver, buffered_chars = None, None, 0

        try:
            async for item in self._input_ch:
                if isinstance(item, self._FlushSentinel):
                    await finish_segment()
                    continue
                if not item:
                    continue
                if session is None:
                    self._mark_started()
                    session = client.audio.tts.connect(model=engine.model, voice=engine.voice,
                                                      format='pcm', sample_rate=24000, timeout=10)
                    starting = asyncio.create_task(asyncio.to_thread(session.start))
                    await asyncio.shield(starting)
                    starting = None
                    output_emitter.start_segment(segment_id=uuid.uuid4().hex)
                    receiver = asyncio.create_task(receive(session))
                # Producer and consumer run concurrently; never wait for full LLM output.
                await asyncio.to_thread(session.send_text, item)
                buffered_chars += len(item.strip())
                if buffered_chars >= 8 and re.search(r'[，。！？；,.!?;\n]', item):
                    await asyncio.to_thread(session.flush)
                    buffered_chars = 0
            await finish_segment()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise APIConnectionError(f'Qwen duplex TTS failed ({type(error).__name__})') from None
        finally:
            # A cancelled to_thread(start) keeps running; await it before closing to avoid
            # creating a connection after cleanup. close unblocks a pending audio reader.
            if starting is not None:
                await asyncio.gather(starting, return_exceptions=True)
            if session is not None:
                await asyncio.to_thread(session.close)
            if receiver is not None:
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
            await asyncio.to_thread(client.close)


class QwenSpeech(tts.ChunkedStream):
    async def _run(self, output_emitter):
        engine = self._tts
        client = dashscope.Client(api_key=engine.key, workspace=engine.workspace,
                                 region='cn-beijing', timeout=30)
        session = client.audio.tts.connect(model=engine.model, voice=engine.voice,
                                          format='pcm', sample_rate=24000, timeout=30)
        try:
            await asyncio.to_thread(session.__enter__)
            await asyncio.to_thread(session.send_text, self._input_text)
            await asyncio.to_thread(session.stop)
            output_emitter.initialize(request_id=uuid.uuid4().hex, sample_rate=24000,
                                      num_channels=1, mime_type='audio/pcm', frame_size_ms=20)
            chunks = session.audio_chunks()
            while True:
                chunk = await asyncio.to_thread(next, chunks, None)
                if chunk is None:
                    break
                output_emitter.push(chunk)
        finally:
            await asyncio.to_thread(session.close)
            await asyncio.to_thread(client.close)
