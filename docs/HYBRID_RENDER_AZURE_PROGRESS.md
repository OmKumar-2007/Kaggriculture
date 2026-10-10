# FarmCraft hybrid Render + Azure progress — 10 October 2026

## Status by checkpoint

| Checkpoint | State | Evidence and remaining gate |
| --- | --- | --- |
| Repository recovery | Done | Branch `azure-staging-deployment` at `fa5e7cf`; previous uncommitted competition, session, frontend, and Azure code preserved. |
| Existing service audit | Partly verified | Render workspace has `neural-coliseum` static site and `neural-coliseum-api` Free web service on branch `my-feature`. Static site returned HTTP 200. API root returned HTTP 200 with the older Neural Coliseum message; `/ready` and `/api/remote-workers/version` returned 404. API event history includes a 512 MiB OOM restart; hourly memory metric reached about 416 MiB near that incident. Actual Neon, S3-compatible storage, and Upstash connectivity is unverified. Blueprint `render.yaml` describes `farmcraft-free-web` and `farmcraft-free-api`, but those services do not appear in the inspected workspace. |
| Azure resource audit | Done | `rg-farmcraft-staging` contains no resources. `Microsoft.Compute` was registered without creating a resource. Total regional quota is 6 vCPUs in both UAE North and Korea Central; Korea's Dasv4 family quota is 4 vCPUs. Family quota does not guarantee live capacity. |
| Competition correctness | Implemented and locally tested | One official Round 1 claim per team and round is atomic; infrastructure retry uses the same job and frozen source. Existing Round 2 seeding, BYEs, two-leg results, and recovery remain. No live Render deployment of these changes. |
| Worker protocol | Implemented and locally tested | Outbound registration, heartbeat, atomic claim, source hash checks, Docker match, result and replay upload, cancellation, telemetry, and lease recovery existed; added a graceful local drain marker. |
| Azure VM worker path | Templates and scripts implemented | `azure-workers/worker.bicep`, cloud-init, managed registration, lifecycle commands, and read-only plan. Bicep compiles. No Azure VM has been created; no Azure-hosted real match has run. |
| Organizer launcher | Implemented and statically checked | Root `START_FARMCRAFT.bat` now reaches hybrid menu for Render + Azure, Render + laptop, mixed, local, status, benchmark, isolated load, and cost. PowerShell parser reported no errors. Old full-Azure manager is preserved under `deployment-manager.legacy-full-azure.ps1`. Interactive operation against a live Azure VM remains untested. |
| Local automated tests | Passed | `python -m pytest -q`: **81 passed, 2 skipped**. Docker daemon was unavailable, so no new real-match benchmark was run. Previous isolated E2E report is in `docs/E2E_TEST_REPORT_2026-10-10.md`; it does not prove Render/Azure operation. |
| Azure deployment preview | Passed for a different allowed region | Bicep local compile passed. UAE North D2s v3 and B2ms what-if previews failed `SkuNotAvailable`; D2as v5 reports `NotAvailableForSubscription`. Poland Central D2as v4 also failed capacity. **Korea Central D2as v4 what-if passed**, proposing VM, NIC, NSG, public IP, and VNet only. No resources created. |
| End-to-end hybrid verification | Pending | Requires reviewed code pushed and deployed to existing Render services, a compatible `/ready` API, approved Azure budget, VM provisioning/registration, real-match and failure tests. |

## Architecture decision

