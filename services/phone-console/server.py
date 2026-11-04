"""Private, SSH-tunnel-only console. Never expose this listener through Caddy."""
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import managed_calls
from urllib.parse import urlsplit, parse_qs

PORT = 5055
LOCK = threading.RLock()
managed_calls.LOCK = LOCK
PENDING_UNTIL = 0.0
ALLOWED = tuple(n for n in os.environ.get('PHONE_ALLOWED_NUMBERS', '').split(',') if n)
CHANNEL = re.compile(r'^Local/[0-9]{11}@console-outbound-[0-9a-f]+;[12]$')


def transcript():
    records = []
    for path in Path('/run/persona-phone-transcripts').glob('sim-ai-*.json'):
        try:
            if path.stat().st_size > 2000000:
                continue
            data = json.loads(path.read_text())
            if time.time() - data['updated_at'] < 1800:
                records.append(data)
        except (OSError, ValueError, KeyError):
            continue
    return max(records, key=lambda record: record['started_at']) if records else {'messages': [], 'active': False, 'room': None}


def cli(command):
    result = subprocess.run(['/usr/sbin/asterisk', '-rx', command], capture_output=True,
                            text=True, timeout=8, cwd='/')
    if result.returncode or 'Unable to connect' in result.stderr:
        raise RuntimeError('Asterisk unavailable')
    return result.stdout


def snapshot():
    channels = [line.split('!')[0] for line in cli('core show channels concise').splitlines() if '!' in line]
    contacts = cli('pjsip show contacts')
    online = any('k60-test/' in line and re.search(r'\bAvail\b', line) for line in contacts.splitlines())
    owned = [channel for channel in channels if CHANNEL.fullmatch(channel)]
    return {'gateway_online': online, 'busy': bool(channels) or time.monotonic() < PENDING_UNTIL,
            'console_call_active': bool(owned), 'pending': time.monotonic() < PENDING_UNTIL and not channels,
            'numbers': ALLOWED, 'max_seconds': 180, '_owned': owned}


def dial(number):
    global PENDING_UNTIL
    if number not in ALLOWED or not re.fullmatch(r'[0-9]{11}', number):
        return 400, {'error': '号码不在允许名单中'}
    with LOCK:
        state = snapshot()
        if state['busy']:
            return 409, {'error': '已有通话或拨号请求，请先等待结束'}
        if not state['gateway_online']:
            return 409, {'error': '安卓网关未注册，先检查手机联网和网关服务'}
        # Hold through the 35s ringing timeout to reject duplicate submissions.
        cli(f'channel originate Local/{number}@console-outbound/n extension s@livekit-ai')
        PENDING_UNTIL = time.monotonic() + 40
    logging.info('console dial submitted ending=%s', number[-4:])
    return 202, {'message': '拨号请求已提交；请查看状态并等待接听'}


def hangup():
    global PENDING_UNTIL
    with LOCK:
        owned = snapshot()['_owned']
        for channel in owned:
            cli('channel request hangup ' + channel)
        if not owned and time.monotonic() < PENDING_UNTIL:
            return 409, {'error': '拨号通道尚未出现，请稍后再次挂断'}
        PENDING_UNTIL = 0
    logging.info('console hangup requested channels=%s', len(owned))
    return 200, {'message': '已请求挂断本控制台通话' if owned else '当前没有本控制台通话'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log headers, credential values or request bodies.
        pass

    def respond(self, status, payload, content_type='application/json; charset=utf-8'):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if status == 401:
            self.send_header('WWW-Authenticate', 'Basic realm="Private phone console", charset="UTF-8"')
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}'):
            self.respond(403, {'error': '仅允许通过本地 SSH 隧道访问'})
            return False
        expected = 'Basic ' + base64.b64encode(('operator:' + os.environ['PHONE_CONSOLE_PASSWORD']).encode()).decode()
        if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            self.respond(401, {'error': '请输入控制台账号和密码'})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        try:
            if self.path == '/api/status':
                with LOCK:
                    state = snapshot()
                state.pop('_owned')
                state['busy'] = state['busy'] or managed_calls.active()
                state['actual_sim'] = 2
                state['caller'] = os.getenv('PHONE_CALLER_NUMBER', '19221659824')
                self.respond(200, state)
            elif self.path.startswith('/api/call?'):
                call_id = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                record = managed_calls.get(call_id)
                self.respond(200 if record else 404, record or {'error': 'Not found'})
            elif self.path == '/api/transcript':
                self.respond(200, transcript())
            elif self.path in ('/', '/app.js', '/style.css'):
                name, mime = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/style.css': ('style.css', 'text/css; charset=utf-8')}[self.path]
                self.respond(200, (Path(__file__).parent / name).read_bytes(), mime)
            else:
                self.respond(404, {'error': 'Not found'})
        except Exception:
            logging.exception('console read failed')
            self.respond(503, {'error': '读取失败，请检查控制台与 Asterisk 服务'})

    def do_POST(self):
        if not self.authorized():
            return
        origin = 'http://' + self.headers.get('Host', '')
        if (self.headers.get('Origin') != origin or self.headers.get('X-Phone-Console') != '1'
                or self.headers.get('Content-Type') != 'application/json'):
            self.respond(403, {'error': '请求来源不被允许'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 2 or size > 1024:
                raise ValueError()
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError()
            if self.path == '/api/dial':
                number = body.get('number')
                if not isinstance(number, str):
                    raise ValueError()
                if body.get('request_id'):
                    status, result = managed_calls.dial(number, body['request_id'], ALLOWED, snapshot)
                else:
                    status, result = (409, {'error': '工作台通话尚未结束'}) if managed_calls.active() else dial(number)
            elif self.path == '/api/hangup':
                status, result = managed_calls.hangup(body['request_id'], cli) if body.get('request_id') else hangup()
            else:
                status, result = 404, {'error': 'Not found'}
            self.respond(status, result)
        except (ValueError, TypeError):
            self.respond(400, {'error': '请求格式无效'})
        except Exception:
            logging.exception('console action failed')
            self.respond(503, {'error': '操作未确认成功，请先查看通话状态，不要重复拨号'})

    def setup(self):
        super().setup()
        self.connection.settimeout(10)


if __name__ == '__main__':
    managed_calls.start_monitor(cli)
    if len(os.environ.get('PHONE_CONSOLE_PASSWORD', '')) < 24 or not ALLOWED or any(not re.fullmatch(r'[0-9]{11}', n) for n in ALLOWED):
        raise SystemExit('Configure a strong password and explicit phone allowlist')
    logging.basicConfig(level=logging.INFO)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
