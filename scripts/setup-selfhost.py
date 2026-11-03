"""Run on the deployment host with sudo; secrets never go to stdout."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

ROOT = Path('/home/ubuntu/Project/persona-voice')
CONFIG = Path('/etc/persona-livekit')


def protected_write(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(content)
    os.chmod(path, 0o600)


def replace_env(path, updates):
    content = path.read_text()
    backup = CONFIG / (path.name.lstrip('.') + '.before-selfhost')
    if not backup.exists():
        protected_write(backup, content)
    lines = [line for line in content.splitlines() if line.split('=', 1)[0] not in updates]
    lines.extend(f'{key}={value}' for key, value in updates.items())
    protected_write(path, '\n'.join(lines) + '\n')
    shutil.chown(path, user='ubuntu', group='ubuntu')


def main():
    assert os.geteuid() == 0, 'Run with sudo'
    CONFIG.mkdir(mode=0o750, exist_ok=True)
    shutil.chown(CONFIG, user='root', group='ubuntu')
    credentials = CONFIG / 'credentials.env'
    if not credentials.exists():
        protected_write(credentials, f'LIVEKIT_API_KEY=APIs{secrets.token_hex(10)}\nLIVEKIT_API_SECRET={secrets.token_urlsafe(48)}\n')
    values = dict(line.split('=', 1) for line in credentials.read_text().splitlines())
    if '--activate' in sys.argv:
        replace_env(ROOT / '.env', {**values, 'LIVEKIT_URL': 'wss://phone.hehaizhao.site/livekit', 'LIVEKIT_AGENT_IDLE_PROCESSES': '1'})
        print('Updated LiveKit credentials and URL; ASR/TTS credentials unchanged')
        return
    template = (ROOT / 'ops/livekit.yaml.example').read_text()
    config = CONFIG / 'livekit.yaml'
    protected_write(config, template.replace('REPLACE_API_KEY', values['LIVEKIT_API_KEY']).replace('REPLACE_API_SECRET', values['LIVEKIT_API_SECRET']))
    shutil.chown(config, user='root', group='ubuntu')
    os.chmod(config, 0o640)
    caddy = Path('/etc/caddy/Caddyfile')
    original = caddy.read_text()
    backup = CONFIG / 'Caddyfile.before-selfhost'
    if not backup.exists():
        protected_write(backup, original)
    old = 'phone.hehaizhao.site {\n\treverse_proxy 127.0.0.1:5050\n}'
    new = '''phone.hehaizhao.site {
    handle_path /livekit/* {
        reverse_proxy 127.0.0.1:7880
    }
    handle {
        reverse_proxy 127.0.0.1:5050
    }
}'''
    if old in original:
        candidate = CONFIG / 'Caddyfile.candidate'
        protected_write(candidate, original.replace(old, new, 1))
        subprocess.run(['caddy', 'validate', '--config', str(candidate), '--adapter', 'caddyfile'], check=True)
        caddy.write_text(candidate.read_text())
    elif 'handle_path /livekit/*' not in original:
        raise RuntimeError('Unexpected Caddy config; manual review required')
    elif 'reverse_proxy 127.0.0.1:5051' in original:
        candidate = CONFIG / 'Caddyfile.candidate'
        protected_write(candidate, original.replace('reverse_proxy 127.0.0.1:5051', 'reverse_proxy 127.0.0.1:7880'))
        subprocess.run(['caddy', 'validate', '--config', str(candidate), '--adapter', 'caddyfile'], check=True)
        caddy.write_text(candidate.read_text())
    subprocess.run(['install', '-m', '0644', str(ROOT / 'ops/persona-livekit.service'), '/etc/systemd/system/persona-livekit.service'], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'redis-server', 'persona-livekit'], check=True)
    subprocess.run(['systemctl', 'restart', 'persona-livekit'], check=True)
    subprocess.run(['systemctl', 'reload', 'caddy'], check=True)


if __name__ == '__main__':
    main()
