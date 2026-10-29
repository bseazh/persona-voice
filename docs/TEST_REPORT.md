# Test report

Generated for the 2026-10-29 P0 deployment. Update this file with command output and redacted IDs after each verification run.

| Area | Status | Evidence |
|---|---|---|
| API validation and mock lifecycle | Passed | 2 pytest cases cover validation, idempotency, lifecycle, masking, and real-call guard |
| Next.js production build | Passed | Next.js 16.4.3, TypeScript and static export completed |
| Dependency audit | Passed | `npm audit --omit=dev`: 0 known vulnerabilities |
| Container health | Passed locally | `/api/health` reports DB ready, real calls false, LiveKit false |
| Browser mock workflow | Passed locally | UI reached `completed`; result explicitly marked simulated |
| Tencent Cloud deployment | Passed | Offline amd64 image running on port 5050; persistent Docker volume created |
| Public HTTPS and DNS | Passed | `https://phone.hehaizhao.site`; Let's Encrypt certificate issued 2026-10-29 |
| Server mock workflow | Passed | `call_ad50056c9ba044b797a2` reached completed through five persisted events |
| LiveKit dispatch | Not executed | Credentials and SIP trunk absent |
| Real handset ring/answer | Not executed | Explicit authorization still required |
| Chinese three-turn conversation | Not executed | P1 not passed |
