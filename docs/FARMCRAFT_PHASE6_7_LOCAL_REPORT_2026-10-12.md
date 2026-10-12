# FarmCraft Phase 6 + 7 local checkpoint — 2026-10-12

## Scope and cloud state

Branch: `azure-primary-phase2`. The checkout already contained unrelated modified and untracked files; none were reset or discarded. No Git push, Render/Neon change, Azure deployment, worker registration, event-mode change, or staging database write was made for this checkpoint.

Read-only Azure checks found `farmcraft-eval-01` running (Standard_D2as_v4) and `farmcraft-staging-api` provisioned with ready revision `farmcraft-staging-api--0000001`. The staging `/ready` checks for database, sessions, and storage passed. Its worker API still advertises version `2026.10.09`, while this local evaluator change is version `2026.10.12`. No claim of cloud worker compatibility is made. The VM guest's service configuration and capacity were not inspected because Azure Run Command would change the VM control plane; its production workload must be preserved.

## Request flow and findings

```text
Bot Lab upload -> versioned submission/object -> official submit -> unique
OfficialSubmissionClaim + durable SimulationJob -> remote claim/lease ->
source and frozen references -> Docker games -> progress and per-game replay
upload -> one transactional result commit -> leaderboard/Admin
```

The existing configuration already allowed 3, 5, or 10 references in `PlatformStore.configure_competition`, and Admin already offered those options. Qualification freezes selected reference IDs, versions, source hashes, keys, seeds, sides, scoring values, and evaluator version in the competition snapshot. Each official job copies that snapshot. The database has a unique `(team_id, round_started_at)` official claim, and the job creation transaction checks existing claims and jobs; a UI double click cannot create a second attempt. A retry reuses the same job and frozen payload. No historical records were modified.

The evaluator orders opponents, then seeds, then sides. With 3 references, 1 seed, and sides `[0,1]`, it runs exactly 6 games in A/P1, A/P2, B/P1, B/P2, C/P1, C/P2 order. The Docker command requests 720 steps. Scoring normalizes money back to the contestant's position. If `w` wins and `t` ties occur in `n` games, win fraction is `(w + 0.5t)/n`; economic component is `clamp(0.5 + mean(contestantMoney - opponentMoney)/(2*economic_scale), 0, 1)`; rating is `rating_scale * (win_rate_weight * win_fraction + economic_weight * economic_component)`. Current settings are weights 0.65/0.35, scale 10,000, rating scale 1,000. A failed game aborts aggregation; a partial result is not scored.

The remote protocol uses a 15-minute one-use registration token and a hashed worker credential. The worker polls every 8 seconds and heartbeats every 15 seconds by default. A lease lasts 90 seconds; a lost lease is retried within `max_attempts` (default 3), while an interrupted tournament requires organizer review. Claiming and result commit use PostgreSQL row locking and attempt IDs. An old attempt cannot commit after lease loss. Replay upload precedes final result commit. Replay writes are idempotent by object key, but a failed result commit can leave an orphan object for later cleanup.

The Docker runner uses no network, read-only root and source mounts, UID 65534, dropped capabilities, no-new-privileges, CPU/memory/PID limits, a bounded tmpfs, a 720-step command and timeout. The controller's Docker access still confers host-level power; therefore the existing production VM is not suitable for an unapproved second workload. A dedicated local organizer machine is the recommended initial staging worker. The existing VM can be considered for the event only after guest capacity, workload isolation, and current worker configuration are measured without disrupting Render.

## Changes in this checkpoint

- `backend/services/evaluation.py`: unique replay ID/path per official game, per-game metadata, optional replay callback.
- `backend/jobs.py` and `farmcraft-evaluator/app/runner.py`: local object storage and remote worker upload each official replay before result completion.
- `tests/test_scoring.py`: asserts the six-game ordering, position normalization, and six distinct replay IDs/uploads using a stub runner (unit test, not real-game evidence).
- `frontend/src/AdminApp.jsx`: shows expected games per contestant from the frozen configuration, or from the editable setup fields.
- `backend/admin.py` and `backend/services/storage.py`: an organizer may start a staging qualification snapshot with `openAccess: false`; the phase and frozen inputs advance, while MAINTENANCE mode and closed public gates remain intact. The existing Admin action defaults to `openAccess: true`, preserving prior behavior.
- `farmcraft-evaluator/VERSION`, server version defaults, local profile examples, and `azure-primary/app.bicep`: prepare version `2026.10.12` for a coordinated staging-only deployment. Render's existing `2026.10.09` setting was not changed.

