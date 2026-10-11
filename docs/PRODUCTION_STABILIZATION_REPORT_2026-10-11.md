# FarmCraft stabilization report — 11 October 2026

## Verdict

**PRODUCTION VERIFIED.** The deployed app passed API readiness and safe production sandbox smoke tests, including two independent Azure workers completing real Docker evaluations concurrently. **EVENT READY is not established:** the sustained 100-user API test missed the preset p95 latency target, and the 2,000-game estimate is based on a short engine benchmark rather than a full official workload.

## Deployed system

| Component | Verified state |
| --- | --- |
| Render API | `neural-coliseum-api`, Free, commit `c423006`; `/health` and `/ready` passed; Neon DB, Upstash Redis and private object storage checks all true. |
| Render frontend | `neural-coliseum`, Free, commit `195a24e`; landing and organizer login pages loaded in the browser. |
| Azure VM | Existing `farmcraft-eval-01`, Standard_D2as_v4, 2 vCPU/8 GiB; checkout `c423006`. |
| Evaluators | `farmcraft-worker.service` and `farmcraft-worker@2.service` active. Two independently registered worker IDs, each capacity one. |
| Competition data | Live phase remained SETUP. Two named test teams and sandbox jobs were added for the smoke test; no official phase, scoring rule, or production database reset was performed. |

## Changes and verification

| Severity | Finding and fix | Verification |
| --- | --- | --- |
| P1 | SSE job events could raise `UnboundLocalError` from variable shadowing. | `tests/test_job_events.py`; full pytest passed. |
| P1 | Temporary heartbeat/API faults could log out valid teams or show unreadable errors. Session restore retries, heartbeat clamping, and error formatting were corrected. | Session tests, frontend Node tests and live API flows. |
| P1 | Concurrent initial `competition_state` creation could cause HTTP 500. Added serialized initialization and a PostgreSQL schema initialization lock. | Regression test and fresh 10–100 user isolated runs. |
| P1 | Worker registration defaulted to capacity two even for a one-game worker. Registration now sends and stores configured capacity. | `tests/test_remote_workers.py`; both live worker records were set to capacity one. |
| P1 | Round 1 could fail in the API container because the evaluator VERSION file was absent. Uses configured evaluator version. | Isolated real Docker Round 1 opening and complete two-round smoke. |
| P2 | Replay frame reads repeatedly loaded full JSON. Added a versioned compact playback bundle with gzip and local seeking at fixed 60 ms per turn (10×). Restricted replay endpoints by ownership/competition visibility. | Playback and access tests; live owner playback succeeded, cross-team access returned 404. |
| P2 | Bot Lab made duplicate dashboard reads; API pool was too small for load. Removed duplicate fetch and raised the configured DB pool to 6+4. | Frontend build/tests and sustained API load. |

Full backend suite after final worker-capacity fix: **91 passed**, three deprecation warnings. Frontend ESLint, production Vite build and five Node tests passed before deployment. The two-round isolated HTTP smoke completed real official evaluation, qualification, tournament seeding, an 8-game Round 2 bracket and persisted a champion. Separate real sandbox/official smoke covered cancellation, replay, cross-team isolation, and Docker cleanup.

## Worker and replay performance

The existing VM completed eight real Docker games at each concurrency level, with zero failures. One concurrent game achieved **15.17 games/min**; two achieved **18.93** (+24.8%). Three achieved 18.94 and four 19.34 while saturating the two vCPUs and increasing per-game latency. Two independently registered one-game workers were deployed. See [WORKER_BENCHMARK_2026-10-10.md](WORKER_BENCHMARK_2026-10-10.md) for CPU, memory, runtime and limitations. An idealized 2,000-game Round 1 would take about **106 minutes** at the short-run two-worker rate, or about **141 minutes** with 25% reserve; that excludes upload, queue and Round 2 time and requires a sustained official workload to validate.

