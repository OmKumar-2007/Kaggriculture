# FarmCraft on an organizer laptop

## Architecture

The public port serves the React site through Nginx. Nginx forwards application API paths to FastAPI inside Docker Compose. PostgreSQL holds teams, submissions, jobs, scores, audit history, and the tournament snapshot. Redis persists RQ queues and short lived sessions and telemetry. Database and Redis ports bind only to `127.0.0.1`. A trusted host Python worker claims jobs from Redis and launches a separate hardened Docker container for each game; the API never receives a Docker socket. Uploaded files live under `data/objects` on the host and are mounted into the API container. Docker named volumes preserve database and queue data across `compose down` and restarts.

The game rules and scoring configuration are unchanged. Sandbox, official, and tournament games all use the evaluator container. The dashboard, SSE job stream, and five second polling fallback present live progress. A completed official evaluation commits the score and job state in one database transaction.

## Windows setup and startup

1. Install Docker Desktop with WSL2, Python 3.11 or newer, and Git. Keep enough free space for Docker images and the event database. Install the trusted worker libraries once:

   ```powershell
   python -m pip install -r requirements-worker.txt
   ```

2. Start Docker Desktop. From the repository root run:

   ```powershell
   .\start-server.ps1 -Workers 2
   ```

   The script asks for a 12 character or longer organizer password on first run and writes an ignored `.env` containing a password hash and random session secret. Keep `.env` private and back it up. It builds the evaluator and web/API images, starts Compose services, launches the trusted host worker, and prints local and candidate LAN addresses. `run-app.bat` calls the same script.

3. Open `http://127.0.0.1:8000/` and the organizer dashboard at `http://127.0.0.1:8000/admin`. Sign in to the admin page with the organizer password. Contestants enter a new team name once and then use an HttpOnly browser session in Tournament and Bot Lab. A second browser cannot claim an existing name. For a lost browser session or a team imported from an earlier version, use **Contestants → team → Generate one-time recovery code** and share the short-lived code privately. Generating a code revokes existing team sessions.

4. Check and stop services:

   ```powershell
   .\health-check.ps1
   .\stop-server.ps1
   ```

   `stop-server.ps1` preserves uploaded files and Docker volumes. Do not use `docker compose down -v` unless you intend to delete persistent event data. To change worker count, stop and restart with `-Workers 1` through `-Workers 8`. Start with 1–2 workers, observe RAM and throughput, and increase only after benchmarking your laptop.

For Linux, install Docker Engine/Compose and Python worker requirements, then run `bash start-server.sh 2` and `bash stop-server.sh`. The first start generates the same private `.env` file. The worker always runs as a host process so it can invoke Docker without mounting the Docker socket into the API.

## LAN and optional internet access

The web port defaults to `8000` on all network interfaces; set `FARMCRAFT_BIND_IP` and `FARMCRAFT_PORT` in `.env` before startup to narrow or change it. Find the organizer laptop's IPv4 address with `ipconfig` on Windows or `ip -4 addr` on Linux. Participants on the same reachable network open `http://<laptop-ip>:8000/`. Verify it from a second device before the event. On Windows, allow TCP port 8000 for the relevant private network profile, ideally restricted to the local subnet; an elevated PowerShell command is:

```powershell
New-NetFirewallRule -DisplayName 'FarmCraft LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private -RemoteAddress LocalSubnet
```

Campus Wi-Fi may isolate clients from one another. If the second device cannot reach the laptop despite a healthy local check, ask the network administrator about client isolation or use a tunnel.

