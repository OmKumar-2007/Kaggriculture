# Production architecture

## Services

- **Render Static Site:** React/Vite contestant portal and `/admin` Control Room.
- **Render FastAPI web service:** request validation, shared state APIs, SSE/polling status, and job creation.
- **Render PostgreSQL:** teams, versioned submissions, jobs, evaluations, worker heartbeats, event settings, audit log, and tournament snapshot.
- **Render Key Value (Redis):** RQ transport. A bounded worker service runs jobs in tournament, official, then sandbox priority order.
- **S3-compatible object storage:** bot versions and replay artifacts. Cloudflare R2 is configured through the S3 interface.

The API persists a job before enqueueing it. PostgreSQL is the canonical lifecycle record; Redis is the dispatch transport. The web process does not run game simulations for sandbox/official requests. The current tournament runner is submitted as one prioritized job and writes its snapshot as progress arrives.

## Environment

Required API/worker values:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis/Render Key Value connection |
| `STORAGE_BACKEND` | `local` for development or `s3` in production |
| `OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY`, `OBJECT_STORAGE_SECRET_KEY` | S3/R2 access |
| `ADMIN_PASSWORD_HASH` | PBKDF2-SHA256 encoded organizer password hash |
| `ADMIN_SESSION_SECRET` | Random secret, at least 32 characters, used to sign HttpOnly sessions |
| `APP_ENV` | `production` on hosted services; fake scoring only accepts development/local/staging/test |
| `CORS_ORIGINS` | Comma-separated additional exact frontend origins when required |
| `SIMULATION_WORKERS` | Bounded worker process count, default 2 |
| `WORKER_HEARTBEAT_INTERVAL` / `WORKER_HEARTBEAT_TIMEOUT` | Worker health sampling and offline threshold |
| `QUEUE_DEGRADED_SECONDS` | Queue wait threshold used for DEGRADED status |
| `API_P95_DEGRADED_MS`, `API_P95_CRITICAL_MS` | API latency thresholds used for system status |
| `FAILURE_RATE_DEGRADED_THRESHOLD`, `FAILURE_RATE_CRITICAL_THRESHOLD` | Infrastructure failure-rate thresholds used for health status |
| `MAX_INFRASTRUCTURE_RETRIES` | Manual infrastructure retry limit |
| `MAX_UPLOAD_BYTES`, `MATCH_TIMEOUT_SECONDS` | Request and game limits |

Create a hash locally; do not commit the result or password:

```powershell
python -c "import getpass,hashlib,secrets; p=getpass.getpass('Organizer password: '); s=secrets.token_hex(16); n=600000; print(f'pbkdf2_sha256${n}${s}$'+hashlib.pbkdf2_hmac('sha256',p.encode(),s.encode(),n).hex())"
```

Generate the signing secret independently with a cryptographically secure random generator. Set both values as private service environment variables in Render. Login is at `/admin`; its authenticated JSON APIs are under `/api/admin/*`. Mutating organizer requests also require the per-session CSRF header returned by the login/session endpoints.

For reliable browser cookie behavior, place the static site and API under the same registrable domain (for example `arena.example.com` and `api.arena.example.com`) or proxy `/api` through the frontend origin. Default sibling `*.onrender.com` hosts can be treated as cross-site by privacy settings that block third-party cookies.

## Startup and schema

Local services can be started with `docker compose up -d --build`; the API command is `uvicorn backend.main:app --host 0.0.0.0 --port 8000`, and workers start with `python -m backend.worker`. Render Blueprint is in `render.yaml`.

The repository includes Alembic configuration and an initial shared-schema revision. Apply it with `alembic upgrade head` after setting `DATABASE_URL`; the API also calls SQLAlchemy `create_all` as an idempotent boot guard. For existing production databases, take a backup, inspect current tables, and create a reviewed Alembic revision before deploying schema changes. A small compatibility adjustment remains for the prior SQLite schema.

## Upload and replay storage

Set `STORAGE_BACKEND=s3` and provide the S3-compatible endpoint, bucket, access key, and secret. Bot sources are written under `submissions/{team}/{submission_id}/agent.py`; replay references are under `replays/`. Local mode writes under `LOCAL_STORAGE_ROOT` and is suitable only for development or a persistent local disk.

## Load testing

Local fake-job load test:

```powershell
$env:APP_ENV='development'
$env:LOAD_TEST_FAKE_SIMULATION='1'
docker compose up -d --build
locust -f load_tests/locustfile.py --headless -u 100 -r 10 -t 10m --host http://127.0.0.1:8000 --html load-report.html
```

Remote hosts are rejected by default. Approved non-production staging runs require `ALLOW_REMOTE_LOAD_TEST=1` and an exact hostname in `LOAD_TEST_STAGING_HOSTS` (or a hostname containing `staging`); the public production hostnames are always rejected. Fake simulations wait a deterministic 2–8 seconds and update normal job, evaluation, and leaderboard lifecycle records; they are prohibited when `APP_ENV` is production. Run `load_tests/benchmark_simulations.py` separately for real engine measurements.

## Operational limits

The RQ worker count is bounded. Pausing a queue prevents workers from taking new jobs from it; already-running games are allowed to finish. A worker heartbeat older than the configured threshold is shown offline. Infrastructure-only failures can be retried from the Control Room; contestant failures are not retried automatically. Organizer actions are audited.

This deployment is designed for an event around 100 contestants, not an unlimited public workload. The Load Test Report records the local environment and measured evidence; do not treat fake-job throughput as a real-game capacity result.
