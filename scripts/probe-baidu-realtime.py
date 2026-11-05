"""Real Lite API smoke test with locally synthesized speech; no phone call."""
import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import wave
from urllib.parse import urlencode
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'BigApple输出/baidu-lite-validation'
MODEL = 'audio-mini-realtime-near'


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'model': MODEL, 'phone_call': False, 'synthetic_input': True,
              'note': 'Timing ends at API audio receipt, not handset playback.', 'tests': []}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as client:
        async with client.post('https://aip.baidubce.com/oauth/2.0/token', data={
            'grant_type': 'client_credentials', 'client_id': os.environ['BAIDU_API_KEY'],
            'client_secret': os.environ['BAIDU_SECRET_KEY']}) as response:
            auth = await response.json(content_type=None)
            if 'access_token' not in auth:
                report['auth_error'] = auth.get('error', 'unknown')
                report['http_status'] = response.status
                return save(report)
        report['auth_ok'] = True
        url = ('wss://aip.baidubce.com/ws/2.0/speech/v1/realtime?'
               + urlencode({'model': MODEL, 'access_token': auth['access_token']}))
        try:
            async with connect(url, proxy=None, open_timeout=20) as ws:
                async def send_json(value):
                    await ws.send(json.dumps(value, ensure_ascii=False))
                async def receive():
                    msg = await asyncio.wait_for(ws.recv(), 25)
                    if not isinstance(msg, str):
                        raise RuntimeError('WebSocket closed without expected event')
                    return json.loads(msg)
                await send_json({'type': 'session.update', 'session': {
                    'input_audio_transcription': {'model': 'default'},
                    'voice': '8003'}})
                while True:
                    event = await receive()
                    if event['type'] == 'error':
                        report['provider_error'] = event.get('error', {}).get('code', 'unknown')
                        return save(report)
                    if event['type'] == 'session.updated':
                        report['session_config'] = {k: event.get('session', {}).get(k)
                                                   for k in ('model', 'voice', 'input_audio_format', 'output_audio_format', 'turn_detection')}
                        break
                for number, question in enumerate(['请问一天有多少个小时？', '那两天一共有多少个小时？'], 1):
                    aiff = OUT / f'input-{number}.aiff'
                    subprocess.run(['say', '-v', 'Tingting', '-o', str(aiff), question], check=True)
                    pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(aiff),
                                                   '-f', 's16le', '-ar', '16000', '-ac', '1', '-'])
                    row = {'question': question, 'input_seconds': len(pcm)/32000}
                    report['tests'].append(row)
                    end = None
                    stop = None
                    chunks = []
                    async def send_audio():
                        nonlocal end
                        start = time.monotonic()
                        for offset in range(0, len(pcm), 640):
                            await send_json({'type': 'input_audio_buffer.append',
                                               'audio': base64.b64encode(pcm[offset:offset+640]).decode()})
                            await asyncio.sleep(max(0, start + min(offset+640, len(pcm))/32000 - time.monotonic()))
                        end = time.monotonic()
                        while True:
                            await send_json({'type': 'input_audio_buffer.append',
                                               'audio': base64.b64encode(bytes(640)).decode()})
                            await asyncio.sleep(.02)
                    sender = asyncio.create_task(send_audio())
                    try:
                        async with asyncio.timeout(60):
                            while True:
                                e = await receive()
                                kind = e['type']
                                if kind == 'error':
                                    row['error_code'] = e.get('error', {}).get('code', 'unknown')
                                    break
                                if kind == 'input_audio_buffer.speech_stopped': stop = time.monotonic()
                                if kind == 'conversation.item.input_audio_transcription.completed': row['user_transcript'] = e.get('transcript')
                                if kind == 'response.audio.delta':
                                    if not chunks:
                                        now = time.monotonic()
                                        row['input_file_end_to_first_audio_seconds'] = round(now-end, 3) if end else None
                                        row['provider_stop_to_first_audio_seconds'] = round(now-stop, 3) if stop else None
                                    chunks.append(base64.b64decode(e['delta']))
                                if kind == 'response.audio_transcript.done': row['assistant_transcript'] = e.get('transcript')
                                if kind == 'response.done':
                                    row['response_status'] = e.get('response', {}).get('status')
                                    row['usage'] = e.get('response', {}).get('usage')
                                    break
                    finally:
                        sender.cancel()
                        await asyncio.gather(sender, return_exceptions=True)
                    audio = b''.join(chunks)
                    row['output_seconds'] = len(audio)/48000
                    row['audio_nonzero'] = any(audio)
                    if audio:
                        target = OUT / f'reply-{number}.wav'
                        with wave.open(str(target), 'wb') as wav:
                            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(audio)
                        row['audio_file'] = str(target)
                    row['passed'] = bool(audio and row.get('user_transcript') and row.get('assistant_transcript') and row.get('response_status') == 'completed')
        except InvalidStatus as error:
            report['handshake_http_status'] = error.response.status_code
            body = error.response.body.decode(errors='replace')
            for secret in (auth['access_token'], os.environ['BAIDU_API_KEY'], os.environ['BAIDU_SECRET_KEY']):
                body = body.replace(secret, '[REDACTED]')
            report['handshake_detail'] = body[:1500]
        except Exception as error:
            report['failure_type'] = type(error).__name__
    save(report)


def save(report):
    report['passed'] = len(report['tests']) == 2 and all(t.get('passed') for t in report['tests'])
    target = OUT / ('result-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