## Validation and performance

- Combined backend tests: 47 passed. Three pre-existing deprecation warnings appeared. The worker HTTP registration test was updated to use the current local evaluator version. A new test verifies the isolated six-game qualification retains closed public access.
- Frontend Vite production build passed. `git diff --check` passed.
- Docker image `nitw-farm-ai-evaluator:2026.10.12` built locally.
- One local, real Docker evaluation with three distinct reference IDs, one seed, two positions, and simple PASS source completed 6 games in **23.66 seconds** total. Measured sequential game intervals were 4.70, 3.68, 3.44, 3.69, 3.68, and 4.46 seconds. Six replay files were generated. This checks the full game engine path but does not measure the API, Azure PostgreSQL, Blob upload, or a competitive bot's CPU load.
- With this nonrepresentative 23.66-second job duration and no overhead, 30 jobs require `ceil(30/c)` waves: 2 workers 355 s; 4 workers 189 s; 6 workers 118 s; 8 workers 95 s; 10 workers 71 s. These are optimistic lower bounds, not a Phase 8 capacity claim. The previous 26–38 seconds per game would imply 156–228 seconds per six-game job and 2,340–3,420 seconds at 2 workers or 780–1,140 seconds at 6 workers. Measure representative bots, replay transfer, queue latency and DB load before buying workers or splitting jobs.

## Staging activation approval gate

Initial approach: use a dedicated local Docker worker, separate staging profile and identity, one concurrent job. It makes outbound HTTPS calls to the Azure staging API and needs no new Azure infrastructure. Keep the staging event in MAINTENANCE and all public registration/official toggles off. A controlled staging-only test needs these explicit mutations:

1. Deploy reviewed commit/image version `2026.10.12` to the Azure staging app only. Preserve maintenance and zero in-app workers.
2. Enable staging remote registration, issue one 15-minute token, register a new staging-only local worker, and store its credential in an ignored restricted file. Do not reuse the Render credential. Confirm version and config hash before starting the worker.
3. Create three stage-only reference bots and one stage-only test team/submission in the staging database and private Blob container. Run each reference's real validation test.
4. Set the staging competition reference count to 3 and seed count to 1, then call the admin start-qualification action with `openAccess: false`. The phase advances and freezes the inputs while MAINTENANCE and public gates remain closed. After the test team's upload is present, enable only official submissions while registrations/uploads/leaderboard remain disabled. This writes one official claim/job; it does not open public registration.
5. Run one six-game official evaluation, verify each replay and score in Admin, then drain/revoke the staging worker and return the event to MAINTENANCE. Preserve the test artifacts for audit until separately approved cleanup.

No such staging mutation is authorized by the Phase 6/7 request. Approval should name the exact deployment image, local machine, staging identity, event-mode changes, test records and rollback. A local worker adds no Azure VM charge; it consumes organizer-machine CPU/power and existing staging API, PostgreSQL, Blob, and network capacity. Azure Blob writes and egress can add variable costs. If the local machine cannot provide safe isolation or representative performance, propose a dedicated Azure VM with a separate cost/credit approval.

## Remaining work and Phase 8 gate

The staging API has not received this code or connected to a worker. Six-game API-to-Blob-to-database evidence is pending approval. The existing VM guest version, Docker image digest, live concurrency and production workload remain unverified. The local PASS-bot timing does not establish the 180-game/15-minute target. Phase 8 should start only after one authorized end-to-end staging job, representative multi-bot timings, worker lease/crash/retry checks, and a new Azure credit/cost review. Phase 5 disaster recovery remains postponed and is required before production cutover.
