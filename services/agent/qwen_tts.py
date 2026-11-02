"""DashScope synthesis with LiveKit's sentence streaming adapter."""
import asyncio
import os
import uuid

import dashscope
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, tts


class QwenTTS(tts.TTS):
    def __init__(self):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False),
                         sample_rate=24000, num_channels=1)
        self.key = os.getenv('DASHSCOPE_TTS_API_KEY') or os.environ['DASHSCOPE_API_KEY']
        self.workspace = os.environ['DASHSCOPE_WORKSPACE']
        self.voice = os.getenv('QWEN_TTS_VOICE', 'longanhuan_v3.1')

    @property
    def model(self):
        return os.getenv('QWEN_TTS_MODEL', 'qwen-audio-3.1-tts-flash')

    @property
    def provider(self):
        return 'DashScope'

    def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return QwenSpeech(tts=self, input_text=text, conn_options=conn_options)


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
