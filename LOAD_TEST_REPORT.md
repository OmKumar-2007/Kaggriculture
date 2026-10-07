# Load test report

**Run date:** 2026-10-07
**Decision:** **NOT READY FOR 100 CONTESTANTS** — the read-only API held 100 users, but this environment could not run the full queued mixed load test because Docker Desktop's engine was unavailable. Redis/PostgreSQL and worker lifecycle readiness therefore remain unverified in this run.

## Environment and test evidence

| Test | Environment | Result |
|---|---|---|
| Automated tests (`pytest -q`) | Windows / Python 3.11 | 29 passed |
| Alembic migration smoke | Temporary SQLite database | `alembic upgrade head` passed |
| Frontend production build (`npm run build`) | Vite 8.3.1 | Passed |
| 100-user spectator smoke | Local FastAPI, SQLite, one API process, 4 logical CPUs, 7.65 GiB RAM; 10 seconds | 297 requests; 0 HTTP failures; 32.50 req/s; p50 12 ms, p95 52 ms, p99 69 ms |
| Real game benchmark | Local Kaggriculture runner; 2 games per concurrency level | 0 failures across levels 1, 2, 4, 8; see results below |
| Full 100-user mixed queue test | Not run | Docker daemon unavailable; `docker compose ps` could not connect to Docker Desktop Linux engine |
| API readiness | Local API process | `/health` returned `ok`; `/ready` returned 503 because Redis was unavailable |

The spectator run is a read-only API test. It does not prove queue throughput, database capacity under write load, or worker recovery. It used SQLite and should not be read as a production Postgres result.

## Real simulation benchmark

Measured using `load_tests/benchmark_simulations.py --levels 1,2,4,8 --games 2`. The short sample is useful as a smoke check, not a production worker-sizing benchmark.

| Concurrent games | Games | Average runtime | p95 runtime | Throughput | Peak observed CPU | Process memory delta | Failures |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 3.208 s | 3.487 s | 0.311 games/s | 85.9% | +5.70 MiB | 0 |
| 2 | 2 | 4.028 s | 4.068 s | 0.470 games/s | 76.7% | +5.06 MiB | 0 |
| 4 | 2 | 4.001 s | 4.043 s | 0.473 games/s | 78.8% | +3.01 MiB | 0 |
| 8 | 2 | 3.925 s | 3.976 s | 0.493 games/s | 82.0% | +4.00 MiB | 0 |

The JSON output is in [`load_tests/results/real_benchmark.json`](load_tests/results/real_benchmark.json). Memory delta is for the benchmark process, not total machine or isolated worker memory. Only two games per level means these p95 values are not statistically stable.

## Existing event-profile artifacts

These Locust CSVs were generated on 2026-10-06 and are retained under `load_tests/results/`. Each short event profile had zero HTTP failures, but the earlier official profile predates the leaderboard query optimization and its response times are not current measurements.

| Profile | Users | Requests | Aggregate p95 | HTTP failures |
|---|---:|---:|---:|---:|
| Spectators after leaderboard query fix | 100 | 459 | 280 ms | 0 |
| Bot uploads | 100 | 615 | 900 ms | 0 |
| Sandbox submissions | 100 | 436 | 720 ms | 0 |
| Official submissions (pre-query-fix artifact) | 100 | 523 | 6,400 ms | 0 |

The official profile made 100 submission requests, but the artifact does not establish that 100 official jobs completed or that the leaderboard converged correctly. Historical peak queue depth, worker count, completed/failed job counts, average queue wait, and worker-crash recovery were not captured, so they are left unclaimed.

## Findings and remaining verification

- A fresh 100-user read-only spectator profile completed successfully with low latency on the local API/SQLite setup.
- The leaderboard query fix has much lower latency in later spectator artifacts than the older official profile, but a current write-heavy run is still needed.
- Real game execution completed without failures at the four requested concurrency settings on this 4-core machine. The sample is too small to determine a production worker count.
- Docker was not running, so this session could not test Postgres + Redis + RQ together, 100 mixed users, 100 official jobs end-to-end, worker restart/recovery, or live organizer queue visibility.
- The bad-agent fixture matrix is included, but its isolated Docker runner verification could not run because Docker was unavailable.
- Before the event, start Docker services and rerun the 10-minute mixed profile plus 100-team official surge against local/staging, recording job completion, queue wait, queue peak, worker count, API response percentiles, and post-run leaderboard state.

**NOT READY FOR 100 USERS**
