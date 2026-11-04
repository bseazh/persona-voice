"""Durable, idempotent AMI origination. AMI and HTTP both remain loopback-only."""
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager

DB = Path(os.getenv('PHONE_STATE_DIR', '/var/lib/persona-phone-console')) / 'calls.sqlite3'
LOCK = threading.RLock()
ACTIVE = ('queued', 'dialing', 'connected', 'uncertain')
CHANNEL = re.compile(r'^Local/[0-9]{11}@console-outbound-[0-9a-f]+;[12]$')


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,number TEXT,state TEXT,reason TEXT,created REAL,updated REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,call_id TEXT,payload TEXT,delivered INTEGER DEFAULT 0)')
    try:
        with db: yield db
    finally: db.close()


def transition(db, call_id, state, reason):
    now = time.time()
    db.execute('UPDATE calls SET state=?,reason=?,updated=? WHERE id=?', (state, reason, now, call_id))
    payload = json.dumps({'call_id': call_id, 'state': state, 'reason': reason, 'at': now})
    db.execute('INSERT INTO events(id,call_id,payload) VALUES(?,?,?)', (str(uuid.uuid4()), call_id, payload))


def get(call_id):
    with connect() as db:
        row = db.execute('SELECT * FROM calls WHERE id=?', (call_id,)).fetchone()
        return dict(row) if row else None


def active():
    with connect() as db:
        return db.execute("SELECT 1 FROM calls WHERE state IN ('queued','dialing','connected','uncertain') LIMIT 1").fetchone() is not None


def ami_originate(number, call_id):
    # Never interpolate browser input into an Asterisk CLI command or shell.
    with socket.create_connection(('127.0.0.1', 5038), timeout=5) as sock:
        stream = sock.makefile('rwb')
        stream.readline()  # AMI greeting
        def action(fields):
            stream.write(('\r\n'.join(k + ': ' + v for k, v in fields) + '\r\n\r\n').encode())
            stream.flush()
            response = {}
            while True:
                line = stream.readline()
                if not line: raise RuntimeError('ami_disconnected')
                if line == b'\r\n':
                    if response: return response
                    continue
                key, _, value = line.decode().partition(':')
                response[key] = value.strip()
        logged = action([('Action', 'Login'), ('Username', 'persona-console'),
                         ('Secret', os.environ['PHONE_AMI_PASSWORD']), ('Events', 'off')])
        if logged.get('Response') != 'Success': raise RuntimeError('ami_login_failed')
        result = action([('Action', 'Originate'), ('ActionID', call_id),
                         ('Channel', f'Local/{number}@console-outbound/n'), ('Context', 'livekit-ai'),
                         ('Exten', 's'), ('Priority', '1'), ('CallerID', '1000'), ('Timeout', '35000'),
                         ('Variable', '__CONSULTATION_ID=' + call_id), ('Async', 'true')])
        if result.get('Response') != 'Success': raise RuntimeError('ami_originate_rejected')


def dial(number, call_id, allowed, snapshot):
    if not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', str(call_id)):
        return 400, {'error': '无效的拨号请求编号'}
    if number not in allowed or not re.fullmatch(r'1[0-9]{10}', str(number)):
        return 400, {'error': '号码不在允许名单中'}
    with LOCK:
        previous = get(call_id)
        if previous:
            if previous['number'] != number: return 409, {'error': '请求编号与号码不一致'}
            return 200, previous  # A retry can never originate a second call.
        state = snapshot()
        if state['busy'] or active(): return 409, {'error': '线路忙，请等待当前电话结束'}
        if not state['gateway_online']: return 409, {'error': '手机网关离线，请先恢复注册'}
        now = time.time()
        with connect() as db:
            db.execute('INSERT INTO calls VALUES(?,?,?,?,?,?)', (call_id, number, 'queued', 'submitted', now, now))
            transition(db, call_id, 'queued', 'submitted')
        try:
            ami_originate(number, call_id)
        except Exception:
            # A timeout may occur after Asterisk accepted the call. Do not redial.
            with connect() as db: transition(db, call_id, 'uncertain', 'originate_result_unknown')
        return 202, get(call_id)


def channels(cli):
    found = {}
    for line in cli('core show channels concise').splitlines():
        fields = line.split('!')
        if not fields or not CHANNEL.fullmatch(fields[0]): continue
        detail = cli('core show channel ' + fields[0])
        match = re.search(r'(?:^|\s)_*CONSULTATION_ID=([0-9a-f-]{36})\b', detail)
        if match:
            found.setdefault(match[1], []).append((fields[0], len(fields) > 4 and fields[4] == 'Up'))
    return found


def hangup(call_id, cli):
    with LOCK:
        record = get(call_id)
        if not record: return 404, {'error': '通话不存在'}
        owned = channels(cli).get(call_id, [])
        if not owned and record['state'] in ACTIVE:
            return 409, {'error': '拨号结果尚未确认，请稍后再试；不会操作其他电话'}
        for channel, _ in owned: cli('channel request hangup ' + channel)
        return 200, {'ok': True}


def monitor_once(cli):
    live = channels(cli)  # Fail closed: an unavailable Asterisk is not an ended call.
    with LOCK, connect() as db:
        for record in db.execute("SELECT * FROM calls WHERE state IN ('queued','dialing','connected','uncertain')").fetchall():
            members = live.get(record['id'], [])
            if members:
                state = 'connected' if any(up for _, up in members) else 'dialing'
                if state != record['state']: transition(db, record['id'], state, state)
            elif record['state'] in ('dialing', 'connected'):
                transition(db, record['id'], 'ended', 'channel_closed')
            elif time.time() - record['created'] > 45:
                transition(db, record['id'], 'failed', 'not_connected')


def deliver():
    with connect() as db:
        rows = db.execute('SELECT * FROM events WHERE delivered=0 ORDER BY rowid LIMIT 20').fetchall()
        for row in rows:
            payload = json.loads(row['payload'])
            payload['event_id'] = row['id']
            req = urllib.request.Request('http://127.0.0.1:5050/api/consult-phone',
                data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + os.environ['CONSULTATION_AGENT_SECRET']})
            try:
                with urllib.request.urlopen(req, timeout=5): pass
            except urllib.error.HTTPError as error:
                if error.code != 404: break  # Deleted consultations must not be resurrected.
            except Exception: break
            db.execute('UPDATE events SET delivered=1 WHERE id=?', (row['id'],))


def start_monitor(cli):
    DB.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect(): pass
    def run():
        while True:
            try: monitor_once(cli)
            except Exception: pass  # Next loop rechecks; never infer success from errors.
            try: deliver()
            except Exception: pass
            time.sleep(2)
    threading.Thread(target=run, daemon=True, name='phone-status').start()
