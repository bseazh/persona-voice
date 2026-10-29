# Real-call setup checklist

The deployment is intentionally unable to place a real call. Complete every item below before changing `ENABLE_REAL_CALLS`.

1. Create a LiveKit Cloud project and store its WSS URL, API key, and API secret in a server-only `.env.local` file.
2. In Twilio, buy a voice-capable number, enable the destination geography, and verify the test handset when using a trial account.
3. Create an Elastic SIP Trunk, configure its Termination URI and Credential List, and associate the permitted caller ID/number.
4. Create a LiveKit outbound SIP trunk using those Twilio credentials. Verify it with `lk sip outbound list` and store the resulting `ST_...` ID.
5. Create provider keys for OpenAI, Deepgram, and Cartesia. Verify the selected Chinese STT model and TTS model/voice against current provider documentation; plugin availability alone is not proof of Chinese support.
6. Put exactly one owner-controlled, consented E.164 test number in `ALLOWED_DESTINATION_NUMBERS`. Keep recording and transcript storage disabled.
7. Install the `lk` CLI and run the worker in a private terminal. Confirm all preflight checks without printing secrets.
8. Only after the owner explicitly requests the test: set `ENABLE_REAL_CALLS=true`, submit one confirmed call, answer the handset, and record the redacted dispatch ID, room ID, SIP status, and actual conversation result.

Do not expose a real-call API anonymously on a public IP. Add authentication, CSRF protection, rate limits, and a spend cap first. Do not treat HTTP 202, dispatch acceptance, or `CreateSIPParticipant` invocation as proof that a telephone was answered.

