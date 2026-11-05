"""MiMo utterance ASR; LiveKit VAD supplies segmentation, not duplex upload."""
import base64
import io
import os
import time
import uuid
import wave

import aiohttp
from livekit import rtc
from livekit.agents import APIConnectionError, stt

URL = 'https://api.xiaomimimo.com/v1/chat/completions'


class MiMoSTT(stt.STT):
    def __init__(self, *, audit=None):
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self.key = os.environ['MIMO_API_KEY']
        self.audit = audit
        self._http = None

    @property
    def model(self): return 'mimo-v2.5-asr'

    @property
    def provider(self): return 'Xiaomi/MiMo'

    async def aclose(self):
        if self._http: await self._http.close()

    async def _recognize_impl(self, buffer, *, language, conn_options):
        frame = rtc.combine_audio_frames(buffer)
        if frame.num_channels != 1: raise ValueError('MiMo ASR requires mono')
        resampler = rtc.AudioResampler(frame.sample_rate, 16000, num_channels=1)
        pcm = b''.join(bytes(f.data) for f in resampler.push(frame) + resampler.flush())
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(pcm)
        encoded = base64.b64encode(output.getvalue()).decode()
        if len(encoded) > 10_000_000: raise APIConnectionError('MiMo ASR audio too large')
        body = {'model': self.model, 'messages': [{'role': 'user', 'content': [
            {'type': 'input_audio', 'input_audio': {'data': 'data:audio/wav;base64,' + encoded}}]}],
            'asr_options': {'language': 'zh'}, 'stream': False}
        attempt = uuid.uuid4().hex
        seconds = len(pcm) / 32000
        started = time.monotonic()
        if self.audit:
            self.audit('provider_usage', {'provider': self.provider, 'model': self.model,
                'attempt_id': attempt, 'phase': 'submitted', 'input_audio_seconds': seconds,
                'billing_basis': 'submitted_audio_not_invoice'})
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30, connect=10))
        try:
            async with self._http.post(URL, json=body,
                    headers={'Authorization': 'Bearer ' + self.key}) as response:
                if response.status != 200:
                    raise APIConnectionError(f'MiMo ASR HTTP {response.status}')
                result = await response.json()
            choice = result['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise APIConnectionError('MiMo ASR incomplete result')
            text = choice['message']['content']
            if not isinstance(text, str): raise APIConnectionError('MiMo ASR invalid text')
            request_id = str(result.get('id', ''))[:160]
            if self.audit:
                self.audit('asr_final', {'at': time.time(), 'characters': len(text),
                    'request_id': request_id, 'provisional': False})
                self.audit('provider_usage', {'provider': self.provider, 'model': self.model,
                    'attempt_id': attempt, 'phase': 'completed', 'request_id': request_id,
                    'latency_seconds': time.monotonic()-started,
                    'usage': {k:v for k,v in (result.get('usage') or {}).items()
                              if isinstance(v,(int,float))}})
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[stt.SpeechData(language='zh', text=text.strip())] if text.strip() else [],
                request_id=request_id)
        except APIConnectionError: raise
        except Exception as error:
            raise APIConnectionError(f'MiMo ASR failed ({type(error).__name__})') from None
