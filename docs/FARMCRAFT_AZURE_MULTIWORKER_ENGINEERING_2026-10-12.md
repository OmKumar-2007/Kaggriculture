# FarmCraft Azure multi-worker engineering checkpoint — 2026-10-12

## Scope and deployed state

This checkpoint changed only the existing Azure staging Container App and created non-destructive staging reference and rehearsal-only official test jobs. Render, both Neon projects, published qualifiers, the existing `farmcraft-eval-01` VM, production DNS and Git remotes were untouched. No new Azure infrastructure was provisioned or removed.

| Item | Verified state |
| --- | --- |
| Azure staging URL | `https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/` |
| Admin URL | `/admin` on the same origin |
| Revision | `farmcraft-staging-api--0000010` |
| Image | `fcstg6chsyox4t2zfa.azurecr.io/farmcraft@sha256:a4b2d9537b9bb2f9efd59a87a54b0b018ea581d1bb24836e13f81ae1c096641c` |
| Rollback image | `sha256:c5145368fed47146fe488656987d65f637a1c048650b2dc2888f63bddb717e73` |
| Evaluator version/config SHA256 | `2026.10.12` / `dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1` |
| Readiness | API, PostgreSQL, sessions, Blob all ready |
| Container limits | 0.5 vCPU/1 GiB per replica, minimum 0, maximum 2 |
| Event | `MAINTENANCE`; registrations, uploads, sandbox, official and tournament gates closed |
| Competition | `QUALIFICATION_OPEN`, three frozen references, one seed, both sides |
| Temporary workers | 3 registered, exercised, drained and revoked; 0 active slots after tests; 4 historical staging identities all revoked |
| Worker registration | Admin-only one-use token issuance enabled; no unspent token was retained by the test scripts |
| Jobs | Eight completed staging jobs total, including this checkpoint's three reference jobs and one six-game official job |

The previous [Checkpoint B report](FARMCRAFT_PHASE6_7_CHECKPOINT_B_RESULTS_2026-10-12.md) records one real six-game official staging evaluation and six successful replay reads. This checkpoint ran a second six-game official evaluation for a newly created rehearsal-only team; all six replay reads succeeded. The new per-game checkpoint path therefore ran in Azure, while a forced Azure worker crash/retry has not yet been exercised.

## Implementation

- Multiple worker processes now use independent profile, credential and drain/stop paths. The Windows staging launcher checks version, config hash, Docker image and host capacity before launch. It offers inspect, prepare, register, start, status, drain, stop, revoke, logs and export actions. It leaves revoked credentials protected locally for audit.
- Linux `farmcraft-staging-worker@.service` and `staging-worker-slot.sh` prepare separate slot files, use interactive one-use registration, enforce permissions and provide graceful drain/stop. These are templates only; no VM was changed.
- PostgreSQL remote claims already used `FOR UPDATE SKIP LOCKED`. Progress now writes under job row lock and attempt/lease fencing. Official games now persist one checkpoint per scheduled game after replay upload. Retry carries completed games to a replacement worker; final result requires all checkpoints and recomputes the aggregate score. Legacy jobs remain readable.
- Admin remote worker metrics use batched queries and expose host, active jobs, available slots, completion/failure counts and average duration. Admin table and health summary show the new data. Admin job lists no longer load large result JSON; details retain the full result.
- Bot Lab reduces hidden-tab status requests, continues polling after SSE failure and shows a recoverable status connectivity message. Same-origin routes avoid a Render dependency.
- New Admin-only, exact-environment staging fixture routes create uniquely named rehearsal teams during frozen qualification while all public gates remain closed. The fixture flag was enabled only for the controlled test and restored to `0` afterward. No staging data was deleted.
- SQLAlchemy PostgreSQL pooling defaults to 3 persistent plus 2 overflow connections per API replica, with pre-ping; two replicas thus have a bounded 10-connection application budget. `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` are bounded overrides.
- Admin System Health now measures the duration of its PostgreSQL `SELECT 1`, session and storage probes and reports checkpointed official games plus the trailing ten-minute game rate. At final verification, PostgreSQL query was 9.7 ms, session check 12.98 ms and storage check 8.54 ms; these are single observations, not latency percentiles.
- Evaluator Docker execution remains network-disabled, read-only, non-root, capability-dropped, with CPU, memory, process, time and temporary storage limits. Worker controller Docker access is separate from the contestant container. The built API image is non-root and contains neither local profile secrets nor test files.

