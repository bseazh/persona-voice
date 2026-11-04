"""DashScope batch ASR; LiveKit supplies VAD-based streaming adaptation."""
import base64
import io
import logging
import os
import re
import time
import wave

import aiohttp
from livekit import rtc
from livekit.agents import APIStatusError, stt

logger = logging.getLogger(__name__)


class QwenSTT(stt.STT):
    def __init__(self, *, key=None, workspace=None):
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self.key = key or os.environ['DASHSCOPE_API_KEY']
        self.workspace = os.getenv('DASHSCOPE_WORKSPACE', '') if workspace is None else workspace
        self.url = ((f'https://{self.workspace}.cn-beijing.maas.aliyuncs.com/api/v1' if self.workspace else 'https://dashscope.aliyuncs.com/api/v1') + '/services/aigc/multimodal-generation/generation') if key else os.environ['QWEN_ASR_URL']

    @property
    def model(self):
        return os.getenv('QWEN_ASR_MODEL', 'qwen-audio-3.1-asr-flash')

    @property
    def provider(self):
        return 'DashScope'

    async def _recognize_impl(self, buffer, *, language, conn_options):
        frame = rtc.combine_audio_frames(buffer)
        resampler = rtc.AudioResampler(frame.sample_rate, 16000, num_channels=frame.num_channels)
        frames = resampler.push(frame) + resampler.flush()
        pcm = b''.join(bytes(item.data) for item in frames)
        if frame.num_channels != 1:
            raise ValueError('Qwen ASR requires mono room audio')
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
        body = {
            'model': self.model,
            'input': {'messages': [{'role': 'user', 'content': [{'type': 'input_audio', 'input_audio': {
                'data': 'data:audio/wav;base64,' + base64.b64encode(output.getvalue()).decode()
            }}]}]},
            'parameters': {'format': 'wav', 'sample_rate': '16000'},
        }
        started = time.monotonic()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as client:
            async with client.post(self.url, json=body, headers={
                'Authorization': f'Bearer {self.key}', 'X-DashScope-SSE': 'disable',
            }) as response:
                if response.status != 200:
                    try:
                        failure = await response.json()
                    except (ValueError, aiohttp.ContentTypeError):
                        failure = {}
                    def identifier(value):
                        return value if isinstance(value, str) and re.fullmatch(r'[\w.:-]{1,160}', value) else None
                    code = identifier(failure.get('code'))
                    reason = identifier(failure.get('message'))
                    request_id = identifier(failure.get('request_id'))
                    if response.status == 400 and 'ASR_RESPONSE_HAVE_NO_WORDS' in (code, reason):
                        # Background noise can pass VAD. This is an empty recognition,
                        # not a broken STT service; let the adapter keep listening.
                        logger.info('qwen_asr_no_speech', extra={'request_id': request_id,
                                    'audio_seconds': len(pcm) / 32000})
                        return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                                              alternatives=[], request_id=request_id or '')
                    logger.error('qwen_asr_failure', extra={'status': response.status,
                                 'provider_code': code, 'provider_reason': reason, 'request_id': request_id})
                    raise APIStatusError(f'Qwen ASR request failed: {code or "unknown"}',
                                         status_code=response.status, request_id=request_id)
                result = await response.json()
        text = result.get('text') or result.get('output', {}).get('text') or result.get('output', {}).get('sentence', {}).get('text', '')
        logger.info('qwen_asr_result', extra={'audio_seconds': len(pcm) / 32000,
                    'latency_seconds': round(time.monotonic() - started, 3), 'text_length': len(text),
                    'request_id': result.get('request_id')})
        return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                              alternatives=[stt.SpeechData(language='zh', text=text)],
                              request_id=result.get('request_id', ''))