Use a dedicated Ubuntu VM with Docker, one concurrent match initially. The VM has outbound HTTPS access and no inbound NSG rule. Render remains authoritative for jobs and scores. Keep Neon PostgreSQL, existing S3-compatible object storage, and Upstash Redis if live readiness checks confirm them. Azure Batch would duplicate scheduling, and Azure Container Apps Jobs cannot host the current privileged Docker controller unchanged ([Batch jobs](https://learn.microsoft.com/en-us/azure/batch/jobs-and-tasks), [Container Apps restrictions](https://learn.microsoft.com/en-us/azure/container-apps/containers)). No Azure database, Blob storage, registry, web app, or Container Apps service is part of the active plan.

## Worker sizing and costs

For 100 teams, five references × two seeds × two sides means 2,000 games; ten references means 4,000. To finish Round 1 in 180 minutes, the whole worker pool must sustain **11.1** or **22.2 games/minute** respectively, before Round 2 and operational slack. The previous `load_tests/results/real_benchmark.json` contains only two games per concurrency level on a 4-logical-CPU, 7.65 GiB local host and cannot establish Azure throughput. Measure at least mean, p95, failures, CPU/RAM, startup overhead, and sustained games/minute on one Azure VM before selecting a pool size. With observed per-VM sustained rate `r`, useful window `T` minutes, and utilization reserve `u`, required VMs are `ceil(games / (r*T*u))`, further limited by approved quota and budget.

The selected read-only candidate is **Standard_D2as_v4 in Korea Central**: 2 vCPUs, 8 GiB RAM, one concurrent match initially. The Azure Retail Prices API returned **$0.118/h** for Linux VM compute, **$1.536/month** for a 32 GiB Standard HDD managed disk, and **$0.005/h** for a Standard static IPv4. Rates are USD public retail, not an account invoice or guarantee of student-credit coverage. The family quota permits at most two such VMs in Korea Central at present, subject to capacity. The student credit balance is unknown. [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices), [Dasv4 specifications](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dasv4-series), [VM states and billing](https://learn.microsoft.com/en-us/azure/virtual-machines/states-billing).

For **one Korea Central D2as v4 VM** at these public rates: 1-hour test ~$0.125 including prorated disk and IP; 3-hour event ~$0.375; 4-hour full rehearsal ~$0.50; accidental 24 hours ~$3.00, before transactions, egress, taxes, and other charges. Two VMs roughly double these direct charges. Keeping disk and public IP for 30 idle days adds roughly **$5.19** even if compute is deallocated. These are budget illustrations, not an approval request to provision. Actual VM rate and student credit must be rechecked before any billable action.

## Security and operational limits

The worker holds only its scoped Render worker credential and no database, Azure subscription, or object-store secret. Registration uses a protected Azure Run Command parameter, then deletes that Run Command resource. The token can briefly appear in the organizer's local CLI process arguments. The dedicated VM's Docker group effectively has root-level host power; untrusted containers share the host kernel. No public worker API or SSH ingress is open. Docker applies no network, non-root execution, read-only root, CPU/RAM/process limits, dropped capabilities, and timeouts. Stopping a guest OS alone is not enough to stop compute billing; deallocate in Azure. Disk and public IP charges remain until those resources are removed.

## Legacy Azure code and changed files

`azure/control-plane.bicep`, `azure/database.bicep`, `azure/application.bicep`, `azure/Dockerfile`, and related profiles are retained for reference. `azure/deploy.ps1` is guarded behind `-LegacyFullAzure` and is absent from the launcher. Active new code is in `azure-workers/`, `farmcraft-evaluator/scripts/deployment-manager.ps1`, `farmcraft-evaluator/app/worker.py`, the root BAT launcher, and the Admin worker view. Earlier uncommitted competition/session changes remain in `backend/`, `migrations/`, `frontend/`, and `tests/`. No changes were pushed during this work.

## Next commands and gates

1. Recheck the Korea Central D2as v4 candidate with `powershell -File azure-workers/manage.ps1 -Action Plan` just before deployment; its read-only what-if passed today, but live capacity can change. No subscription upgrade is planned.
2. Review and commit the preserved working tree, push a branch, and update the **existing** Render static site and API to the matching commit. Configure its Neon/S3/Upstash secrets without printing them. Confirm `/ready` and `/api/remote-workers/version` and inspect Render events after deployment.
3. Recheck student credit and public VM/disk/IP rates, set a one-VM time/budget cap, and obtain explicit approval for billable provisioning.
4. With approved SKU: `powershell -File azure-workers/manage.ps1 -Action Provision -Size <sku> -GitRef <pushed-sha> -ApiUrl https://<current-api>.onrender.com`.
5. Issue a one-use token in Admin, run `-Action Register`, and confirm a fresh heartbeat. Run one real sandbox, official, and Round 2 path, then crash/lease/cancel/hash/duplicate-result tests in an isolated event state.
6. Benchmark sustained real games on the VM. Use the measured rate to size 2,000 or 4,000 games plus Round 2, subject to Azure quota and an approved cost cap. Run the 100-user HTTP test only against the isolated port-18000 stack.
7. At event end: `-Action Drain`, wait for service exit, `-Action Deallocate`, then verify Azure power state and remaining disk/IP charges.
