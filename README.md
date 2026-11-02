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
# 千问 ASR 配置

录音输入和 LiveKit Agent 识别均使用 `qwen-audio-3.1-asr-flash`，需要在项目 `.env` 设置 `DASHSCOPE_API_KEY`、`QWEN_ASR_URL`、`QWEN_ASR_MODEL`。
浏览器录音由服务器 FFmpeg 转为 16kHz 单声道 WAV；Agent 使用 LiveKit 官方 VAD StreamAdapter 按句调用同一 HTTP 接口。这是说完一句后识别，并非逐字流式 ASR。
部署服务器必须安装 FFmpeg。密钥只保存在本地/服务器 `.env`，不可提交。
TTS 仍使用 ElevenLabs；ASR 更换不会恢复 ElevenLabs 已耗尽的 TTS 额度。