An optional Cloudflare Quick Tunnel can expose the site without opening an inbound firewall port: install `cloudflared`, then run `cloudflared tunnel --url http://127.0.0.1:8000` and share the printed address. [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) are for testing and do not support SSE, so the participant page also polls job status. For a stable event hostname, configure a named Cloudflare Tunnel and route its public hostname to `http://127.0.0.1:8000`; see [Cloudflare's tunnel guide](https://developers.cloudflare.com/tunnel/get-started/). The tunnel forwards only the web port. Keep database, Redis, and Docker management ports local.

## Event operation and recovery

- Participant upload accepts `agent.py` or `main.py`, up to `MAX_SUBMISSION_SIZE_KB` (256 by default). Home registration queues an official evaluation; Bot Lab supports upload, sandbox tests, and official submissions. A team may have one active job of each type by default. The API responds with a job ID and queued status; the result appears after the worker finishes.
- The organizer Control Center has **Teams & Sessions**, **Submissions & Jobs**, **Evaluation Pipeline**, **Tournament & Matches**, **Workers & Devices**, **System Health**, **Tournament Controls**, and **Audit Logs**. Team details show individual sessions and allow revocation, suspension, blocking, and one-time access recovery. Tournament Controls can close registration or uploads, hide the leaderboard, set submission limits and cooldowns, pause queues, and request an emergency stop. All writes require the organizer session and CSRF token and record an audit entry.
- A queued job can be cancelled immediately. Cancelling a running job atomically marks it cancelled in PostgreSQL and signals the trusted host worker to stop its active Docker evaluator; the UI reports cleanup as pending until the worker acknowledges it. Once a job is cancelled, a late worker result cannot commit a score. Queue pauses prevent new dispatch and leave running jobs alone. Worker pause, drain, disable, resume, and active-capacity controls are in **Workers & Devices**. Raising capacity above the number of host worker processes requires a restart.
- Jobs are durable in PostgreSQL. Redis AOF persists queue state. On startup and periodically the worker reconciles queued DB jobs into Redis, and stale running jobs requeue up to their attempt limit. Tournament failures require organizer review to avoid replaying an incomplete bracket.
- Inspect **Evaluation Pipeline → job** for recorded validation, container, match, scoring, and completion stages; `docker compose logs api`, `docker compose logs web`, and `data/host-worker-errors.log` provide lower-level diagnostics. The job page supports downloading logs. `health-check.ps1` verifies web/API readiness. Docker Desktop must be running for evaluations.
- Host telemetry is collected by the trusted worker through `psutil`, bounded to the last 360 samples in Redis. Device presence is based on authenticated browser heartbeats. A remote browser does not expose full system CPU/RAM/temperature; the dashboard does not claim these metrics.

## Team identity migration

Before upgrading an event with existing contestants, save a PostgreSQL backup and a copy of `data/objects`. The API adds nullable recovery fields and a session version to existing team rows, creates a team strategy table, and retains each existing team ID, submission, bot version, score, and leaderboard record. It creates a case-insensitive unique team-name index when the existing names permit it. Restart the API after deploying the updated code; its startup migration applies these additive changes. Existing browser sessions from the former access-code flow must sign in through organizer recovery once; each recovery code expires after 15 minutes and works only once. The organizer can generate it from **Control Room → Contestants** and should deliver it privately to the team.

If older data contains two team names that differ only by case, the migration leaves those records and their histories intact and skips the unique index. Resolve each collision with the organizer using independent proof of ownership before renaming a team; never merge records on name similarity alone. Then restart the API to create the index. New registration still rejects a case-insensitive name already in use. Team names may contain only letters, digits, underscores, and hyphens; a team name is claimed on first registration and is not a password. Returning teams stay signed in through their HttpOnly browser cookie until the session expires or they log out. Losing that browser session requires organizer recovery.

Strategy Path makes all nine educational guides available immediately. Selecting a focus saves that mission to the team's ID for later visits. It does not alter the Python agent uploaded by the team; their code determines match actions.

## Security and capacity limits

Each untrusted game runs without network access, with CPU/RAM/PID limits, read-only root filesystem, a temporary writable area, a non-root account, dropped Linux capabilities, and only two read-only agent mounts plus one replay output mount. The host worker is trusted and can invoke Docker; its credentials and Docker access must never be given to participants. Containers use an external timeout and are forcibly removed after timeout or failure. Docker isolation is a useful layer, not a complete security boundary against kernel or daemon vulnerabilities. Keep Docker Desktop and the host OS updated, use a dedicated event laptop/account, and avoid storing unrelated secrets there.

Team sessions use HttpOnly cookies and CSRF tokens; organizer login uses a salted password hash, signed cookie, CSRF token, and throttling. LAN HTTP traffic is unencrypted; use a trusted network or an HTTPS tunnel for remote access, especially for organizer sign-in. The system has no automated multi-laptop worker enrollment; future workers would need a separately authenticated, trusted transport. The current worker ID and per-process telemetry leave a path to add that later.

The `MAX_EVALUATION_WORKERS` setting bounds host concurrency to eight, but 100 concurrent users and a particular worker count are not guaranteed until measured on the event laptop. Use the isolated test workflow in [load_tests/README.md](../load_tests/README.md) before the event. The load stack uses separate volumes and port 18000 and cannot modify the production leaderboard.
