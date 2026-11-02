# Persona Voice

Browser-based, real-time Chinese voice assistant built with LiveKit.

```text
Browser microphone
  ↕ WebRTC
LiveKit Cloud room
  ↕ WebRTC
Python Agent
  ├─ ElevenLabs Scribe v2 Realtime (STT)
  ├─ DeepSeek Chat (LLM)
  └─ ElevenLabs v4 (TTS)
```

This project no longer uses the former mock outbound-call UI, `/api/conversation`, Base64 recording uploads, temporary audio URLs, or SQLite call simulation. SIP and telephone calling are intentionally out of scope for this stage.

## Local development

Requirements: Node 22.22+, Python 3.10–3.14, and a populated repository-root `.env`.

Start the Agent:

```bash
python3.12 -m venv .venv-agent
source .venv-agent/bin/activate
pip install -r services/agent/requirements.txt
python -m livekit.agents download-files
python services/agent/agent.py dev
```

Start the web app in another terminal:

```bash
cd web
npm ci
npm run dev
```

Open `http://127.0.0.1:3000`, enter `VOICE_ACCESS_CODE`, and allow microphone access.

## Environment

Copy `.env.example` to `.env`. Required values are:

- LiveKit Cloud URL, API key, and API secret
- ElevenLabs API key and voice ID
- DeepSeek API key
- a long random `VOICE_ACCESS_CODE` for the public web app

Secrets are server-side only. The browser receives a short-lived token scoped to one random room. The token endpoint is access-code protected and rate limited.

## Production and automatic deployment

The production path is `/home/ubuntu/Project/persona-voice` and the site is `https://phone.hehaizhao.site`.

Every push to `main` runs `.github/workflows/deploy.yml`, which validates the Agent, audits/lints/builds Next.js, synchronizes the release over SSH, installs pinned Agent dependencies when needed, and restarts two systemd units:

- `persona-voice-web.service` — Next.js standalone server on `127.0.0.1:5050`
- `persona-voice-agent.service` — LiveKit Python Agent

Caddy terminates HTTPS and proxies to the Next.js server. The server `.env` is excluded from synchronization and remains in place across deployments.

Useful checks:

```bash
sudo systemctl status persona-voice-web persona-voice-agent
sudo journalctl -u persona-voice-agent -n 100 --no-pager
curl http://127.0.0.1:5050/api/token
```
