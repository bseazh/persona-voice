# Persona Voice Agent

LiveKit Python Agent for browser-based, real-time Chinese voice conversations.

Pipeline: ElevenLabs `scribe_v2_realtime` → DeepSeek `deepseek-chat` → ElevenLabs `eleven_v4`.

```bash
python3.12 -m venv .venv-agent
source .venv-agent/bin/activate
pip install -r services/agent/requirements.txt
python -m livekit.agents download-files
python services/agent/agent.py dev
```

The process reads provider credentials from the repository root `.env`. Production uses `start` rather than `dev`.
