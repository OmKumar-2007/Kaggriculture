# FarmCraft Phase 6/7 — Checkpoint B staging evaluation plan

## Current state

Checkpoint A is deployed and healthy at `farmcraft-staging-api--0000002`. The staging competition is in `SETUP`; event mode is `MAINTENANCE` and public registration, uploads, sandbox, official submissions, and tournament actions are closed. No evaluator laptop is registered. The staging API image does not yet contain the fixture route described below.

Render, both Neon projects, and `farmcraft-eval-01` are outside this checkpoint.

## Locally prepared fixture route

`backend/admin.py` now has two organizer-only, CSRF-protected routes: upload one validated `agent.py` for the named fixture team during `SETUP`, and queue exactly one official six-game job after qualification opens. Both routes are disabled by default. They require `FARMCRAFT_STAGING_FIXTURE_ENABLED=1`, the exact staging PostgreSQL and Blob hosts, PostgreSQL queue mode, `MAINTENANCE`, and all five public event actions closed. The queue route additionally requires three frozen reference bots, one seed, both sides, and a valid fixture submission. The normal official one-attempt claim still applies. Five local gate/queue tests pass.

The fixture route is not a public participant upload test. It validates the stored source and then exercises the actual durable queue, remote worker protocol, Docker evaluator, reference snapshot, six games, replay upload, result recording, and admin visibility. It leaves a real non-rehearsal test team and job in the isolated staging database. Cleanup of those records would need its own reviewed procedure; they will not be silently removed.

## Proposed execution after separate approval

1. Review the exact source diff, rebuild the image with the fixture route, inspect exclusions and config hash, push it to the existing staging ACR, deploy only `farmcraft-staging-api`, enable the fixture flag only there, and verify `/ready` plus MAINTENANCE controls. Keep the prior healthy revision for rollback.
2. Prepare the separate local evaluator Python environment and Docker evaluator image. Issue a short-lived staging registration token via staging organizer API; register one laptop worker at concurrency one. Protect its credential in the ignored local profile. Verify version and configuration hash match staging before processing jobs.
3. Upload three distinct reference sources to staging through existing organizer APIs and run their real reference tests. Select the three passing versions. Set three references and one qualification seed. Upload one validated fixture agent through the guarded route.
4. Start qualification with `openAccess=false`. Recheck that public registration, upload, sandbox, official, and tournament actions remain closed. Queue the fixture's one official job via the guarded route. Observe six completed games, both sides for each reference, six distinct replay IDs, source hashes, job status, and rating.
5. Stop and revoke the staging worker, disable the fixture flag, and restore the exact pretest event control values. Do not publish qualifiers or start a tournament. Report the job and artifact IDs, timing, errors, and any partial state.

## Rollback and boundaries

If the new revision fails health checks, restore the previous immutable staging image and evaluator version, then verify `/ready`. If an evaluation fails, stop further jobs, revoke the staging worker, and report the existing fixture/reference/job rows before any cleanup. Staging qualification phase advancement is persistent and is **not** automatically reset to `SETUP`; resetting that phase would require a separate safe cleanup plan. The public staging HTTPS endpoint remains reachable, but participant actions remain closed throughout.

No new Azure infrastructure is proposed. Existing Container App/ACR/storage usage and local Docker compute can increase; actual billed usage will be checked after the run. No production route, database, VM, DNS, or Git branch will be changed.
