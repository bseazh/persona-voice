# Implementation decisions

- Baseline reviewed 2026-10-29: `livekit-examples/outbound-caller-python` commit `608f4c7055c3e3307a98187cfdf74b77eeac8600`.
- The upstream example currently uses LiveKit Agents `~1.0`, `CreateSIPParticipant(wait_until_answered=True)`, Deepgram, Cartesia, GPT-4o, Silero, and `EnglishModel()`.
- Chinese turn detection and exact Deepgram/Cartesia model compatibility remain unverified, so the deployment does not claim P1/P2 readiness.
- FastAPI serves the Next.js static export in production. This keeps one public container and one origin while preserving a normal Next.js development workflow.
- SQLite uses the Python standard library for the narrow MVP data model. Real dispatch and callbacks must be added before real mode can transition beyond validation.
- The server runs on port 5050, within the user-authorized 5049-5055 range, to avoid altering existing Caddy routes and services on ports 80/443/3000.