A representative 720-step replay bundle was built in **0.388 s**, with 13.55 MB raw data compressed to **221,690 bytes**. The prior single-frame read measured **0.534 s per request**. Playback now fetches one bundle and seeks locally instead of making a request per turn. Automated frontend tests checked the 60 ms fixed interval and controls; browser memory and visual replay rendering were not instrumented.

## Isolated API load

All runs used the local isolated stack and fake simulation jobs. They measure API admission and dashboard traffic, **not 100 simultaneous real Docker evaluations**. Invalid runs caused by accumulated test registrations and an early API readiness race were discarded and rerun from fresh isolated state.

| Users | Requests | Unexpected errors | p95 | p99 |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 339 | 0 | 440 ms | 1,200 ms |
| 25 | 853 | 0 | 440 ms | 830 ms |
| 50 | 1,278 | 0 | 1,600 ms | 2,600 ms |
| 75 | 1,417 | 0 | 3,000 ms | 3,500 ms |
| 100 (45 s) | 1,420 | 0 | 3,100 ms | 3,800 ms |
| 100 (120 s, after optimization) | 4,505 | 0 | 2,700 ms | 3,900 ms |

The sustained 100-user run reached **37.7 requests/s**, p50 **1,200 ms** and **0 errors**. A spot sample showed API CPU 132.5%, API RAM 93.9 MiB, PostgreSQL CPU 18%, DB RAM 77.4 MiB and 15 DB connections; the fake queue showed 92 queued, two running, 31 completed. At 100 users, p95 **missed** the preset <2 s target; p99 and error targets passed. A 120-user spectator-only read test generated 1,610 requests in 30 s, zero errors, p95 150 ms and p99 230 ms. Queue latency and real-worker throughput were measured separately; no claim of full event capacity follows from the fake load.

## Live production smoke

Two authorized test teams submitted two sandbox jobs through the live API. Both completed on the existing Azure VM with one attempt and overlapping execution windows. Admin job lookup attributed one to each worker. Both replays were retrievable by their owners; a cross-team replay request returned 404. Worker heartbeats were fresh and independent when inspected. The live test did not change official competition phase or submit official jobs.

Browser checks confirmed the deployed landing page and organizer login page render. A full visual pass through authenticated contestant tabs, desktop/mobile layouts and 10× replay controls on the deployed frontend was not completed; the HTTP smoke and automated tests cover those underlying flows. The local isolated full tournament covered official workflow without altering live competition data.

## Safety and remaining work

The replay endpoints now enforce ownership and hide restricted official replays. Worker claim/result tests cover lease recovery, cancellation and duplicate completion; live smoke found no duplicate results. The production event should still run a longer representative official-job soak with monitoring, measure queue wait under realistic submissions, and repeat a browser walkthrough for all authenticated tabs and mobile widths. The short VM benchmark and API p95 miss prevent an EVENT READY claim.

No billable resources were added, no competition rule was changed, and no production data was reset. Existing local `azure-workers/manage.ps1.bak` remains untracked and untouched.

## Git and rollback

The deployed backend and VM code commit is **`c423006`**. The baseline tag `farmcraft-before-stabilization-20261010` points to `6810aea`. The Render static site is at `195a24e` because the last code commit changed only backend and worker code.

For a code rollback, deploy a **new revert commit** on `azure-staging-deployment` after preserving current work; do not force-push or reset the production branch. Redeploy the chosen commit from the Render Dashboard/API, then update `/opt/farmcraft` on the Azure VM to the matching commit after active jobs drain. Stop and disable `farmcraft-worker@2.service` only if reverting to the one-worker configuration. Keep the original worker active and verify `/ready`, worker heartbeats and a sandbox job afterward. The schema changes are additive; keep the database at its current state and do not delete submissions, replays or team records. Historical rollback reference: `farmcraft-before-stabilization-20261010` (`6810aea`), but use a compatible commit pair for API/frontend/worker rather than blindly deploying the old tag.
