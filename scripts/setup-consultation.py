"""Run as ubuntu on the server once; preserves existing secrets and application data."""
import os
from pathlib import Path
import secrets
import subprocess

root = Path(__file__).resolve().parents[1]
env_path = root / '.env'
lines = env_path.read_text(encoding='utf-8').splitlines()
values = dict(line.split('=', 1) for line in lines if '=' in line and not line.startswith('#'))

def sql(statement):
    result = subprocess.run(['sudo', '-u', 'postgres', 'psql', '-v', 'ON_ERROR_STOP=1', '-tA'], input=statement, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('PostgreSQL provisioning failed; inspect database service locally')
    return result.stdout.strip()

url = values.get('CONSULTATION_DATABASE_URL')
if not url:
    if sql("SELECT 1 FROM pg_roles WHERE rolname='persona_consult'"):
        raise RuntimeError('Existing database role found without URL; recover credentials before proceeding')
    password = secrets.token_hex(24)
    sql(f"CREATE ROLE persona_consult LOGIN PASSWORD '{password}'")
    sql('CREATE DATABASE persona_consult OWNER persona_consult')
    values['CONSULTATION_DATABASE_URL'] = f'postgresql://persona_consult:{password}@127.0.0.1:5432/persona_consult'
values.setdefault('CONSULTATION_ADMIN_PASSWORD', secrets.token_urlsafe(30))
values.setdefault('CONSULTATION_ENCRYPTION_KEY', secrets.token_hex(32))
values['CONSULTATION_PUBLIC_ORIGIN'] = 'https://phone.hehaizhao.site'
values['PERSONA_PROJECT_ROOT'] = str(root)
phone = subprocess.run(['sudo', 'cat', '/etc/persona-phone-console.env'], capture_output=True, text=True)
if phone.returncode == 0:
    phone_values = dict(line.split('=', 1) for line in phone.stdout.splitlines() if '=' in line and not line.startswith('#'))
    if phone_values.get('PHONE_CONSOLE_PASSWORD'):
        values['PHONE_CONSOLE_PASSWORD'] = phone_values['PHONE_CONSOLE_PASSWORD']
keys = {'CONSULTATION_DATABASE_URL', 'CONSULTATION_ADMIN_PASSWORD', 'CONSULTATION_ENCRYPTION_KEY', 'CONSULTATION_PUBLIC_ORIGIN', 'PERSONA_PROJECT_ROOT', 'PHONE_CONSOLE_PASSWORD'}
output = [line for line in lines if line.split('=', 1)[0] not in keys]
output.extend(key + '=' + values[key] for key in sorted(keys) if key in values)
os.umask(0o077)
temporary = env_path.with_suffix('.consultation-new')
temporary.write_text('\n'.join(output) + '\n', encoding='utf-8')
temporary.chmod(0o600)
temporary.replace(env_path)
artifact = root / 'BigApple输出/consultation-access.txt'
artifact.parent.mkdir(parents=True, exist_ok=True)
artifact.write_text('公网工作台：https://phone.hehaizhao.site/consult\n管理员密码：' + values['CONSULTATION_ADMIN_PASSWORD'] + '\n\n登录后点击「语音配置 · 填写 Key」，输入北京业务空间及共用千问 Key，再分别测试 ASR、TTS。\n此文件包含管理凭据，请勿提交 Git 或转发。\n', encoding='utf-8')
artifact.chmod(0o600)
print('Consultation database and private environment configured. No credentials printed.')
