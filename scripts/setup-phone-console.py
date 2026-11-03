"""Provision private console on the server; no call is made."""
from pathlib import Path
import os
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

def main():
    assert os.geteuid() == 0, 'Run with sudo'
    assert not run('asterisk', '-rx', 'core show channels concise').strip(), 'Active phone call: wait before installing'
    config = Path('/etc/persona-phone-console.env')
    if not config.exists():
        fd = os.open(config, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write('PHONE_ALLOWED_NUMBERS=15820242347\nPHONE_CONSOLE_PASSWORD=' + secrets.token_urlsafe(32) + '\n')
    destination = Path('/opt/persona-phone-console')
    destination.mkdir(exist_ok=True)
    for name in ('server.py', 'index.html', 'app.js', 'style.css'):
        run('install', '-m', '0644', str(ROOT / 'services/phone-console' / name), str(destination / name))
    run('install', '-m', '0644', str(ROOT / 'ops/persona-phone-console.service'), '/etc/systemd/system/persona-phone-console.service')
    run('install', '-o', 'asterisk', '-g', 'asterisk', '-m', '0640', str(ROOT / 'ops/asterisk-livekit-extensions.conf'), '/etc/asterisk/persona-livekit-extensions.conf')
    run('asterisk', '-rx', 'dialplan reload')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'persona-phone-console')
    run('systemctl', 'restart', 'persona-phone-console')
    print('Private console installed on 127.0.0.1:5055. No call made. Password remains in protected server config.')

if __name__ == '__main__':
    main()
