# FarmCraft Phase 3 PostgreSQL provisioning preflight

**Status: previewed, not provisioned.** Branch `azure-primary-phase2` remains local. Render, both Neon projects, the archived 16 qualifiers, Azure evaluator VM and live routes were not changed.

## Exact first approval inventory

| Resource | Proposed value |
| --- | --- |
| Azure subscription | Azure for Students, `edcb16c2-9bcf-4533-8ca0-d182aaac9b70` |
| Resource group | `rg-farmcraft-pgtest-20261011` (new and isolated) |
| Region | Korea Central |
| PostgreSQL Flexible Server | `farmcraftpgtest20261011omk`, PostgreSQL 16, Burstable `Standard_B1ms`, one vCPU |
| Provisioned storage | 32 GiB, autogrow off; 7-day local redundant backup; no HA |
| Database | `farmcraft_test`, empty; no historical copy |
| Network | Public endpoint with a firewall rule for **only** the test client's current IPv4 `103.28.244.78`; no `0.0.0.0` rule or separate public IP resource. Client must use TLS and port 5432. Current IP is rechecked by the deploy script. |
| Logging | Platform metrics only; no paid Log Analytics workspace or diagnostic export in this test. |

The public endpoint is limited to this disposable laptop connectivity test. The later application design uses a separate private-network database and requires a second resource approval. The PostgreSQL password is randomly generated at deployment, temporarily passed as an ARM secure parameter, and stored only as Windows DPAPI-encrypted text under ignored `config/local-profiles/`; it is never committed or displayed. The preview used a different disposable random value, then removed its temporary file.

## Read-only verification

- Subscription enabled; region policy allows Korea Central, Indonesia Central, Malaysia West, Poland Central and UAE North. The PostgreSQL provider is registered. The test group did not exist at preflight.
- Korea Central's catalog lists B1ms and B2s, zones 1–3, PostgreSQL 16 and 32 GiB storage. Current VM quota is 2/6 regional vCPUs and 2/4 DAsv4. Those VM quotas do not prove PostgreSQL provisioning eligibility. `az consumption budget list` returned no budgets.
- `az bicep build` passed for the two eligibility templates and the three Phase 2 staging templates. ARM subscription deployment validation passed. Subscription what-if predicted **four creates only**: the group, server, `farmcraft_test`, and one-IP firewall rule. It predicted no changes to existing resources.
- Server name availability could not be confirmed by a separate API check in this session. The template validation and what-if do not guarantee backend capacity, policy exemption, subscription entitlement, global name availability at deployment time, or a successful PostgreSQL connection. A real creation attempt is the remaining eligibility test.
- The student-credit balance was not exposed through the Azure CLI checks. Before approval, view the remaining balance and expiration in the Azure Sponsorships portal. No actual Azure staging usage or bill has been observed.
- Reviewed the Phase 2 Git diff and the new templates. Credential-pattern hits are parameter names, environment reads, and placeholders; no literal production connection string or secret was found in the changed files. Existing ignored local profiles were not copied or printed.

## Estimated USD retail charges

Public Azure Retail Prices API, Korea Central, 2026-10-11; estimates exclude student benefits, taxes, exchange, bandwidth, excess backup and service-specific billing rounding. Actual billed usage can differ.

| Resource / assumption | 4-hour test | One day | 730-hour month |
| --- | ---: | ---: | ---: |
| B1ms compute at $0.026/hour | $0.104 | $0.624 | $18.98 |
| 32 GiB storage at $0.131/GB-month, prorated | ~$0.023 | ~$0.138 | ~$4.19 |
| **Minimal PostgreSQL test subtotal** | **~$0.13** | **~$0.76** | **~$23.17** |
| Container App 0.5 vCPU/1 GiB, fully active, before free grant; **later gate only** | ~$0.22 | ~$1.30 | ~$39.42 gross (~$34.02 if the full monthly free grant applies) |
| ACR Basic at $0.1666/day; **later gate only** | ~$0.028 | ~$0.167 | ~$5.00 |
| Blob Hot LRS, example 1 GB at ~$0.02/GB-month; **later gate only** | <$0.001 | <$0.001 | ~$0.02 plus operations/egress |
| New VNet, private DNS, public IP, logging | **None created in first test** | **$0 configured** | **$0 configured** |

For the later private staging stack, VNet/subnet traffic, private DNS zone/queries, logs, outbound transfer and any required IP/endpoint resources need a separate quote and approval. The PostgreSQL test's public endpoint does not create a customer-billed public-IP resource. The proposed Container App receives a managed ingress FQDN, not a separately approved static IP. The current evaluator VM, disk and static public IP already accrue their own costs and are outside this new-resource estimate. PostgreSQL storage and any excess backup keep billing when compute is stopped; deleting only the server may leave other separately created resources. The isolated group must be inspected before cleanup.

## Prepared commands (do not run before approval)

Read-only repeat: `pwsh -File .\azure-primary\preflight-postgres.ps1`. It builds the Bicep and runs ARM validate/what-if with a disposable secure preview value.

Creation after explicit approval: `pwsh -File .\azure-primary\deploy-postgres-test.ps1 -Approved -AllowedClientIp 103.28.244.78`. That command creates the isolated resource group, B1ms server, database and single-IP firewall rule through the subscription Bicep. It halts if the current public IP or group state differs.

Inspect after creation: `az resource list --resource-group rg-farmcraft-pgtest-20261011 --output table`. Confirm TLS, a read/write persisted row, SQLAlchemy schema initialization against the **test database only**, pooling and reconnect/restart behavior. Never point Render or existing workers at this server.

Cleanup after separate deletion authorization: first inspect `az resource list --resource-group rg-farmcraft-pgtest-20261011 --output table`; then `az group delete --name rg-farmcraft-pgtest-20261011 --yes --no-wait`. Poll `az group exists --name rg-farmcraft-pgtest-20261011` until `false`, then remove the ignored local test credential file. Do not delete `rg-farmcraft-staging` or any Neon/Render resource. If provisioning fails, inspect the test group for partially created billable resources and present them before any cleanup; Render/Neon continue serving production.

## Phase 4 prerequisites

Record successful server creation, TLS and app-level schema/read-write/reconnect tests, measured billed usage and remaining credit. Then price and request a **new** approval for private Blob Storage, ACR Basic, Container Apps environment/app, managed identities, private networking, logging and Redis sessions. Test that staging deployment with synthetic data before any production cutover.
