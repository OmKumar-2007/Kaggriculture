# FarmCraft Phase 4 infrastructure result

Date: 2026-10-12 Asia/Calcutta. The user confirmed Azure for Students available credit of **₹9,334 out of ₹9,599** immediately before provisioning and approved only the itemized Phase 4 infrastructure. Subscription `edcb16c2-9bcf-4533-8ca0-d182aaac9b70` was active with the student spending limit on.

## Deployment and actual inventory

Subscription deployment `farmcraft-phase4-foundation-20261012` succeeded at 2026-10-11 19:36 UTC in Korea Central. The previously absent `rg-farmcraft-azure-staging-20261012` was created. Azure Resource Manager deployed:

- VNet `fcstg-vnet`, with `container-apps` 10.42.0.0/27 delegated to Microsoft.App and `postgres` 10.42.0.32/28 delegated to PostgreSQL.
- Private DNS zone `private.farmcraft.postgres.database.azure.com` and succeeded VNet link `fcstg-vnet-link`.
- PostgreSQL Flexible Server `farmcraftstgpg20261012omk`, version 16, Standard_B1ms, 32 GiB Premium_LRS P4, 7-day local backups, no HA; empty application database `farmcraft`.
- Basic registry `fcstg6chsyox4t2zfa.azurecr.io`, admin user disabled; user-assigned identity `fcstg-pull` with AcrPull on only that registry.
- Standard_LRS storage account `fcstg6chsyox4t2zfa` and private `private-artifacts` Blob container. HTTPS-only, minimum TLS 1.2, anonymous Blob access disabled, Shared Key disabled. The account endpoint is publicly addressable but requires Entra authorization; it does not have a private endpoint.
- Consumption workload-profile Container Apps environment `fcstg-environment`, using the staging VNet and external ingress capability.

Azure also created managed resource group `ME_fcstg-environment_rg-farmcraft-azure-staging-20261012_koreacentral` containing Standard public IP `capp-svc-lb-ip` and Standard load balancer `capp-svc-lb`. These did not appear as individual resources in the ARM what-if and are **ongoing billable dependencies**. One IP was observed, rather than the two-IP planning assumption.

## Verification and limits

- Subscription and nested group deployment states: Succeeded. PostgreSQL state: Ready. Container Apps environment state: Succeeded. Registry state: Succeeded.
- PostgreSQL `publicNetworkAccess=Disabled` and `require_secure_transport=on`; subnet and private DNS IDs point only into the new staging group. The `farmcraft` database is listed.
- Registry has one AcrPull assignment for the staging pull identity. Storage rejects Shared Key by configuration, and the private Blob container is listed through Entra authentication.
- At the infrastructure checkpoint, no Container App, image push, worker, Redis service, Log Analytics workspace, private storage endpoint, or production route had been created. At that point the private database had only control-plane verification. The separately approved app step below subsequently verified database and Blob readiness from inside the VNet. There is still no worker, Redis service, Log Analytics workspace, private storage endpoint, or production route change.
- Render, both Neon projects, the original Azure evaluator VM, GitHub branches, and production competition records were not changed. At final verification, the existing Render frontend returned HTTP 200 and the Render API `/ready` returned HTTP 200 with database, Redis and storage healthy. The Phase 3 test PostgreSQL server remains Stopped in its separate group.

## Cost and retention

Azure consumption usage returned **zero posted line items** for the new group and the managed group at report time. That means billing had not yet appeared; it does **not** mean the deployment is free. With one observed Standard public IP, the revised retail baseline is approximately PostgreSQL B1ms+32 GiB $23.17/month, ACR Basic $5.07/month, IP $3.65/month, and load balancer $18.25/month: **about $50.14 per 730-hour month, $1.65/day, or $0.069/hour**. Add private DNS zone/queries, Blob storage/operations, network traffic, any registry excess, and later application compute. Four hours of baseline resources is approximately $0.28, with ACR day-prorating/billing potentially making the short test closer to $0.44. These are estimates in USD retail pricing, not observed account charges or INR conversions. The separate stopped Phase 3 PostgreSQL server retains estimated storage cost and may automatically restart after seven days; it requires its own deletion decision.

## Approved staging application deployment

The user then gave **separate approval** for the staging app, its image push and Blob role assignment. A local build of the current checkout with `azure/Dockerfile` succeeded. The built image was checked for absence of `/app/.env` and `/app/config/local-profiles`, pushed to the new ACR as `farmcraft:phase4-20261012`, and the ACR manifest digest was verified as `sha256:84ae81bbdefb32f4a4e4789aca65b215e401f5f8ee4f1a79601dee07f4d8ee06`. `az deployment group what-if` with disposable placeholder secrets previewed two creates: Container App `farmcraft-staging-api` and container-scoped Blob Data Contributor role assignment, with eight existing resources ignored. App deployment `farmcraft-phase4-app-20261012` then succeeded. A staging-only PostgreSQL URL, admin password hash and session secret were submitted as secure ARM parameters through an ACL-restricted temporary file; the recoverable admin and session credentials are Windows DPAPI encrypted in ignored `config/local-profiles/`. No password, connection string or session secret was printed or committed.

The app serves at `https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/`. It has 0.5 vCPU and 1 GiB per replica, Consumption minReplicas 0/maxReplicas 2, external HTTPS ingress, PostgreSQL-backed queue and sessions, staging-only admin/session secrets, managed-identity Blob access, and a TLS PostgreSQL connection inside the staging VNet. After the first cold start, `/health`, `/ready`, `/`, and `/admin` all returned HTTP 200. `/ready` reported database, sessions and storage true. A staging admin login, authenticated session check and logout all succeeded. From inside the staging app, an isolated Blob object write/read/delete round trip passed and SQLAlchemy inspected **21 schema tables** while `SELECT 1` succeeded. The new database reported zero contestants, zero submissions, zero qualifiers and `SETUP` phase. The container-scoped Blob Data Contributor assignment exists. The revision is Healthy.

The initial staging event defaulted to DEVELOPMENT with official submissions enabled. Because no evaluator worker is deployed, it was set to **MAINTENANCE** with uploads, sandbox, official, tournament and registration access disabled. The staging app's expected worker count was set to zero; a new revision was healthy, `/ready` remained 200, and admin metrics reported `HEALTHY`, zero teams/jobs, PostgreSQL queue. These settings affected only the empty staging database.

A single continuously active replica costs up to about $0.054/hour of compute beyond any shared Azure Container Apps monthly free grant; at 730 active hours and an untouched 100-hour-equivalent grant, that is about $34/month in addition to the current ~$50/month infrastructure baseline. The app scales to zero when idle, so this continuous-activity scenario is not a forecast. Actual usage depends on traffic, replica count, and remaining subscription grant. No evaluator is part of this step; queued jobs would have no consumer. No load test or official competition job was run. The cost API still had no posted charges for the new groups at the last check.

## Remaining boundaries

There is no approved production cutover, evaluator worker connection, historical data copy, or cleanup. Later load tests or participant registration require a deliberate staging event-mode decision. The public staging URL is for verification; Render and Neon remain the production stack. Deleting either the Phase 3 or Phase 4 resource group requires separate approval.

For later cleanup, first inspect both the staging resource group and Azure-managed `ME_` group. Deletion is not authorized by the current approval and must be requested separately. Do not delete `rg-farmcraft-pgtest-20261011` or `rg-farmcraft-staging` as part of staging cleanup.
