# FarmCraft Phase 4 staging preflight — approval pending

Date: 2026-10-12 Asia/Calcutta. Branch: `azure-primary-phase2` (local only). **No Phase 4 resource has been provisioned.** Render, both Neon projects, the Azure evaluator VM, production branches, and competition records remain untouched.

## Scope and preview

The active subscription is Azure for Students `edcb16c2-9bcf-4533-8ca0-d182aaac9b70`. The Phase 3 B1ms test in Korea Central succeeded and its server remains stopped in `rg-farmcraft-pgtest-20261011`. That group is separate and still incurs storage charges. The last verified credit balance was the user's 2026-10-11 Azure Education screenshot: ₹9,334 available, expiring 2027-10-10. Recheck credit immediately before any later create.

`az bicep build` passed for `foundation.bicep`, `postgres.bicep`, `app.bicep`, and `phase4-sub.bicep`. `az deployment sub validate` succeeded. `az deployment sub what-if --result-format ResourceIdOnly` showed **13 creates, zero modifies and zero deletes** in the new group `rg-farmcraft-azure-staging-20261012`:

1. The resource group.
2. VNet `fcstg-vnet` (10.42.0.0/24), with delegated `container-apps` /27 and `postgres` /28 subnets.
3. Private DNS zone `private.farmcraft.postgres.database.azure.com`.
4. DNS link `fcstg-vnet-link`.
5. ACR Basic `fcstg6chsyox4t2zfa`.
6. User-assigned pull identity `fcstg-pull`.
7. ACR Pull role assignment for that identity.
8. Standard LRS StorageV2 account `fcstg6chsyox4t2zfa` (same string is valid across a different Azure provider).
9. Blob service.
10. Private `private-artifacts` container.
11. Container Apps Consumption workload-profile environment `fcstg-environment` with external ingress capability.
12. PostgreSQL Flexible Server `farmcraftstgpg20261012omk`, version 16, Standard_B1ms, 32 GiB, 7-day local backup, no HA, no public database access.
13. Database `farmcraft`.

Items 8–10 are one storage account with nested resources. Azure may automatically place public IP and load-balancer resources in a managed `ME_` group for the Container Apps VNet environment; the ARM what-if does **not** enumerate those. The preview does not include a Container App, image, Log Analytics workspace, worker, Redis, NAT Gateway, private endpoint, or any production routing change.

The storage container denies anonymous access, the account requires TLS 1.2 and disables Shared Key, and the future app identity is intended to receive Blob Data Contributor only at container scope. The storage **endpoint itself remains publicly reachable** in this low-cost template, with Entra authorization required. A truly private storage endpoint would require additional private endpoint/DNS resources and a new costed approval. The registry also has a public endpoint with admin user disabled; a private registry endpoint would be a separate costed design.

## Cost planning (USD retail estimate; not observed charges)

Korea Central Azure Retail Prices API values checked on 2026-10-12: B1ms $0.026/hour, PostgreSQL 32 GB storage $0.131/GB-month ($4.19/month), ACR Basic $0.1666/day, Hot LRS blob storage about $0.02/GB-month, Container Apps 0.5 vCPU active $0.000024/vCPU-second and memory $0.000003/GiB-second. Global meters show Standard static IPv4 $0.005/IP-hour and a Standard Load Balancer base rule $0.025/hour. The Container Apps environment's external VNet path may generate two IPs and one load balancer. The first 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests per subscription-month are free on Container Apps Consumption, shared with other apps on the subscription; unused allowance is not guaranteed. The phase-4 app defaults to zero minimum replicas.

| Proposed recurring component | Approximate rate | Four hours | One day | 730-hour month |
| --- | ---: | ---: | ---: | ---: |
| PostgreSQL B1ms compute + 32 GiB storage | $0.0317/h | $0.13 | $0.76 | $23.17 |
| ACR Basic | $0.1666/day | up to $0.17 billing-day allowance | $0.17 | $5.07 |
| Two managed Standard public IPs, if allocated | $0.010/h | $0.04 | $0.24 | $7.30 |
| One managed Standard load balancer, if allocated | $0.025/h | $0.10 | $0.60 | $18.25 |
| **Planning subtotal, before usage** | **~$0.074/h** | **~$0.44 including one ACR day** | **~$1.77** | **~$53.8** |

Add private DNS zone/query charges, Blob GB/operations, registry storage beyond included capacity, network transfer, and any logging. The template does not create Log Analytics or an app; those lines have no baseline in this first preview. A later always-active 0.5 vCPU/1 GiB app could add about $0.054/hour before the subscription's monthly free grant, or roughly $34 for the 630 hours after a fully available 100-hour-equivalent free grant. This is a scenario, not an approved deployment. The Phase 3 stopped server separately retains about $4.19/month of storage and may automatically restart after seven days unless separately deleted. Student credit may offset billed charges, but retail estimates are not an invoice or guarantee against charges.

## Read-only verification and limits

`Microsoft.App`, `Microsoft.ContainerRegistry`, `Microsoft.Storage`, `Microsoft.Network`, and `Microsoft.DBforPostgreSQL` are registered. The subscription policy `sys.regionrestriction` explicitly includes `koreacentral` among five permitted regions; another `SecurityCenterBuiltIn` assignment is present. The Korea Central PostgreSQL capability listing includes `Standard_B1ms`, version 16, and 32 GiB storage. Azure documents /27 as the minimum Container Apps workload-profile subnet and /28 as the minimum private PostgreSQL delegated subnet. Phase 3 established B1ms eligibility in Korea Central, but it did not prove quota for a **second** simultaneous Flexible Server. Provider registration, policy, and ARM validation cannot guarantee regional capacity or that the managed Container Apps environment can be created on this Students subscription. Storage and registry name availability should be rechecked immediately before provisioning; what-if alone is not a global-name reservation.

The name prefix was shortened from `farmcraftstg` to `fcstg`, because the old storage-account expression exceeded 24 characters. The staging app template was changed to PostgreSQL-backed sessions and queue with minimum replicas zero, avoiding production Redis credentials and idle application compute. These local edits are not deployed. The application and private database connectivity must be verified only after the separately approved infrastructure exists. No official competition jobs are included.

## Proposed create and cleanup operations (not executed)

Preflight: `powershell -ExecutionPolicy Bypass -File azure-primary/preflight-phase4.ps1`.

After **separate explicit approval** and a fresh credit, quota, policy, and name check, generate a unique database password in protected local storage and pass it as a secure ARM parameter. The exact create operation is `az deployment sub create --name farmcraft-phase4-foundation --location koreacentral --template-file azure-primary/phase4-sub.bicep --parameters @<locally-protected-parameters-file>`. The file must contain only staging values and must stay outside Git; the deployment must be inspected for partial resources if it fails. The command above is a template, not runnable until the secure parameter file has been generated.

Before any cleanup, inventory with `az resource list --resource-group rg-farmcraft-azure-staging-20261012 --output table` and inspect any managed Container Apps group. Cleanup requires **another explicit approval**: `az group delete --name rg-farmcraft-azure-staging-20261012 --yes`, then confirm the group and associated managed resources are gone. Do not delete the separate Phase 3 group as part of this operation.

## Approval boundary and subsequent work

The immediate approval would cover only the 13 listed ARM creates plus Azure-managed IP/load-balancer dependencies and their ongoing costs. It would not authorize deployment of `app.bicep`, an image, a worker, a private storage endpoint, a live cutover, or deletion. After infrastructure verification, separately preview the combined UI/API app with a pinned image digest and new staging-only credentials; then request approval for that application deployment and its cost. Render and Neon remain the active production stack throughout.
