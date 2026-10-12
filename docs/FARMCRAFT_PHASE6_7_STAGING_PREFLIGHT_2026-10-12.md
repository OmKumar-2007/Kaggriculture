# FarmCraft Phase 6/7 Azure staging activation preflight — 2026-10-12

Checkpoint A was subsequently approved and completed. Its observed deployment result is in `docs/FARMCRAFT_PHASE6_7_CHECKPOINT_A_2026-10-12.md`; the preflight values below describe the state before that deployment.

## Deployed links and access

All addresses below were checked with read-only HTTP GET. A 200 response and asset delivery establish reachability, not an end-to-end competition result.

| Surface | Exact URL | Deployment and reachability | Authentication | Contestant access now |
| --- | --- | --- | --- | --- |
| Render contestant frontend | https://neural-coliseum.onrender.com/ | Separate Render static site; HTML 200 | Page public; team session for Bot Lab | Round 1 register/official submit blocked by current `SETUP` phase; other access depends on live event settings |
| Render Admin Control Room | https://neural-coliseum.onrender.com/admin | Same Render static site; HTML 200 | Render admin password, separate from staging | Organizer only |
| Azure staging contestant frontend | https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/ | React is served by the combined Azure API container; HTML and JS/CSS assets 200. No separate Azure Static Web App exists | Page public; team session for Bot Lab | No: MAINTENANCE and `SETUP` |
| Azure staging Admin Control Room | https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/admin | Same combined Azure container; HTML 200 | Staging admin password only; no username | Organizer only |
| Azure staging API base | https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/ | Container App revision `farmcraft-staging-api--0000001` active | Public reads; protected writes require team/admin/worker auth | Mutating competition actions closed |
| Azure `/health` | https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/health | JSON 200 | None | Read only |
| Azure `/ready` | https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/ready | JSON 200; database, sessions and storage true | None | Read only |

The Render API `/ready` also returned 200. The Render leaderboard reports phase `SETUP` at this check, as does Azure staging. Azure `/event/status` reports MAINTENANCE with upload, sandbox, official and tournament flags false. Prior Phase 4 verification recorded staging registration disabled; the public event endpoint does not expose that flag, and no authenticated read was made because login itself writes an audit record.

## Staging Admin password

`/admin` uses one password and no username. The API checks it against `ADMIN_PASSWORD_HASH` and issues an HttpOnly admin session cookie. The original staging password is present in the ignored, Windows DPAPI-protected `config/local-profiles/phase4-admin.dpapi`. A read-only recovery check succeeded under the current Windows account. No reset or rotation is required. It is distinct from Render Admin credentials.

Run this locally in PowerShell from the repository root; it copies the password to your own clipboard and prints only a status message:

```powershell
.\azure-primary\copy-staging-admin-password.ps1
```

Paste it into the Azure staging Admin login, then clear the clipboard. The helper was syntax checked but was not run to place the secret on this session's clipboard.

## Deployment readiness

| Item | Verified state |
| --- | --- |
| Branch | `azure-primary-phase2`; working tree contains earlier modified and untracked Phase 2–4 and rehearsal files; no reset or push |
| Current staging worker API version | `2026.10.09`; configuration SHA256 `dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1` |
| Proposed server/worker version | `2026.10.12`; backend default, worker VERSION and staging Bicep value agree locally |
| Current staging image | `fcstg6chsyox4t2zfa.azurecr.io/farmcraft@sha256:84ae81bbdefb32f4a4e4789aca65b215e401f5f8ee4f1a79601dee07f4d8ee06` |
| Rollback revision | `farmcraft-staging-api--0000001`, active with 100% traffic; restore its pinned image and version `2026.10.09` if the new revision fails |
| Proposed local API image | Built with `azure/Dockerfile` as `farmcraft:phase67-preflight`, local image ID `sha256:e06ac8f8ad38b9ab470931d45ebce83f2870075850c7c4e82e435bff175d8129`; registry digest does not exist until an approved push |
| Evaluator Docker image | Local `nitw-farm-ai-evaluator:2026.10.12` built; not on the Azure VM |
| Database migration | Phase 6/7 changes add no table or column. Existing startup migrations remain; deployment must be checked against staging schema before activation |
| Secrets | Existing Container App secret references for DB/admin/session remain in place. No credential rotation or connection string change is proposed |
| Event | MAINTENANCE; no connected worker; local image keeps `SIMULATION_WORKERS=0` |

The API image includes the local branch's earlier uncommitted application changes. The `.dockerignore` now excludes unrelated rehearsal folders and launcher/reset scripts. Before approval to deploy, review the exact source diff and the final locally built image ID; after approval to push, obtain and verify its ACR digest before updating the app. No image was pushed in this preflight.

### Deployment sequence after separate approval

