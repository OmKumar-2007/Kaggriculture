# FarmCraft end-to-end test report — 10 October 2026

## Scope and environment

Tests used the current checkout and a new, isolated Compose project (`farmcraft-e2e-20261010`) on port 18000, with separate PostgreSQL, Redis, and object storage. The existing application on port 8000 was checked read-only and its competition database was not changed. The isolated worker and containers were stopped after testing; their Docker volumes were retained for inspection.

## Results

| Area | Result | Evidence |
| --- | --- | --- |
| Python automated suite | Pass | `python -m pytest -q`: 68 passed, 3 dependency deprecation warnings |
| Frontend static checks | Pass | `npm run lint` and `npm run build` in `frontend/` |
| Docker evaluator image | Pass | Built `nitw-farm-ai-evaluator:2026.10.09` from the local engine source |
| API, database, Redis, storage | Pass | Isolated and main `/ready` checks returned all true |
| Reference setup | Pass | Five reference bots uploaded, evaluated with the real Docker engine, selected; Round 1 opened |
| Participant identity and permissions | Pass | Registration, session, recovery, logout, duplicate name and cross-team denial |
| Bot Lab and sandbox | Pass | Valid and invalid source upload, real sandbox match, result and replay |
| Official Round 1 | Pass | Two real 20-game submissions completed; scores and leaderboard updated |
| Admin Control Center | Pass | Session revoke, suspend/block/unblock, settings, worker pause/resume, cancellation, pipeline and audit checks |
| Two-round competition | Pass | Qualification close, failure adjudication, top-2 finalization, bracket lock, real tournament and champion persistence |
| Matchmaking and winner display | Pass | One pairing completed with eight real game legs; tie resolved by higher qualification seed; winner, replay links and tie-break shown in browser |
| Browser navigation | Pass | All 8 contestant tabs and 13 admin tabs rendered; no JavaScript exceptions, HTTP 500 responses, or broken images observed |
| Responsive rendering | Pass | Desktop contestant/admin and mobile entry screenshots inspected in `load_tests/data/` |
| Local running application | Pass | Port 8000 remained up; API, PostgreSQL and Redis containers healthy after test shutdown |

## Findings and corrections

- Several existing smoke scripts assumed registration automatically queued an official job and used an old eight-game expectation. The identity smoke was updated for explicit submission and the current 20-game format.
- The real remote evaluation smoke fixture lacked the frozen submission hash and reference pool required by the current official job contract. The fixture was updated and the real evaluator smoke passed.
- Fake simulation is correctly rejected for Round 1 and Round 2 competition jobs. The load-test instructions now say to use a real worker for competition testing.
- Browser screenshots must wait for entrance animations to finish. With that wait, the admin overview and champion screen were readable.

## Limits

- The 60-agent/100-user capacity rehearsal was not rerun. This was a functional end-to-end pass, not a throughput claim. During the tournament, the isolated admin monitor reported host CPU at 100% and RAM near 98%, so concurrent capacity requires a separate measured load run.
- Render, Neon, Upstash, and an external evaluator laptop were not configured in this local test; cloud deployment and remote connectivity remain unverified.
- The `real_pipeline_smoke.py` legacy script was not run in this completed tournament state. Its overlapping real sandbox/official/cancellation paths were covered by `remote_real_smoke.py`, the identity smoke, and Control Center smoke.
