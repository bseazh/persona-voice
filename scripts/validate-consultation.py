"""Explicit live validation: real DeepSeek calls with labelled fictional survey input."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
origin = 'https://phone.hehaizhao.site'
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def call(path, body=None, expected=200, csrf=True):
    headers = {'Origin': origin, 'X-Consultation': '1'} if csrf else {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(origin + '/api/consult/' + path, data=data, headers=headers)
    try:
        response = opener.open(req, timeout=90)
    except urllib.error.HTTPError as error:
        response = error
    raw = response.read()
    assert response.code == expected, (path, response.code, raw[:300].decode(errors='replace'))
    if 'application/json' in response.headers.get('Content-Type', ''):
        return json.loads(raw)
    return raw

call('sessions', expected=401)
call('create', {'consent': True}, expected=403, csrf=False)
password = (root / 'BigApple输出/consultation-access.txt').read_text(encoding='utf-8').split('管理员密码：', 1)[1].splitlines()[0]
call('login', {'password': password})
call('me')
speech = call('speech')
assert 'key' not in speech and 'encrypted' not in speech
call('speech', {'key': 'invalid', 'workspace': 'llm-w115702gcv6zwvwy'}, expected=400)
if not speech['configured']:
    call('test-tts', {}, expected=400)
assert call('line')['dial_enabled'] is False
created = call('create', {'title': '上线验收 · 虚构睡眠情况（真实模型）', 'consent': True}, expected=201)
sid = created['id']
opening = call('turn', {'id': sid, 'requestId': str(uuid.uuid4())})
assert len(opening['messages']) == 1 and opening['messages'][0]['role'] == 'assistant'
body = {'id': sid, 'requestId': str(uuid.uuid4()), 'text': '愿意开始。以下是验收测试的虚构资料：平时晚上十二点睡，早上七点起，约三十分钟入睡，每晚醒一次，下午容易困，下午四点喝咖啡，睡前看手机一小时，希望更容易入睡。'}
answered = call('turn', body)
assert len(answered['messages']) == 3 and answered['facts']
replayed = call('turn', body)
assert len(replayed['messages']) == 3
closed = call('turn', {'id': sid, 'requestId': str(uuid.uuid4()), 'finish': True})
assert closed['status'] == 'closed' and len(closed['messages']) == 4
call('turn', {'id': sid, 'requestId': str(uuid.uuid4()), 'text': '已经结束'}, expected=409)
call('report', {'id': sid})
archived = call('session?id=' + sid)
assert archived['report_status'] == 'ready'
events = call('events?id=' + sid)
assert sum(e['kind'] == 'turn.completed' for e in events) == 3
assert any(e['kind'] == 'report.generated' for e in events)
output = root / 'BigApple输出/consultation-validation'
output.mkdir(parents=True, exist_ok=True)
for kind in ('report', 'transcript'):
    content = call(f'export?id={sid}&kind={kind}')
    assert b'\n' in content and len(content) > 200
    (output / (kind + '.md')).write_bytes(content)
call('logout', {})
call('session?id=' + sid, expected=401)
print(json.dumps({'passed': True, 'session_id': sid, 'messages': len(archived['messages']), 'events': len(events), 'speech_configured': speech['configured'], 'export_directory': str(output)}, ensure_ascii=False))