## Evidence and limits

| Check | Result |
| --- | --- |
| Backend suite | 107 passed; 3 dependency/deprecation warnings, 0 failures |
| Frontend production build | Passed |
| Git whitespace check | Passed (line-ending warnings only) |
| Linux shell syntax | Passed using Git Bash; not run under systemd |
| Staging image build/content | Passed, matching config SHA, no local profiles, UID 10001 |
| Staging multi-worker smoke | Three reference jobs completed; two distinct workers claimed jobs; 0 failures; both drained/revoked |
| Staging isolated official smoke | One new rehearsal team, six-game official job `d9fb0e25-6532-4e23-b417-f0ea11b8a524`, rating 787.6583333333333, six distinct replay reads, worker 03 drained/revoked |
| Staging HTTP routes | `/`, `/admin`, `/ready`, worker version all HTTP 200 |
| Azure PostgreSQL queue concurrency | Observed two distinct workers taking separate real jobs; the full 30-job race is untested |
| Staging official checkpoint/retry | Normal checkpoint path ran in Azure; local HTTP, store and resumed-game tests passed; Azure forced retry remains untested |

Local Docker 720-step benchmark on a four-logical-CPU, approximately 8 GiB laptop (starter versus random agents):

| Slots | Games | Wall time | Throughput | Mean | P95 | Peak host CPU | Peak host RAM |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 6/6 | 27.43 s | 13.13 games/min | 4.57 s | 4.96 s | 96.5% | 7.45 GiB |
| 2 | 6/6 | 17.91 s | 20.10 games/min | 5.94 s | 6.46 s | 97.8% | 7.36 GiB |

The laptop was nearly CPU and memory saturated at two slots. Four, six, eight and ten local slots were not attempted. The six-games-per-job design remains preferable for this event: thirty jobs are enough for queue balancing, while per-game durable checkpoints preserve partial work. A 180-game runtime of 8.96 minutes from the measured two-slot throughput is only an ideal starter-agent extrapolation; competitive bots, replay transfer, database waits and burst contention could exceed 15 minutes. Do not treat this as an acceptance result.

Provisional event plan: one slot on the existing D2as v4 plus two slots on each of two separately approved D4as v4 VMs (five slots total). This is a capacity hypothesis, not a deployment recommendation to execute now. The earlier ten-slot proposal is not supported by CPU evidence. Representative bots and 30 actual contestants must determine final capacity and whether a smaller cluster suffices. No new VMs were provisioned.

## Cost review (estimates, not billed usage)

Read-only `az consumption usage list` returned 26 metered entries for October 10–12, but `pretaxCost`, `billableQuantity` and `usageQuantity` were `None`; actual billed spend could not be obtained from that API response. The previously reported ₹9,334 student balance is a historical point-in-time value, not a refreshed balance.

Korea Central public retail rates retrieved October 12 via the [Microsoft Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices): D2as v4 Linux $0.118/hour, D4as v4 and D4s v4 Linux $0.236/hour, PostgreSQL B1ms compute $0.026/hour, PostgreSQL storage $0.131/GB-month, Basic ACR registry unit $0.1666/day. The staging PostgreSQL is 32 GB, so its compute plus provisioned storage is approximately $0.0318/hour or $23.17 per 730-hour month before backup overage, network and taxes. The stopped Phase 3 PostgreSQL test server is a separate 32 GB storage risk at approximately $4.19/month while stopped; it was neither restarted nor deleted. Basic ACR is approximately $5.00 per 30 days, plus excess storage and operations. The API has zero minimum replicas and may consume the shared Container Apps free grant; [Azure pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/) lists 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests per subscription-month before consumption charges. Actual free-grant usage is unknown.

