# FarmCraft fresh event migration (prepared, not cut over)

## Verified state, 2026-10-11

- Archived Neon project: `farmcraft-control-plane` (`misty-poetry-11204791`). It remains configured on the live Render API and was not altered by this preparation.
- Fresh Neon project: `farmcraft-control-plane-v2` (`nameless-mountain-72584949`), production branch `br-hidden-butterfly-az5o9i8f`, AWS Singapore, Free plan.
- The pooled PostgreSQL connection succeeded independently of Render. SQLAlchemy initialized all 21 model tables. A second initialization succeeded. Teams, submissions, jobs, reference bots, remote workers, official claims, and tournament games are empty; competition phase is `SETUP`.
- The new `farmcraft-v2-private` bucket is private and empty. HEAD, PUT, and GET succeeded; the probe object was deleted.
- A local FastAPI startup probe against the new database, bucket, and existing session Redis returned `/ready` with all checks healthy, zero `/players`, and `SETUP`. This was not a live Render cutover.
- Render API currently uses the archived database; its `/ready` reports database unavailable because Neon rejects the old project's connections for quota. The API's last live commit is `c423006`; the Git branch includes later commits, and auto-deploy is off.
- The Azure VM `farmcraft-eval-01` is running. Two worker services were active, with no Docker evaluation container visible during the check. The old database's durable queued/running job state could not be inspected while quota-blocked.

## Architecture and risks

`backend.services.storage` creates the SQLAlchemy engine at import from `DATABASE_URL` (pool size 6, overflow 4) and runs `Base.metadata.create_all()` plus additive migrations. `backend.main` runs job recovery at startup. Six bot files under tracked `players/` were previously eligible for automatic import into a fresh database; the new `IMPORT_LEGACY_PLAYERS=1` opt-in prevents that contamination by default. `STORAGE_BACKEND=s3` uses the five `OBJECT_STORAGE_*` variables, and the database keeps object keys for bot sources and replays. `QUEUE_BACKEND=postgres` makes PostgreSQL the durable job queue; Redis serves browser sessions. Worker identities and registration tokens live in the database, so existing Azure credentials cannot authenticate after the switch.

The admin dashboard polls every five seconds. Before the query change, `/api/admin/metrics` and contestant metrics loaded entire `simulation_jobs` rows, including potentially large `result_json`, even when only counts, timestamps, and statuses were needed. This is a plausible major contributor to Neon transfer but not a proven full accounting of 9.47 GB. The local change selects only needed columns for these frequent reads and removes a per-team strategy lookup. The admin job list and participant job details still load results and need transfer monitoring under real traffic.

## Protected local rollback material

The ignored, user-restricted `config/local-profiles/farmcraft-render-env-before-v2.env` holds the current Render variables. The corresponding new database URL and storage configuration are in `farmcraft-v2-database-url.txt` and `farmcraft-v2-storage.json` in the same directory. Keep these files off Git and out of messages. The old Neon project and bucket remain the historical archive. The existing local PostgreSQL dump predates finalization and is **not** a complete current archive.

## Cutover procedure — requires organizer approval

1. Confirm the Git branch contains the startup and transfer fixes and that Render auto-deploy remains off. Save the exact commit and the service's current environment and deploy identifiers. Do not launch official qualification.
2. Inspect the VM for active Docker evaluations and, if clear, stop the old worker services before switching. Leave the VM, its disk, and its local credentials intact.
3. In Render API Environment, change **only** `DATABASE_URL`, `OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY`, `OBJECT_STORAGE_SECRET_KEY`, and `OBJECT_STORAGE_REGION` to the verified v2 values. Preserve Redis, admin authentication, CORS, evaluator version, and all other variables. Use a save-without-deploy action if available, then manually deploy the approved Git commit so code and environment switch together.
4. Require `/ready` to show database, Redis, and storage true. Require `/players` to show zero and competition phase `SETUP`; check admin login and event settings. If any check fails, stop and diagnose before participant access.
5. Issue new one-time registration tokens in the new admin database. On the VM, use `FARMCRAFT_WORKER_CREDENTIAL_FILE` to register each worker into a **separate v2 credential file**; do not overwrite `credentials.json` or the slot credential files. Validate each new credential against `/api/remote-workers/me`, stop its service, retain the old file under a restricted archive name, move the validated v2 file into the expected path, and restart. The current registration scripts refuse to overwrite existing credentials. Verify heartbeats and one sandbox job before any scale or official evaluation.
6. Exercise one disposable contestant registration, upload, object retrieval, sandbox result, replay, analytics, and admin monitoring. Remove only data created for this v2 probe. Keep official Round 1 unstarted.

## Rollback

Do not automatically reconnect the archived project: doing so resumes ordinary application writes and could change historical records. If v2 fails, first keep the API unavailable or repair v2. With separate approval to reattach the archive, restore the saved six old environment values and the previous API deploy, then verify `/ready`; expect the old Neon quota to continue blocking it until Neon restores access. Do not restore the pre-finalization dump over either database. Do not delete either project or bucket.

## Transfer monitoring

Watch the v2 project's Network transfer and compute usage in the Neon console after each small sandbox run and at least daily during the event. Compare growth against API request volume and worker polling; stop load rehearsal if transfer rises unexpectedly. The app-side optimization reduces selected bytes for the most frequent admin metrics calls, but Neon is the authoritative source for billed transfer. A 30-bot stress test is deferred until the small live flow and transfer trend are measured.
