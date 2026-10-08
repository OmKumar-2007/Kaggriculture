# FarmCraft laptop hosting validation — 8 October 2026

## Scope and architecture

The existing React/Vite frontend, FastAPI backend, PostgreSQL store, Redis/RQ queue, and Kaggriculture evaluator were retained. The local event stack now serves the frontend and API on one web port, keeps database and Redis on loopback, and uses a trusted host worker to launch one restricted Docker evaluator per match. Tournament game rules and scoring were left intact. The admin area now reads real host, worker, queue, and participant session telemetry.

This report records checks run on the organizer laptop: 4 logical CPUs, 7.65 GiB RAM, Docker Desktop/WSL2. The isolated rehearsal stack uses separate PostgreSQL and Redis volumes, an upload directory under `load_tests/data`, and web port 18000. Fake evaluation is enabled only for explicit rehearsal runs; the real evaluator checks use a worker with that mode disabled.

## Verification performed

| Check | Result |
|---|---|
| Python automated suite | `python -m pytest -q tests`: **55 passed**, 3 upstream deprecation warnings. Includes cancellation/result races, team state and settings, atomic tournament registration, callback failure propagation, leaderboard preservation, deterministic persistent-tie resolution, legacy tournament error reconciliation, worker and queue behavior, a real tournament replay, and an actual infinite-loop bot killed by Docker timeout with container cleanup. |
| Frontend | `npm run build` and `npm run lint`: both passed. |
| Compose files | Production configuration parsed with placeholder secrets; isolated configuration parsed and started. The production file intentionally refuses to parse without `ADMIN_PASSWORD_HASH`, `ADMIN_SESSION_SECRET`, and `POSTGRES_PASSWORD`; `start-server.ps1` creates them on first start. |
| Isolated HTTP flow | `/ready`, team sign-in, private-route authorization, CSRF rejection, `main.py` upload, sandbox and official queueing, job completion, leaderboard update all passed. Home `/register` also returned a queued official job and its result appeared on the leaderboard. |
| Admin | Anonymous metrics access returned 401; organizer login, metrics, devices, and telemetry returned 200. The Control Center smoke exercised team session revocation, suspension/blocking, worker pause/resume, queued and running cancellation, event settings, pipeline, and audit. The Evaluation Pipeline table, actual stage values, trends, filters and mobile layout were inspected in a browser. |
| Real evaluator | Built evaluator image and completed a full 720-turn sandbox match (score 3386), an eight-game official evaluation (rating 834.15), and a contestant runtime failure that left the prior leaderboard score intact. Cancelling an infinite-loop agent while its container was running produced a cancelled job and zero orphan evaluator containers. This flow was repeated on the final isolated build with the same score and rating; its replay frame was retrievable. |

The latest isolated identity smoke additionally confirmed that empty uploads return HTTP 400 for Bot Lab and tournament registration, and a duplicate tournament registration returns HTTP 409 without creating another version. The latest browser review covered participant and admin rendering at 390, 768, 1024, 1366 and 1920 pixels; each had `documentElement.scrollWidth <= innerWidth`. The admin table intentionally scrolls within its own container on mobile. Frontend build, lint and `git diff --check` passed after the changes. See [FRONTEND_TOURNAMENT_PIPELINE_AUDIT.md](FRONTEND_TOURNAMENT_PIPELINE_AUDIT.md) for the implementation audit and remaining tournament policy limitation.

## Live recheck after organizer credential rotation

The organizer password and signing secret were rotated on 8 October 2026; the plaintext password is given only in the conversation handoff, not in this repository. Browser login to `/admin` succeeded. The home sign-in screen, public event, roster, tournament and leaderboard endpoints, teams, workers, queues, tournament controls, match view, and pipeline view loaded. `health-check.ps1` returned ready with database, Redis and storage healthy; two worker processes were idle and all queues were open. The original **3 teams, 4 submissions and 8 jobs** were retained. The existing bracket was already in `error` after ten exact-tie replays; its stale running match is now displayed as aborted, and the historical job was corrected from completed to failed with one reconciliation event. The old result was preserved. A newly launched bracket uses the documented seeded draw after ten exact ties. No new bracket was started during this check.

