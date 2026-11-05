"""Provision private console on the server; no call is made."""
from pathlib import Path
import os
import re
import secrets
import subprocess
import argparse

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-number', help='Add an exact 11-digit recipient after configuring its Asterisk route')
    parser.add_argument('--caller-number', help='Document expected SIM caller; does not change the physical SIM number')
    args = parser.parse_args()
    if args.allow_number and not re.fullmatch(r'[0-9]{11}', args.allow_number):
        parser.error('Recipient must be exactly 11 digits')
    if args.caller_number and not re.fullmatch(r'1[0-9]{10}', args.caller_number):
        parser.error('Caller must be exactly 11 digits')
    assert os.geteuid() == 0, 'Run with sudo'
    assert not run('asterisk', '-rx', 'core show channels concise').strip(), 'Active phone call: wait before installing'
    config = Path('/etc/persona-phone-console.env')
    if not config.exists():
        fd = os.open(config, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write('PHONE_ALLOWED_NUMBERS=15820242347\nPHONE_CONSOLE_PASSWORD=' + secrets.token_urlsafe(32) + '\n')
    if args.allow_number:
        # The installed route may lag the repository; require an explicit source route.
        source = (ROOT / 'ops/asterisk-livekit-extensions.conf').read_text()
        assert f'exten => {args.allow_number},1,' in source, 'No explicit dialplan route for recipient'
        lines = config.read_text().splitlines()
        for index, line in enumerate(lines):
            if line.startswith('PHONE_ALLOWED_NUMBERS='):
                numbers = [n for n in line.split('=', 1)[1].split(',') if n]
                if args.allow_number not in numbers:
                    numbers.append(args.allow_number)
                lines[index] = 'PHONE_ALLOWED_NUMBERS=' + ','.join(numbers)
                break
        else:
            lines.append('PHONE_ALLOWED_NUMBERS=' + args.allow_number)
        config.write_text('\n'.join(lines) + '\n')
    values = dict(line.split('=', 1) for line in config.read_text().splitlines() if '=' in line)
    if args.caller_number:
        values['PHONE_CALLER_NUMBER'] = args.caller_number
    values.setdefault('PHONE_AMI_PASSWORD', secrets.token_hex(32))
    environment = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    values['CONSULTATION_AGENT_SECRET'] = environment['CONSULTATION_AGENT_SECRET']
    config.write_text('\n'.join(key + '=' + value for key, value in values.items()) + '\n')
    config.chmod(0o600)
    settings = run('asterisk', '-rx', 'manager show settings')
    assert '127.0.0.1:5038' in settings, 'AMI must already be enabled on loopback only'
    manager = Path('/etc/asterisk/manager.d/persona-console.conf')
    manager.write_text('[persona-console]\nsecret=' + values['PHONE_AMI_PASSWORD'] + '\ndeny=0.0.0.0/0.0.0.0\npermit=127.0.0.1/255.255.255.255\nread=none\nwrite=originate\n')
    run('chown', 'asterisk:asterisk', str(manager))
    manager.chmod(0o640)
    run('asterisk', '-rx', 'manager reload')
    destination = Path('/opt/persona-phone-console')
    destination.mkdir(exist_ok=True)
    run('install', '-m', '0644', str(ROOT / 'ops/persona-phone-transcripts.conf'), '/etc/tmpfiles.d/persona-phone-transcripts.conf')
    run('systemd-tmpfiles', '--create', '/etc/tmpfiles.d/persona-phone-transcripts.conf')
    for name in ('server.py', 'managed_calls.py', 'index.html', 'app.js', 'style.css'):
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
