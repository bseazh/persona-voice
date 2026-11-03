# SIM to AI voice bridge

Current test roles: dialing SIM 19221659824 (user-supplied number), receiving
phone 15820242347. Android currently reports China Broadnet in slot 1 (SIM 2).
Caller identity on the cellular network comes from that physical SIM.

```text
Receiving phone <-> cellular network <-> Android Voice SIP Agent
    <-> Asterisk TCP 5054 / RTP 10000–10019
    <-> loopback LiveKit SIP <-> self-hosted LiveKit room
    <-> Qwen streaming ASR / DeepSeek / Qwen TTS
```

LiveKit SIP v1.22.0 uses the Tencent Docker mirror of `livekit/sip`, pinned to
digest `sha256:ccca91b38e57b0565d965ee8e7db698f0d7fd1a44a4018c4cacae14eb95bed10`.
It runs under `persona-livekit-sip.service`, uses host networking, and reads
the existing root-only `/etc/persona-livekit/credentials.env`. SIP binds only
to 127.0.0.1:5060; its media range is 20000–20099 and advertised media IP is
127.0.0.1. No new public firewall ports are required. Asterisk uses its separate
127.0.0.1:5062 UDP transport and endpoint `livekit-local`.

The inbound trunk `persona-asterisk-local` accepts only 127.0.0.1/32 and
destination 9000. Dispatch rule `persona-sim-ai` creates a separate `sim-ai-`
room per call and dispatches `persona-voice-agent`. The original echo route
remains available for isolating cellular audio issues. Incoming cellular
takeover remains disabled.

Provision on the server (does not dial):

```sh
sudo python3 scripts/setup-sip-bridge.py
.venv-agent/bin/python scripts/configure-sip-route.py
```

These are explicit infrastructure steps; ordinary GitHub deployments preserve
`/etc/asterisk`, `/etc/persona-livekit`, and Redis routing data. For changed SIP
service YAML, rerun setup then `sudo systemctl restart persona-livekit-sip`.

Before a real call, confirm recipient availability, `adb` gateway readiness,
`pjsip show contacts`, and that no channels are active. After authorization:

```sh
sudo asterisk -rx 'channel originate Local/15820242347@sim-ai-outbound extension s@livekit-ai'
```

The route allows only the current test recipient, uses the existing SIM slot
header, and limits the call to 180 seconds. The AI greets the recipient and
supports natural speech turns/interruption. This command initiates a real,
potentially billable SIM call. Do not run it automatically on deployment.

For a server-only smoke test, generate `BigApple输出/tts-check.wav` using
`scripts/check-tts.py`. Convert it to mono 8 kHz PCM WAV and install it at
`/usr/share/asterisk/sounds/custom/persona-sip-test.wav` (the Debian Asterisk
data directory). Start `scripts/observe-sip-test.py`, then run:

```sh
sudo asterisk -rx 'channel originate Local/s@livekit-ai extension s@livekit-ai-smoke'
```

This plays the fixture into SIP without dialing any phone. The observer prints
test transcripts and audio peak/frame counts; it does not save raw audio.
Use it only for an authorized test session. Check `pjsip show channelstats`
and the SIP/Agent systemd journals as well. A successful server test does not
replace listening on the receiving phone.

## Validation on 2026-11-03

- SIM echo test: recipient confirmed audible beep and own voice echo.
- Server-only SIP test: Chinese fixture transcribed correctly; AI generated
  a relevant reply and Asterisk received return RTP with zero reported loss.
- Authorized real SIM AI test: room `sim-ai-_1000_nWVWzH3HySvH`; two spoken
  questions transcribed and answered. Observer saw 4,500 audio frames per
  direction, peaks 28,123 (phone) and 26,956 (Agent). Asterisk reported zero
  packet loss on both legs during the sample. These are transport/audio
  observations, not a guarantee of subjective latency or interruption quality.
- User subsequently confirmed that the current AI phone experience works well.
- The model answered a time-sensitive product question using stale knowledge.
  The prompt now explicitly discloses the absence of live search; current facts
  still require a future search integration, and prompt text alone cannot
  guarantee factual accuracy.
