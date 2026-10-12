# FarmCraft Phase 6/7 — Checkpoint A staging deployment

## Approved scope and execution

The organizer approved Checkpoint A only: push the reviewed `2026.10.12` API image to the existing staging ACR and update only `farmcraft-staging-api`, then verify health and preserve a rollback path. Checkpoint B worker registration, fixture creation, and evaluation are not authorized by this approval.

Before the push, the application diff, container contents and environment configuration were reviewed. The local image excluded `.env`, `config/local-profiles`, and unrelated rehearsal folders; React assets and `config/evaluation.json` were present. The image's evaluation configuration SHA256 was `dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1`, matching the predeployment staging API. The working tree remained uncommitted and unpushed.

The image was pushed as `fcstg6chsyox4t2zfa.azurecr.io/farmcraft:phase67-20261012`, and ACR verified the immutable digest `sha256:e06ac8f8ad38b9ab470931d45ebce83f2870075850c7c4e82e435bff175d8129`. The staging Container App was updated to this digest with `FARMCRAFT_EVALUATOR_VERSION=2026.10.12`. No application secret or database URL was changed. The resulting ready revision is `farmcraft-staging-api--0000002`, receiving 100% of traffic. Previous revision `farmcraft-staging-api--0000001` remains healthy and active with 0% traffic, pinned to digest `sha256:84ae81bbdefb32f4a4e4789aca65b215e401f5f8ee4f1a79601dee07f4d8ee06`.

## Postdeployment checks

| Check | Observed result |
| --- | --- |
| New revision | Healthy; provisioned; 100% traffic |
| `/health` | HTTP 200 |
| `/ready` | HTTP 200; database, sessions, storage all true |
| `/` and `/admin` | HTTP 200; linked JavaScript and CSS both HTTP 200 |
| Worker API | `2026.10.12`; same evaluation config SHA256 as local and prior staging |
| Event | MAINTENANCE; uploads, sandbox, official and tournament flags false |
| Competition | `SETUP`; no qualification started |
| Embedded simulation workers | `SIMULATION_WORKERS=0` |
| Render | Frontend HTTP 200; API ready; worker API remains `2026.10.09` |
| Existing evaluator VM | Still running; no change made |

No staging worker was registered, no test fixture or official job was created, and no competition mode was changed. No Git commit or push occurred. This establishes API deployment health; it is not end-to-end evaluator evidence.

## Rollback

If a later staging-only issue requires rollback, point only `farmcraft-staging-api` back to the old immutable digest and set `FARMCRAFT_EVALUATOR_VERSION=2026.10.09`. Confirm `/ready`, frontend assets and MAINTENANCE afterward. Do not alter Render, Neon, or `farmcraft-eval-01`. The old revision is currently available, and no rollback was needed at this checkpoint.

```powershell
az containerapp update --name farmcraft-staging-api --resource-group rg-farmcraft-azure-staging-20261012 --image fcstg6chsyox4t2zfa.azurecr.io/farmcraft@sha256:84ae81bbdefb32f4a4e4789aca65b215e401f5f8ee4f1a79601dee07f4d8ee06 --set-env-vars FARMCRAFT_EVALUATOR_VERSION=2026.10.09
```

The operation used existing ACR and Container Apps resources, so it created no new fixed-price Azure resource. The additional registry image and transient revision can increase storage/compute usage; actual billed amounts are not yet available from Azure Cost Management.

## Checkpoint B gate

Checkpoint B requires separate approval for a staging-only local worker identity and token, fixture records and Blob objects, a controlled six-game official job, event-control changes, and restoration to MAINTENANCE. The current API lacks an admin-only normal-team creation/upload route while public registration remains closed. A guarded fixture mechanism must be reviewed before the test; opening public registration is outside the proposed scope.
