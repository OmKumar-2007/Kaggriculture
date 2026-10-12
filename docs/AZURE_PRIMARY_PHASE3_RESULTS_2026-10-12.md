# FarmCraft Phase 3 PostgreSQL test result

Date: 2026-10-12 Asia/Calcutta. Branch: `azure-primary-phase2` (local only). No Render, Neon, evaluator VM, production route, GitHub branch, or competition record changed.

## Credit gate

The user's Azure Education Overview screenshot for the same account as the active Azure CLI subscription showed ₹9,334 available out of ₹9,599, expiring 2027-10-10. This exceeded the preapproved ~$0.13 four-hour PostgreSQL test estimate. The screenshot is a point-in-time balance, not an invoice.

## Created inventory

Subscription deployment `farmcraft-pgtest-create-20261011` succeeded. Only these four approved resources were created in Korea Central:

1. Resource group `rg-farmcraft-pgtest-20261011`.
2. PostgreSQL Flexible Server `farmcraftpgtest20261011omk`: PostgreSQL 16, Burstable Standard_B1ms, 32 GiB, 7-day local backup, autogrow disabled, no HA.
3. Empty application database `farmcraft_test` (subsequently populated only by the schema/probe test).
4. Firewall rule `test-client-only`, start/end IPv4 both `103.28.244.78`.

The server was created 2026-10-11 18:56:36 UTC. The deployment had no VNet, public-IP resource, Blob, registry, Container App, Log Analytics workspace, or worker change. The PostgreSQL password was generated locally, stored as a Windows DPAPI-encrypted file in ignored `config/local-profiles/pgtest-admin.dpapi`, and was not printed or committed.

## Verification

- Deployment succeeded; server reported `Ready`; database and firewall were listed by Azure CLI.
- `require_secure_transport` Azure server parameter was `on`. A client connection using `sslmode=require` reported `pg_stat_ssl.ssl=true`; an attempted `sslmode=disable` connection was rejected.
- `PlatformStore` initialized the FarmCraft SQLAlchemy schema in the **test database**, yielding 21 tables. No historical data was copied.
- A probe row was inserted and read after engine disposal/reconnect. Two simultaneous pooled connections returned successful queries.
- First local smoke runs encountered test-harness errors (module search path, then an unsupported SQL `SHOW` for an Azure control-plane parameter, then a duplicate test argument). Those were corrected locally. The final smoke run passed all checks above.
- After testing, the server was stopped. The first CLI stop request lost its connection before changing state; one retry completed, and a fresh Azure query confirmed `Stopped` at approximately 2026-10-11 19:07 UTC.

## Cost and retention

Azure consumption usage for 2026-10-11 through 2026-10-12 returned no line item for the test server at report time; no observed bill is claimed. Retail estimate: B1ms $0.026/hour plus 32 GiB storage at about $4.19 per 730-hour month, roughly $0.032/hour while running, $0.76/day or $23.17/month if continuously running. The active test lasted roughly 10 minutes, but billing granularity and credits may change the eventual charge. **Compute billing stops while Stopped; storage and any excess backup continue** at an estimated ~$4.19/month. Azure automatically starts a stopped Flexible Server after seven days, so deletion or a fresh cost decision is needed before approximately 2026-10-19 00:37 IST. The exact restart time and actual bill must be checked in Azure.

## Next decision

No deletion has been performed. The user requested separate approval before deleting the test group or provisioning anything else. For cleanup, first inspect `az resource list --resource-group rg-farmcraft-pgtest-20261011 --output table`, then after explicit deletion approval run `az group delete --name rg-farmcraft-pgtest-20261011 --yes --no-wait`, wait until `az group exists --name rg-farmcraft-pgtest-20261011` returns `false`, and remove the local encrypted test credential. Do not touch `rg-farmcraft-staging`.

Before a future Azure application deployment, obtain a separate itemized quote and approval for private networking, Blob, ACR Basic, Container Apps, identities, logs, Redis sessions, and synthetic staging tests. Render and Neon remain authoritative.