The proposed five-slot VM compute is $0.590/hour, or $1.77 for three hours, if all three VMs run throughout. Two **additional** D4as v4 VMs contribute $0.472/hour or $1.416 for three hours. This excludes VM disks, public IPs, data transfer, load-balancer/network meters, taxes and any API/Blob consumption. Deallocating VMs stops compute billing but retained disks and static IPs can continue billing. The existing VM is currently running and costs an estimated $0.118/hour compute before those other meters. Staging has no explicit public IP or load-balancer resources in its resource group; the existing evaluator VM does have a Standard static public IP and Standard HDD disk. Blob account is Standard LRS with public access disabled; its variable data/transaction charges were not measurable from the available usage output. ACR reports 295,670,967 bytes used against its included 10 GiB Basic storage allowance after these image pushes. Official Azure cost management and the current student balance should be checked before any new VM approval.

## Operations

Run from `D:\kaggriculture\Kaggriculture`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/deploy-staging-update.ps1 -Action Verify
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/verify-staging.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/staging-workers.ps1 -Action Inspect -Count 2
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/staging-workers.ps1 -Action Status -Count 2
```

For a **new, separately named** temporary staging worker fleet, inspect, prepare, register each slot, then start. The two identities used here are revoked and must not be reused silently. Check host CPU/RAM before choosing the count. To finish, drain, confirm processes exited, then revoke. Use `-Action Logs -Slot N` for local logs and `-Action Export` for an ignored local metrics file. The staging Admin password is recoverable only through `azure-primary/copy-staging-admin-password.ps1` from the DPAPI-protected local profile; do not print it in shared logs or chat.

Example for the next unused slot, subject to local capacity and a fresh one-use registration token:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/staging-workers.ps1 -Action Prepare -FirstSlot 4 -Count 1
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/staging-workers.ps1 -Action Register -Slot 4 -FirstSlot 4 -Count 1
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/staging-workers.ps1 -Action Start -FirstSlot 4 -Count 1
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/staging-workers.ps1 -Action Status -FirstSlot 4 -Count 1
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/staging-workers.ps1 -Action Drain -FirstSlot 4 -Count 1
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/staging-workers.ps1 -Action Revoke -FirstSlot 4 -Count 1
```

The Admin UI is at the URL above; API readiness is `GET /ready`. The isolated fixture runner requires the staging fixture flag to be deliberately enabled on a ready revision, a live staging-only worker and all public gates closed. Restore that flag to `0`, drain and revoke the worker immediately after use; the runner does not do that automatically. The current flag is verified `0`.

Build/deploy only after reviewing the full working tree and image contents:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/deploy-staging-update.ps1 -Action BuildDeploy -ExpectedCurrentDigest sha256:a4b2d9537b9bb2f9efd59a87a54b0b018ea581d1bb24836e13f81ae1c096641c -Tag <new-immutable-tag>
```

Rollback to the previous verified image if needed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File azure-primary/deploy-staging-update.ps1 -Action Rollback -RollbackDigest sha256:c5145368fed47146fe488656987d65f637a1c048650b2dc2888f63bddb717e73
```

The deploy script checks that the **new revision itself** is healthy and runs the expected digest before declaring success. A failed BuildDeploy readiness check attempts to restore the prior image and reports failure. It does not modify Render or Neon.

## Phase 8 gates

1. **Implemented and verified:** independent worker identities, two-worker real staging claims, two six-game staging official evaluations, six-game frozen schedule, normal official per-game checkpoints, local checkpoint/retry/score tests, closed participant gates, staging API readiness.
2. **Implemented but not fully tested:** lease expiry during a real Azure Docker game, Blob partial-failure recovery, Linux systemd startup, long-duration worker stability. Non-destructive staging inspection/export exists; destructive reset is deliberately unimplemented pending a separately reviewed staging backup and selective deletion plan.
3. **Requires additional infrastructure and separate approval:** any D4-class VMs, disks, networking, and their billed capacity. Existing `azure-workers/worker.bicep` can serve as a planning base but must use a new resource group/name and an immutable published worker source before provisioning; do not target `farmcraft-eval-01`.
4. **Requires separate approval:** representative bot benchmark and full 30-contestant/180-game rehearsal, public event opening, production cutover, any staging data deletion.
5. **Blocked until independently implemented and tested:** Phase 5 Render disaster recovery. The 15-minute target and production readiness cannot be claimed yet.
