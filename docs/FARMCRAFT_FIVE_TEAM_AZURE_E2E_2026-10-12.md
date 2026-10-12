# FarmCraft Azure staging: five-team end-to-end rehearsal

Date: 2026-10-12. Scope: the isolated Azure staging application only. The existing Render services, Neon databases, and `farmcraft-eval-01` were not changed.

## Outcome

| Check | Result |
| --- | --- |
| Worker startup | Four registered workers started with evaluator version `2026.10.12` and configuration hash `dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1`. |
| Five contestants | Five distinct accounts and five distinct strategy-family bots uploaded and validated. Cross-team Bot Lab access returned 403; invalid file type returned 400. |
| Sandbox | Five real jobs completed, one per contestant. |
| Round 1 | Five concurrent official submissions completed on their first attempt, six games each: 30 completed games and 30 unique replay objects. Scores were recomputed from game records and matched the submitted results and standings. All 30 replay analytics and opening frames loaded from private storage. |
| Round 2 | The five qualifiers produced an eight-slot bracket with three byes. Four matches produced eight completed games and eight replay objects. Champion: `E2E_EPSILON_261012`. The final's two legs aggregate to 60,786 versus 48,070. |
| Frontend | Staging landing and `/admin` login pages rendered in the browser. This did not include a visual walkthrough of every authenticated screen. |
| Local regression | `python -m pytest tests/test_sandbox.py tests/test_remote_workers.py -q`: 12 passed. |

The five teams were `E2E_ALPHA_261012`, `E2E_BETA_261012`, `E2E_GAMMA_261012`, `E2E_DELTA_261012`, and `E2E_EPSILON_261012`. The contestant rehearsal completed **43 real games** (five sandbox, 30 official, eight tournament). One additional reference smoke game completed before the contestant run.

Two initial jobs exposed real deployment defects. The first reference job could not write a replay because the systemd private temp namespace was invisible to the Docker daemon. A subsequent tournament job could not write local objects because its systemd path was read-only. Both were fixed, then their replacement jobs completed. The tournament resume did not discard completed games. Four worker identities handled jobs. Five official jobs were submitted concurrently; four occupied available slots while the fifth queued. A 5-, 6-, or 10-job simultaneous execution capacity has **not** been demonstrated.

Staging event controls were restored to `MAINTENANCE` with registration, uploads, sandbox, official evaluation, tournament, and leaderboard visibility disabled. The event remains `TOURNAMENT_COMPLETED`. `qualifierCount` is 5; it cannot be reset to the previous 16 while this completed bracket remains. No staging records were deleted.

## Infrastructure and costs

The new resource group `rg-farmcraft-evaluators-20261012` contains only `farmcraft-eval-02` in Korea Central and `farmcraft-eval-03` in Indonesia Central, their two 32-GiB Standard HDD OS disks, two static Standard outbound public IPs, two NICs, two NSGs, and two VNets. The VMs have no inbound SSH rules. Both VMs were **deallocated** after the rehearsal; their disks, IPs, identities, and installed worker credentials remain. The existing `farmcraft-eval-01` was not stopped.

Azure retail estimates sampled during preflight were US$0.236/hour for D4s v4 and US$0.216/hour for D4as v4. Together with approximately US$0.010/hour for two IPs and US$0.0042/hour for two disks, the estimated incremental running rate was **US$0.466/hour**, before bandwidth, storage transactions, tax, and discounts. The VMs existed for about 2 hours 35 minutes before deallocation, placing a coarse upper-bound estimate near **US$1.21** for that interval. This is **not an actual Azure bill**; posted usage was not yet available. The retained disks and public IPs continue to incur an estimated US$0.0142/hour, about US$0.34/day, until explicitly deleted. Current Azure credit was user reported as ₹9,174 of ₹9,599 before provisioning.

The existing staging storage account also gained a private `worker-bootstrap` container containing digest-checked root modules and a sandbox patch. Each new VM's managed identity received container-scoped `Storage Blob Data Reader`; the deploying user received container-scoped `Storage Blob Data Contributor`. Account key access stayed disabled. Worker credentials were not recreated or committed.

## Evidence and limitations

Detailed private evidence is in ignored local files under `config/local-profiles/`: `five-team-e2e-20261012.json`, `five-team-round1-audit-20261012.json`, and `five-team-round2-20261012.json`. These may contain session material; do not commit or share them. The public report omits secrets and connection strings.

Peak CPU and memory under full load were not measured. The 30-contestant performance rehearsal, fault injection, forced lease fencing, and complete authenticated UI walkthrough were not run. These results establish a working five-team staging path, not a production capacity guarantee. Restart both **new** VMs and check fresh worker heartbeats before further evaluations. Cleanup of the resource group or storage container requires a separate decision because it would remove retained disks and worker installations.

No Git commit, merge, or push was performed.