The admin dashboard intermittently reports **degraded** because host RAM has exceeded 90%. C: had about **1.0 GiB free** during this check, despite ample space on D:. Rebuildable Docker build cache was pruned, but the Windows free-space figure did not materially rise because Docker's virtual disk did not shrink. Free C: space and reduce memory pressure before running a live event or a larger batch of evaluations.

The real pipeline smoke ran with `LOAD_TEST_FAKE_SIMULATION=0` in the isolated worker. Its admin job detail recorded container, match, scoring, and result stages. `python load_tests/control_center_smoke.py` was run separately with the isolated fake worker; the two modes were never enabled together on the same worker. Isolated services were shut down with volumes retained after testing.

## Load measurements

The Locust `contestants` profile signs test teams in, uploads a bot, creates sandbox/official jobs, polls job status, refreshes the leaderboard, and sends heartbeats. Its evaluation worker returns **fake results** so these measurements are for HTTP, persistence, queueing, and dashboard behavior. They do not demonstrate capacity for 100 real concurrent games.

| Run | Requests | HTTP failures | Throughput | Aggregate p50 / p95 / p99 |
|---|---:|---:|---:|---:|
| 5 users, 30 seconds | 108 | 0 | 3.70 requests/s | 28 / 200 / 500 ms |
| 100 users, 90 seconds | 4,164 | 0 | 46.34 requests/s | 610 / 2,800 / 5,600 ms |

In the 100-user run, all 100 session creations and all 100 uploads succeeded. Session creation p95 was 6,900 ms; upload p95 was 5,500 ms. The observed Redis queue peaked at 93 jobs. During the run the admin page showed host CPU near 99% and RAM near 97%; disk free space was about 1.8 GiB. These resource and latency figures indicate that this laptop needs more headroom and tuning before a live 100-person event. The queue subsequently drained in the rehearsal stack.

For the **real Docker evaluator**, `python load_tests/benchmark_simulations.py --levels 1,2 --games 2` ran two complete fixture games at each concurrency level, with no failures. One worker completed two games in 10.742 seconds (0.186 games/s); two workers completed two games in 7.191 seconds (0.278 games/s). Peak observed CPU was 100% and 98.9% respectively. This four-game sample is too small to establish long-run throughput, higher worker counts, or how 100 real submissions would queue. The benchmark JSON is saved in ignored `load_tests/data/real_benchmark.json` on this laptop.

## Remaining checks and limits

- A second device on the college LAN and a public tunnel were not available for an end-to-end connection check. Follow `LOCAL_HOSTING.md`, then test a phone on the actual event network before sharing the URL.
- The production database was backed up before the Control Center code update at `data/farmcraft-control-before-2026-10-08.dump` (ignored by Git). After the update, `health-check.ps1` reported ready with database, Redis, and storage healthy; the trusted host worker had two idle processes. The original local database still contained 3 teams, 4 submissions, and 8 jobs. The player home page and admin login page loaded on port 8000. Two Redis queue pauses inherited from earlier local operations were cleared so official and sandbox jobs can dispatch. Never run `docker compose down -v` for a routine restart.
- Before the final frontend/tournament update, the live PostgreSQL database was backed up again to `data/farmcraft-before-frontend-audit-2026-10-08.dump` (ignored by Git). The stack was restarted with `stop-server.ps1` and `start-server.ps1 -Workers 2`, preserving volumes. `health-check.ps1` again reported ready with database, Redis and storage healthy. The live database still has **3 teams, 4 submissions and 8 jobs**; the host worker process is running, and the player sign-in and admin login pages loaded in the existing browser tabs on port 8000.
- The four-game real benchmark and 90-second fake load do not justify a claim of 100 simultaneous real evaluations. Start with 1–2 workers, free disk space, repeat a longer real-game benchmark, and watch the Server tab. With 7.65 GiB RAM and 4 logical CPUs, a high worker count is likely to reduce stability.
- Participant device telemetry is limited to browser session information and heartbeats. It does not report remote device CPU, RAM, battery, or temperature.
- Docker isolation reduces risk from uploaded Python but is not a complete boundary against host kernel or Docker vulnerabilities. Use a dedicated, updated organizer laptop and account.

## Reproduce

See [LOCAL_HOSTING.md](LOCAL_HOSTING.md) for production Windows/Linux startup, LAN, optional tunnel, admin, and shutdown instructions. See [load_tests/README.md](../load_tests/README.md) for isolated load commands. The test stack uses distinct volumes and must remain separate from event data.
