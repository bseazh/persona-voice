#!/usr/bin/env bash
set -euo pipefail

revision="${1:?revision is required}"
project_dir="/home/ubuntu/Project/persona-voice"

if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid Git revision" >&2
  exit 2
fi

cd "$project_dir"
test -s .env
command -v ffmpeg >/dev/null || { sudo apt-get update && sudo apt-get install -y ffmpeg; }
test -f web/.next/standalone/server.js
test -d web/.next/static

mkdir -p web/.next/standalone/.next
cp -a web/.next/static web/.next/standalone/.next/
if [[ -d web/public ]]; then
  cp -a web/public web/.next/standalone/
fi

python_bin=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    python_bin="$candidate"
    break
  fi
done
test -n "$python_bin"

requirements_hash="$($python_bin -c 'import hashlib; print(hashlib.sha256(open("services/agent/requirements.txt", "rb").read()).hexdigest())')"
installed_hash="$(cat .venv-agent/.requirements.sha256 2>/dev/null || true)"
if [[ ! -x .venv-agent/bin/python || "$requirements_hash" != "$installed_hash" ]]; then
  "$python_bin" -m venv .venv-agent
  .venv-agent/bin/pip install --upgrade pip
  .venv-agent/bin/pip install -r services/agent/requirements.txt
  printf '%s\n' "$requirements_hash" > .venv-agent/.requirements.sha256
fi

.venv-agent/bin/python -m livekit.agents download-files

sudo install -m 0644 ops/persona-voice-web.service /etc/systemd/system/persona-voice-web.service
sudo install -m 0644 ops/persona-voice-agent.service /etc/systemd/system/persona-voice-agent.service
sudo systemctl daemon-reload
sudo systemctl enable persona-voice-web.service persona-voice-agent.service
sudo systemctl restart persona-voice-agent.service
sudo systemctl restart persona-voice-web.service

healthy=false
for _ in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:5050/api/token >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done

if [[ "$healthy" != "true" ]]; then
  sudo systemctl status persona-voice-web.service --no-pager || true
  sudo journalctl -u persona-voice-web.service -n 100 --no-pager || true
  exit 1
fi

sudo systemctl is-active --quiet persona-voice-agent.service
echo "Deployed ${revision} successfully"
