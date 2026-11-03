# Tencent LiveKit deployment

The current single-node SFU runs on 134.175.154.244 (Guangzhou), using the
official LiveKit 1.13.11 Linux amd64 release. SHA-256 of its tarball:
`1e9ee90ca301e1842b2887fc77cb122759756a9c8aeb4334ee91de3325ec43fb`.

Browser and Agent use `wss://phone.hehaizhao.site/livekit`. Caddy strips
`/livekit` and proxies HTTP/WebSocket to port 7880. Port 7880 is not allowed
through the Lighthouse firewall; clients use TLS on 443. RTC uses UDP 5053
with TCP 5052 as fallback. No TURN/TLS service is configured yet; networks
that block both media ports need an additional TURN deployment.

Services: `persona-livekit`, `redis-server`, `persona-voice-agent`,
`persona-voice-web`, `caddy`. Redis is bound to loopback only.

LiveKit config and generated keys live in `/etc/persona-livekit`, outside
the GitHub rsync deployment directory. Local and server `.env` use the
self-hosted URL and keypair. API secrets are never committed.
Old server `.env` and Caddy settings are protected files in that directory.
Agent idle pool is reduced to one process for the 4 GB server.

Infrastructure provisioning is explicit, not run on every application push:
install the verified binary to `/usr/local/bin/livekit-server`, then run
`sudo python3 scripts/setup-selfhost.py`; `--activate` updates only LiveKit
settings in the server `.env`. Restart Agent and web after activation.
Normal GitHub pushes still build, sync and restart the web and Agent;
they preserve `.env`, the SFU, Redis data, and system configuration.

Validation:

- `curl --fail https://phone.hehaizhao.site/livekit/` returns `OK`.
- `.venv-agent/bin/python scripts/smoke-realtime.py` checks two spoken
  turns, non-silent reply audio, partial transcripts, and interruption.
- `.venv-agent/bin/python scripts/check-tts.py` checks synthesis separately.
- A browser test must also verify mic publication and remote playback:
  server-side testing alone does not validate a user's network/device.

SIM follow-up: K60 Pro uses SIM slot 1 (SIM 2, the only active SIM reported
after the latest swap: China Broadnet/sub3), Voice SIP Agent, Shizuku,
SIP TCP 5054 and Asterisk RTP UDP 10000–10019. These are independent of
LiveKit media ports. First validate an audible echo in both directions;
then test the LiveKit SIP bridge and voice Agent (see `ops/SIM_AI.md`).
SIP registration alone is not proof that cellular audio works.
Latest dialing SIM number supplied by the user is 19221659824; the actual
caller number comes from the physical SIM, not an overridden SIP caller ID.
Latest recipient and gateway allowed prefix are 13660199577. Both the
gateway default SIM and Asterisk X-VSA-SIMSLOT must use slot 1.
Confirm availability before resuming manual listening tests. Inbound
takeover stays disabled. This configuration change does not initiate a call.
