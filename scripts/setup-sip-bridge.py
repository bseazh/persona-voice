"""Run with sudo on Tencent. Add an isolated SIP bridge; never dial a phone."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    subprocess.run(args, check=True)

def main():
    assert os.geteuid() == 0, 'Run with sudo'
    run('install', '-m', '0640', str(ROOT / 'ops/livekit-sip.yaml'), '/etc/persona-livekit/sip.yaml')
    run('install', '-m', '0644', str(ROOT / 'ops/persona-livekit-sip.service'), '/etc/systemd/system/persona-livekit-sip.service')
    for source, target, parent in [
        ('asterisk-livekit-pjsip.conf', 'persona-livekit-pjsip.conf', 'pjsip.conf'),
        ('asterisk-livekit-extensions.conf', 'persona-livekit-extensions.conf', 'extensions.conf'),
    ]:
        run('install', '-o', 'asterisk', '-g', 'asterisk', '-m', '0640', str(ROOT / 'ops' / source), '/etc/asterisk/' + target)
        config = Path('/etc/asterisk') / parent
        original = config.read_text()
        include = '#include "' + target + '"'
        if include not in original:
            backup = config.with_suffix(config.suffix + '.before-livekit')
            if not backup.exists():
                run('cp', '-p', str(config), str(backup))
            config.write_text(original.rstrip() + '\n\n' + include + '\n')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'persona-livekit-sip')
    run('asterisk', '-rx', 'pjsip reload')
    run('asterisk', '-rx', 'dialplan reload')

if __name__ == '__main__':
    main()
