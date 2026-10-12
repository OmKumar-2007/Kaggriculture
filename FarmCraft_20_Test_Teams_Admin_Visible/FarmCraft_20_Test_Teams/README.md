# FarmCraft — 20 Test Teams and 20 Bots

An **offline-prepared test kit** for the `OmKumar-2007/Kaggriculture` FastAPI app. It contains 20 **distinct Python `agent.py` sources** mapped one-to-one to 20 unique QA team names. It has **not created accounts on production or any remote service**.

## Contents

- `teams.csv` — exact names, bot descriptions, paths, SHA-256 checksums
- `team_names.txt` — names for organizer/admin inspection
- `bots/<TEAM>/agent.py` — one valid, independent bot file per team
- `validate_bots.py` — offline bot syntax + sample observation/action checks
- `provision_test_teams.py` — creates sessions/teams and uploads each bot to a permitted API
- `monitor_jobs.py` — read-only progress/score monitor for optional queued sandbox jobs
- `test_provision_client.py` — local mock API integration test (creates no real teams)

The first two agents are more involved, crop-focused and goose/livestock-focused strategies. The other 18 are variants of the repository's synthetic farming benchmark fleet with different crop preferences, job priorities, seed purchasing and selling thresholds. This collection is **for app testing**, not 20 tournament-optimized bots.

## IMPORTANT: Account semantics and production risk

The app does **not use team passwords**. `POST /api/participants/session` creates a team and returns an HttpOnly cookie plus CSRF token. Registered team names cannot later sign in again without a valid existing session or an organizer-issued recovery code. This kit stores separate team session cookies under `runtime/sessions/` so subsequent test runs can reuse them.

**Keep the `runtime/` folder private. Do not commit it or share it.** The kit ZIP does not contain login credentials or live cookies. Test sessions can expire; retain the test-account names and use organizer recovery if needed.

**Creating 20 ordinary accounts on production consumes up to 20 real registration slots.** This is not the existing `is_rehearsal` admin mode. The script blocks production by default. Do not execute against production while contestant registration/competition data matters.

## 1. Unpack and validate

From PowerShell in the folder where you extracted the ZIP:

```powershell
cd .\FarmCraft_20_Test_Teams
py -3 validate_bots.py
py -3 test_provision_client.py
py -3 provision_test_teams.py
```

Without `--execute`, provisioning only lists intended changes; no accounts are created.

## 2. Register 20 teams + upload 20 bots on LOCAL TEST API

Start a **separate local instance** of FarmCraft with isolated DB/object storage, then run:

```powershell
py -3 provision_test_teams.py --base-url http://127.0.0.1:8000 --execute --workers 2
```

The runner first checks `/health` and `/ready`, then creates 20 team sessions and uploads all 20 bots to `/botlab/upload` with their correct cookies and CSRF tokens. It verifies `validation.valid` and saves `runtime/provision_results.json`.

The runner can be re-run while cookies remain valid. It restores sessions and skips already-uploaded submissions unless you explicitly use `--force-upload`.

## 3. Run limited real sandbox jobs (optional)

To enqueue up to 4 real sandbox evaluations, using teams that were already provisioned:

```powershell
py -3 provision_test_teams.py --base-url http://127.0.0.1:8000 --execute --mode sandbox --max-sandbox-jobs 4
py -3 monitor_jobs.py
```

To enqueue one sandbox match for **all 20 bots** in an **isolated test environment** (check worker capacity first):

```powershell
py -3 provision_test_teams.py --base-url http://127.0.0.1:8000 --execute --mode sandbox --max-sandbox-jobs 20 --workers 3
py -3 monitor_jobs.py --timeout 7200
```

**The script queues real jobs; it does not generate fake successful results.** This tests the submit/queue/worker interface when the real Docker evaluator is connected. It does not automatically trigger official Round 1 evaluation, competition registration, seeding or tournament progression.

## 4. Remote STAGING (explicit opt-in)

Use only an authorized, isolated staging instance with its **own test database and object storage**:

```powershell
py -3 provision_test_teams.py --base-url https://YOUR-STAGING-API.example.com --allow-staging --staging-host YOUR-STAGING-API.example.com --execute
```

The known production hosts (`neural-coliseum-api.onrender.com` and `neural-coliseum.onrender.com`) are **blocked** unless an operator explicitly provides both `--allow-production` and `--acknowledge-competition-slots`. Those flags should only be used after reviewing the impact and confirming production testing is intended. Always use the backend API URL, not the static frontend URL.

## Verification already performed when this kit was created

- **20 SHA-distinct bot files**, sizes approximately 5–20 KB
- **20 bots / 15,360 offline mock-observation action validations**, including all required return fields
- Local fake-HTTP-API integration: **20 account registrations, 20 authenticated bot uploads, 20 saved cookie jars**, followed by **20 session restores, 20 safe upload skips, 4 sandbox enqueue requests**

**Not yet performed:** 20 real sign-ins to Render/staging, real Kaggriculture 720-turn evaluation runs, production registrations, or stress-test timings. Those require your accessible app/worker and deliberate target selection.

## Extra note

If this kit is copied into your Git repository, add `FarmCraft_20_Test_Teams/runtime/` to `.gitignore` before running. The saved session cookies are sensitive bearer credentials.
