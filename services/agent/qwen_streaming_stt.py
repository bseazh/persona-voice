"""Duplex Qwen ASR using the official DashScope websocket SDK."""
import asyncio
import logging
import os
import time

import dashscope
from livekit import rtc
from livekit.agents import APIConnectionError, DEFAULT_API_CONNECT_OPTIONS, stt
from qwen_stt import QwenSTT
from preflight import StablePreflight, preflight_enabled

logger = logging.getLogger(__name__)


class QwenStreamingSTT(QwenSTT):
    def __init__(self, *, audit=None, **kwargs):
        super().__init__(**kwargs)
        self.audit = audit
        self._preflights = set()
        self._speaking = None
        self._capabilities = stt.STTCapabilities(streaming=True, interim_results=True)

    def stream(self, *, language=None, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return QwenStream(stt=self, conn_options=conn_options, sample_rate=16000)

    def set_user_speaking(self, speaking):
        self._speaking = speaking
        for preflight in tuple(self._preflights):
            preflight.set_speaking(speaking)
        if self.audit:
            self.audit('asr_vad_boundary', {'at': time.time(), 'speaking': speaking})


class QwenStream(stt.RecognizeStream):
    async def _run(self):
        client = dashscope.Client(api_key=self._stt.key,
                                 workspace=self._stt.workspace,
                                 region='cn-beijing', timeout=120)
        session = client.audio.asr.recognize(
            model=os.getenv('QWEN_STREAMING_ASR_MODEL', 'qwen-audio-3.1-asr-flash-streaming'),
            format='pcm', sample_rate=16000, timeout=120)
        tasks = []
        def emit_preflight(event):
            self._event_ch.send_nowait(stt.SpeechEvent(
                type=stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
                request_id=event.request_id, alternatives=event.alternatives))
            if self._stt.audit:
                self._stt.audit('asr_preflight', {'at': time.time(), 'characters': len(event.alternatives[0].text),
                    'request_id': event.request_id, 'provisional': True})
        preflight = StablePreflight(emit_preflight)
        self._stt._preflights.add(preflight)
        if self._stt._speaking is True:
            preflight.set_speaking(True)
        try:
            await asyncio.to_thread(session.start)
            logger.info('qwen_streaming_connected', extra={'request_id': session.request_id})

            async def send():
                async for frame in self._input_ch:
                    # A flush boundary must not close the persistent conversation socket.
                    if isinstance(frame, rtc.AudioFrame):
                        await asyncio.to_thread(session.send_audio_frame, bytes(frame.data))
                await asyncio.to_thread(session.stop)

            async def receive():
                results = session.results()
                speaking = False
                while True:
                    result = await asyncio.to_thread(next, results, None)
                    if result is None:
                        break
                    sentence = result.get_sentence() or {}
                    text = sentence.get('text', '').strip()
                    if not text:
                        continue
                    self._mark_provider_progress()
                    if not speaking:
                        self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH))
                        speaking = True
                    final = result.is_sentence_end()
                    event = stt.SpeechEvent(
                        type=stt.SpeechEventType.FINAL_TRANSCRIPT if final else stt.SpeechEventType.INTERIM_TRANSCRIPT,
                        request_id=session.request_id or '',
                        alternatives=[stt.SpeechData(language='zh', text=text,
                            start_time=(sentence.get('begin_time') or 0) / 1000,
                            end_time=(sentence.get('end_time') or 0) / 1000)])
                    if final:
                        preflight.final()
                    self._event_ch.send_nowait(event)
                    if not final and preflight_enabled():
                        preflight.update(text, event)
                    if final:
                        if self._stt.audit:
                            self._stt.audit('asr_final', {'at': time.time(), 'characters': len(text),
                                'request_id': session.request_id or '', 'provisional': False})
                        self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH))
                        speaking = False
                if not self._input_ch.closed:
                    raise APIConnectionError('Qwen ASR stream ended unexpectedly')

            tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # SDK exceptions may contain request payloads; expose only their class.
            raise APIConnectionError(f'Qwen streaming ASR failed ({type(error).__name__})') from None
        finally:
            preflight.close()
            self._stt._preflights.discard(preflight)
            await asyncio.to_thread(session.close)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(client.close)
