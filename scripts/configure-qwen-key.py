"""Read a shared Qwen key from stdin; never print it. Optional server sync."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--sync-server', action='store_true')
parser.add_argument('--default-gateway', action='store_true')
args = parser.parse_args()
key = sys.stdin.read().strip()
if not 20 <= len(key) <= 512 or any(c.isspace() for c in key):
    raise SystemExit('Invalid key format')
root = Path(__file__).resolve().parents[1]
path = root / '.env'
lines = path.read_text(encoding='utf-8').splitlines()
values = {'DASHSCOPE_API_KEY': key, 'DASHSCOPE_TTS_API_KEY': key}
if args.default_gateway:
    values.update(DASHSCOPE_WORKSPACE='', DASHSCOPE_TTS_WORKSPACE='',
                  QWEN_ASR_URL='https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation')
updated = [line for line in lines if line.split('=', 1)[0] not in values]
updated.extend(name + '=' + value for name, value in values.items())
os.umask(0o077)
new = path.with_suffix('.qwen-new')
new.write_text('\n'.join(updated) + '\n', encoding='utf-8')
new.chmod(0o600)
new.replace(path)
print('Shared Qwen key saved to .env (mode 600); value not printed.')
if args.sync_server:
    result = subprocess.run(['sshpass', '-e', 'ssh', 'ubuntu@134.175.154.244',
                             'python3 /home/ubuntu/Project/persona-voice/scripts/configure-qwen-key.py' + (' --default-gateway' if args.default_gateway else '')],
                            input=key, text=True, check=True)