1. Capture the current revision, image digest, event status and `/ready` result. Stop if they differ from this report.
2. Tag the reviewed local API image with a unique Phase 6/7 ACR tag and push only to `fcstg6chsyox4t2zfa.azurecr.io/farmcraft`. Obtain its immutable registry manifest digest.
3. Update **only** `farmcraft-staging-api` to that digest and set `FARMCRAFT_EVALUATOR_VERSION=2026.10.12`; preserve its database, storage, admin/session secrets, scale limits and `SIMULATION_WORKERS=0`. Azure Container Apps creates a new revision.
4. Wait for `/health`, `/ready`, `/`, `/admin`, static assets and `/api/remote-workers/version`; compare the server configuration hash with the local worker's `config/evaluation.json`. Confirm MAINTENANCE and zero pending jobs before further actions.
5. On failure, update this staging app back to the pinned Phase 4 digest with evaluator version `2026.10.09`, verify `/ready` and MAINTENANCE, and leave any partial ACR tag for reviewed cleanup. Do not change Render or Neon.

No new Azure resource is required for this update. Existing staging PostgreSQL, ACR, Blob, network and Container Apps charges continue. A brief new revision, image storage, Blob transactions, and HTTP/database/network usage can add variable charges. The earlier infrastructure baseline was an estimate of about USD 50.14/month, not a current invoice. [Azure Container Apps billing](https://learn.microsoft.com/en-us/azure/container-apps/billing) describes per-second consumption and shared monthly grants; [Blob pricing](https://azure.microsoft.com/en-us/pricing/details/storage/blobs/) includes storage and operations. Check actual Azure Cost Management after deployment; billing data can lag.

## Isolated local worker plan

The local `prepare-staging-worker.ps1` created an ignored, ACL-restricted profile at `config/local-profiles/staging-worker.env`. Its URL is Azure staging, concurrency 1, heartbeat 15 seconds, polling 8 seconds, 512 MiB/1 CPU/128 PID Docker limits, and image tag `2026.10.12`. The profile parser succeeded. There is no credential file yet, and no worker was registered or started. The existing Azure VM is running and untouched.

After approval, install the evaluator's Python requirements in a dedicated local venv, keep Docker Desktop running, and set these variables in the worker's PowerShell session:

```powershell
$env:FARMCRAFT_WORKER_ENV_FILE = (Resolve-Path .\config\local-profiles\staging-worker.env).Path
$env:FARMCRAFT_WORKER_CREDENTIAL_FILE = (Join-Path (Resolve-Path .\config\local-profiles).Path 'staging-worker.credentials.json')
```

Then enable registration **only in Azure staging Admin**, obtain its 15-minute one-use token, and run `farmcraft-evaluator/.venv/Scripts/python.exe farmcraft-evaluator/app/worker.py --register` from the repository root. The program securely prompts for the token and saves the credential to the separate path. Check `/api/remote-workers/version`, the local config hash and Docker image before starting `farmcraft-evaluator/app/worker.py` normally. After the test, drain the worker, wait for active jobs to finish, stop its process, and revoke the staging identity in staging Admin. No Render worker secret is reused.

## Controlled six-game test plan and blocker

Use three staging-only reference artifacts, one normal staging test team and source version, seed `41021`, sides `[0,1]`, and the existing 720-step evaluator. The admin action supports `openAccess:false`, so the qualification snapshot can freeze three references and one seed without opening public gates. Create the test identity and upload while still behind admin-only staging controls. The current API has no admin-only normal-team creation/upload route; public registration must **not** be opened as a shortcut. A guarded staging-only fixture path or one-time in-container script must be reviewed and approved before the actual run.

After approval: run the three real reference validation jobs; verify they passed and are selected; freeze the snapshot with public access closed; enable only the minimum official submission control for the test team; create one official attempt; observe PostgreSQL job, claim/lease, six Docker games, six distinct Blob replay objects, transactional result, exact score calculation, and Admin job visibility. Then drain/revoke the local staging worker, disable official submissions, and restore MAINTENANCE. Keep records for audit unless cleanup is separately approved. No mocked outcome counts as evidence.

## Approval gate

The following are **not** authorized by this preflight: pushing the API image to ACR; updating the Azure Container App or its evaluator-version variable; creating the staging worker token or identity; changing registration controls; adding references, a test team, submission, job or Blob object; changing qualification phase or event flags; executing a real Azure staging evaluation; or deleting test artifacts. Each writes Azure staging state. Render, both Neon projects, `farmcraft-eval-01`, published production results, and Git remotes remain untouched.

Approval for activation should identify the reviewed image digest after push, authorize only the staging app update and a separate local worker identity, authorize the specific staging fixture records and six-game job, and specify event gate restoration. No new Azure VM or production cutover is proposed.
