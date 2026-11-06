"""Retrieve an existing cloud library key through authenticated official ve CLI.

No library creation, paid purchase, key printing or automatic upload.
Writes only the selected library's configuration into the ignored project .env.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def call(action, body):
    proc = subprocess.run(['ve', 'vikingdb', action, '--force', '--version', '2025-06-09',
        '--method', 'POST', '--region', 'cn-beijing', '--endpoint', 'vikingdb.cn-beijing.volcengineapi.com',
        '--body', json.dumps(body)], capture_output=True, text=True, timeout=40)
    if proc.returncode:
        raise RuntimeError('CLI request failed; check ve login and library permission (details withheld)')
    data = json.loads(proc.stdout)
    if data.get('ResponseMetadata', {}).get('Error'):
        raise RuntimeError('Cloud rejected library access (details withheld)')
    return data['Result']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resource-id', required=True)
    parser.add_argument('--user-id', default='default')
    parser.add_argument('--uri', default='viking://resources/persona_voice_procurement_demo')
    args = parser.parse_args()
    if not re.fullmatch(r'ov-[a-zA-Z0-9_-]+', args.resource_id):
        raise ValueError('Invalid library ResourceID')
    if not re.fullmatch(r'viking://resources/[a-zA-Z0-9_/-]+', args.uri):
        raise ValueError('Specify a dedicated public demo resource directory')
    info = call('GetOpenVikingCollection', {'ResourceID': args.resource_id})
    if info.get('Status') != 'READY':
        raise RuntimeError('Library is not READY')
    result = call('AccessOpenVikingApiKey', {'ResourceID': args.resource_id, 'UserID': args.user_id})
    key = result.get('ApiKey')
    if not isinstance(key, str) or not key or any(c in key for c in '\r\n'):
        raise RuntimeError('No valid API key returned')
    target = ROOT/'.env'
    original = target.read_text(encoding='utf-8') if target.exists() else ''
    updates = {'OPENVIKING_API_KEY': key, 'OPENVIKING_RESOURCE_ID': args.resource_id,
               'OPENVIKING_PROCUREMENT_URI': args.uri}
    lines = [line for line in original.splitlines() if line.split('=',1)[0] not in updates]
    lines.extend(f'{name}={json.dumps(value)}' for name,value in updates.items())
    target.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    os.chmod(target, 0o600)
    print('Saved selected library configuration to project .env; key not displayed. Server sync and resource upload are separate steps.')

if __name__ == '__main__':
    main()
