# Persona Voice

LiveKit AI outbound calling MVP. The checked-in configuration is deliberately mock-only: it exercises the web, API, validation, idempotency, SQLite persistence, and status polling without placing a telephone call.

## Quick start with Docker

```bash
cp .env.example .env
docker compose up --build -d
curl http://127.0.0.1:5050/api/health
```

Open `http://127.0.0.1:5050`. Stop with `docker compose down` (SQLite data remains in the `persona_voice_data` volume).

Deployed mock workbench: `https://phone.hehaizhao.site`. The server path is `/home/ubuntu/Project/persona-voice`; Caddy terminates HTTPS and proxies to the container on port 5050.

## Local development

Requires Python 3.12 or 3.13 and Node 20+ (the LiveKit agent dependency set is not yet validated on Python 3.14).

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r services/api/requirements-dev.txt
uvicorn app.main:app --app-dir services/api --reload --port 8000
```

In another terminal:

```bash
cd web
npm ci
npm run dev
```

Run tests with `pytest -q`. See `MANUAL_SETUP.md` before enabling a real call. A dispatch being accepted is not evidence that a phone rang or was answered.

## API

- `POST /api/calls` creates a mock or explicitly authorized real call request.
- `GET /api/calls/{call_id}` returns event-driven status.
- `GET /api/calls` lists recent calls with masked numbers.
- `GET /api/health` reports readiness without exposing secrets.

The public deployment remains mock-only. A real call requires every provider credential, an outbound SIP trunk, `ENABLE_REAL_CALLS=true`, an exact E.164 allowlist match, and explicit user confirmation in the UI.

## Tencent Cloud operations

The server cannot currently reach Docker Hub reliably, so deployment uses an offline `linux/amd64` image built on the developer machine. Routine server checks:

```bash
cd /home/ubuntu/Project/persona-voice
sudo docker compose ps
sudo docker compose logs --tail=100
curl http://127.0.0.1:5050/api/health
```
