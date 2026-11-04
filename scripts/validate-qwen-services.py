"""Explicit live speech validation on the server using its private .env."""
import contextlib
import hashlib
import http.cookiejar
import io
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid
import wave
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
env = dotenv_values(root / '.env')
key = env['DASHSCOPE_API_KEY']
workspace = env.get('DASHSCOPE_WORKSPACE', '')
origin = 'https://phone.hehaizhao.site'
out = root / 'BigApple输出/qwen-validation'
out.mkdir(parents=True, exist_ok=True)
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
results = {'key_fingerprint': hashlib.sha256(key.encode()).hexdigest()[:12], 'workspace': workspace}

def call(route, body=None, content_type='application/json'):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    req = urllib.request.Request(origin + '/api/consult/' + route, data=body,
        headers={'Origin': origin, 'X-Consultation': '1', 'Content-Type': content_type})
    try:
        response = client.open(req, timeout=75)
    except urllib.error.HTTPError as e:
        response = e
    return response.code, response.read()

def safe(value):
    return str(value).replace(key, '[REDACTED]')[:500]

status, body = call('login', {'password': env['CONSULTATION_ADMIN_PASSWORD']})
assert status == 200, 'Workspace login failed'
status, body = call('speech', {'key': key, 'workspace': workspace})
assert status == 200, 'Speech configuration save failed'
status, body = call('speech')
config = json.loads(body)
assert config['configured'] and 'key' not in config and 'encrypted' not in config
results['saved_to_workspace'] = True
status, body = call('test-tts', {})
results['tts'] = {'http': status}
if status == 200:
    (out / 'tts-test.wav').write_bytes(body)
    with wave.open(io.BytesIO(body)) as wav:
        results['tts'].update(seconds=round(wav.getnframes()/wav.getframerate(), 2), sample_rate=wav.getframerate())
else:
    results['tts']['error'] = safe(json.loads(body).get('error'))
    import dashscope
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            sdk = dashscope.Client(api_key=key, workspace=workspace, region='cn-beijing', timeout=20)
            try:
                with sdk.audio.tts.connect(model='qwen-audio-3.1-tts-flash', voice='longanhuan_v3.1', format='pcm', sample_rate=24000, timeout=20) as session:
                    session.send_text('你好。')
                    session.stop()
                    pcm = b''.join(session.audio_chunks())
                results['tts']['direct_bytes'] = len(pcm)
            finally:
                sdk.close()
    except Exception as e:
        results['tts']['provider_error'] = {'type': type(e).__name__, 'message': safe(e)}

audio = (out / 'asr-reference.wav').read_bytes()
boundary = 'speechtest' + uuid.uuid4().hex
multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="reference.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + audio + f'\r\n--{boundary}--\r\n'.encode())
status, body = call('test-asr', multipart, 'multipart/form-data; boundary=' + boundary)
results['asr'] = {'http': status, 'result': json.loads(body)}
if status != 200:
    import base64
    payload = {'model':'qwen-audio-3.1-asr-flash','input':{'messages':[{'role':'user','content':[{'type':'input_audio','input_audio':{'data':'data:audio/wav;base64,' + base64.b64encode(audio).decode()}}]}]},'parameters':{'format':'wav','sample_rate':'16000'}}
    base = f'https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1' if workspace else 'https://dashscope.aliyuncs.com/api/v1'
    req = urllib.request.Request(base+'/services/aigc/multimodal-generation/generation',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','X-DashScope-SSE':'disable'})
    try:
        response = urllib.request.urlopen(req, timeout=45)
    except urllib.error.HTTPError as e:
        response = e
    data = json.load(response)
    results['asr']['provider'] = {'http':response.code, **{k:safe(data[k]) for k in ('code','message','request_id') if k in data}}
call('logout', {})
(out / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(results, ensure_ascii=False))
