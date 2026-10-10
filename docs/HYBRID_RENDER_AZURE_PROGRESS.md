# FarmCraft hybrid Render + Azure progress — 10 October 2026

## Live state

| Component | Current state | Verification |
| --- | --- | --- |
| Render frontend | Existing Free static site `neural-coliseum` is live at https://neural-coliseum.onrender.com. It builds from `frontend/`, and its API rewrites and SPA fallback are configured. | Home and `/admin` return HTTP 200; `/api/remote-workers/version` through the site returns API JSON. |
| Render API | Existing Free web service `neural-coliseum-api` is live on branch `azure-staging-deployment` at commit `6810aeaf199a472780dd68abc1afd20690ac2da2`. Auto-deploy is off. | `/health` returns 200; `/ready` returns 200 with database, Redis, and storage true; evaluator version and config hash match the VM checkout. |
| Neon | Free Singapore PostgreSQL project `farmcraft-control-plane` and private S3-compatible bucket `farmcraft-uploads` are connected to the API. | Live readiness checks and successful replay uploads. Credentials are only in Render settings. |
| Upstash | Free Singapore Redis database `farmcraft-sessions` is connected to the API. | Live readiness check and organizer login/session round trip. |
| Organizer access | A fresh password hash and session secret are configured in Render; login and session through the static-site rewrite both returned HTTP 200. | Secret values are not stored in Git or this document. |
| Azure evaluator | Existing `farmcraft-eval-01` Standard_D2as_v4 Ubuntu VM is **running** in Korea Central. The `rg-farmcraft-staging` group contains its VM, OS disk, NIC, static public IP, VNet, and NSG. | Azure Run Command confirmed checkout `6810aea`, `cloud-init` done, Docker 29.1.3, and active `farmcraft-worker.service`. |
| Worker registration | One worker is registered, idle, and heartbeating with healthy Docker and 1 concurrent game capacity. | Render Admin API reports a fresh heartbeat; server capacity was corrected from 2 to 1 to match VM telemetry. |
| Real sandbox jobs | Two Azure-run sandbox jobs completed. Two older jobs failed: one replay file permission error and one replay upload size error. The gzip replay transfer fix is now live. | Admin job list and VM journal. The dashboard's aggregate `CRITICAL` state reflects those historical failures; dependencies and queues are healthy. |
| Official and tournament evaluations | Not yet verified on this Azure VM. | No claim of end-to-end competition readiness until real official and Round 2 jobs pass. |

The static site is live at commit `5e5925f`; the API and Azure checkout are at `6810aea`. The later commit changes evaluator replay transport, not frontend assets. `render.yaml` is kept as a configuration reference for the **existing** services. The Dashboard settings are authoritative until a Blueprint is explicitly attached. Do not apply this file as a new Blueprint without checking how Render will reconcile the existing service IDs.

## Review and local verification

- Repository branch: `azure-staging-deployment`; the live API and VM commit at the time of this review is `6810aea`. The current review edits in `azure-workers/`, `render.yaml`, `tests/`, and this document have not yet been deployed to Render or copied to the Azure checkout.
- The hybrid control plane stays on Render with PostgreSQL queues, Neon object storage, and Upstash sessions. The Azure VM only runs outbound evaluator requests; it has no database or storage credentials and no inbound application port.
- Local suite: `python -m pytest -q` passed **81 tests, 2 skipped** before the added gzip replay HTTP regression assertion; the focused remote-worker suite then passed **6 tests**. Frontend ESLint and Vite production build passed.
- The gzip upload path caps compressed input at 8 MiB and decompressed JSON at 32 MiB. The new regression assertion covers a valid compressed replay and invalid gzip data. A full real official and Round 2 run remains necessary.
- The Azure manager's SKU restriction check was corrected and its default API URL now matches the live service. The VM status script no longer calls an unsupported `cloud-init --short` option. These small local fixes require a pushed commit before they can be used from a fresh checkout.
- The local `azure-workers/manage.ps1.bak` is an untracked backup from earlier work and is intentionally outside the deployment commit.
- The retired full-Azure templates remain under `azure/` for reference. `azure/deploy.ps1` requires `-LegacyFullAzure` and is not called by `START_FARMCRAFT.bat`. Azure Batch and Container Apps Jobs were considered; the existing Docker controller fits a dedicated VM with less scheduling change.
- A registration and sandbox claim/result/replay path is Azure-deployed and verified. Official submission and Round 2 paths have local tests, but no live Azure proof yet. The two completed sandbox jobs are too few to measure sustained throughput or p95 latency.
- The current Docker isolation uses no contestant network, a read-only root, non-root UID, CPU/RAM/process limits, dropped capabilities, and timeouts. A dedicated VM still shares its kernel with contestant containers; the controller's Docker access is effectively host-level access. Worker registration briefly passes a single-use token through a protected Azure Run Command parameter on the organizer machine.

## Cost and operational gate

The VM is **currently running and billable**. No second VM was created during this review. Its public retail estimate from the earlier pricing check was about **$0.118/hour** for compute, plus the managed OS disk and static IP; actual student credit and invoice impact were not verified in this review. Deallocating stops VM compute charges, while disk and IP remain chargeable. The existing launcher supports drain, status, and deallocate. Do not provision or scale additional Azure capacity without an approved budget and a fresh quota/price check.

Earlier public-rate planning estimates for one VM, including prorated disk and IP, were approximately **$0.125 for one hour**, **$0.375 for a three-hour event**, **$0.50 for a four-hour rehearsal**, and **$3.00 if left running for 24 hours**. They exclude egress, transactions, taxes, and any effect of student credits. For 100 teams, 5 references × 2 seeds × 2 sides require 2,000 real games; 10 references require 4,000. Finishing Round 1 in 180 minutes requires 11.1 or 22.2 games per minute across the pool before Round 2 and reserve. The current two-game live sample cannot establish that capacity; do not scale from it.

## Remaining work

1. Run one real official evaluation and one Round 2 match in an isolated competition state; verify frozen source hashes, scores, replays, and admin visibility. Do not use fake simulation.
2. Exercise cancellation, lease expiry/reclaim, worker restart, and duplicate result handling against the live Azure worker. Record measured CPU/RAM, mean/p95 match time, and sustained games per minute before sizing for 100 teams in three hours.
3. Investigate Render API 502 responses observed during deploy transitions and confirm they do not recur under normal job traffic.
4. Keep the VM running only while evaluation work is needed. Drain and deallocate at the event end; verify Azure power state and remaining disk/IP resources.

Read-only status commands from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File azure-workers/manage.ps1 -Action Status
Invoke-RestMethod https://neural-coliseum-api.onrender.com/ready
Invoke-RestMethod https://neural-coliseum-api.onrender.com/api/remote-workers/version
```

For an approved shutdown, use `-Action Drain`, verify that active jobs have finished with `-Action Status`, then use `-Action Deallocate`. Do not deallocate during a live job.
