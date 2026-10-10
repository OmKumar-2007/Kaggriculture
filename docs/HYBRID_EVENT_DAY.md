# FarmCraft hybrid event-day checklist

Use this only after the Render API has passed `/ready` and `/api/remote-workers/version`, the approved Azure VM size has passed a read-only what-if, and one Azure worker has completed real sandbox, official, cancellation, and Round 2 checks. Current status and blockers are in [HYBRID_RENDER_AZURE_PROGRESS.md](HYBRID_RENDER_AZURE_PROGRESS.md).

## Before opening registration

1. Confirm the current Render frontend/API commit, Neon database, object storage, Redis, and Admin login. Do not use the older `my-feature` Neural Coliseum API.
2. Confirm student credit, the approved maximum VM count and duration, Azure quota, and current retail VM, disk, IP, and egress rates. Record a shutdown time and an organizer responsible for it. Azure budget alerts are notifications, not hard caps.
3. Run `powershell -File azure-workers/manage.ps1 -Action Status`; list resource group contents in Azure Portal. Confirm only intended worker resources exist.
4. Start already approved VMs with `-Action Start`, or provision one approved VM from the pushed Git commit. Confirm fresh worker heartbeats, Docker health, version, configuration hash, disk, RAM, and capacity in Admin.
5. Run a small real sandbox match and verify replay, result, and Admin metrics. Confirm the Round 1 reference pool, two seeds, both sides, qualifier count, and one-official-attempt rule before opening submissions.

## During the three-hour event

1. Watch queued sandbox/official jobs, oldest wait, running batches, failed jobs, worker heartbeat age, CPU, RAM, and disk in Admin. A stale heartbeat or failed Docker health is a worker incident.
2. Keep `WORKER_CONCURRENCY=1` per initial VM until a sustained benchmark supports more. Add another approved VM only if quota, measured throughput, and budget permit it. Do not use fake simulation for competition jobs.
3. Keep laptop overflow off unless explicitly enabled. Both worker types use the same server-owned claim/lease protocol; do not switch workers by deleting live job state.
4. For an infrastructure failure, retry the same frozen official job through the Admin retry path. Do not issue a second official submission or mutate reference versions mid-round.
5. Before Round 2, resolve pending or failed Round 1 jobs, freeze qualifiers, inspect BYEs and pairings, then start the bracket. Watch two-leg side swaps and tiebreaks through champion persistence.

## Shutdown

1. Close new submission and evaluation dispatch in Admin; let current jobs settle.
2. Run `powershell -File azure-workers/manage.ps1 -Action Drain`. Verify the worker service exits and queue/lease state is stable.
3. Run `powershell -File azure-workers/manage.ps1 -Action Deallocate`. Verify Azure reports **Stopped (deallocated)** for every VM. Guest shutdown alone does not end compute billing.
4. Record final scores, replays, audit trail, worker logs, measured throughput, Azure runtime, and any failures.
5. Review managed OS disks and static public IPs retained after deallocation. Remove them only through a separately reviewed teardown so no credential or evidence is lost unintentionally.
