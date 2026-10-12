# Azure primary staging package

Phase 3 begins with the separately priced, disposable PostgreSQL test in
`postgres-eligibility-sub.bicep` and `postgres-eligibility.bicep`. Run
`preflight-postgres.ps1` for read-only ARM validation and what-if. The guarded
`deploy-postgres-test.ps1` is prepared but must not be run before explicit
approval. The inventory, costs and cleanup commands are in
`docs/AZURE_PRIMARY_PHASE3_PREFLIGHT_2026-10-11.md`.

Phase 4 infrastructure and the combined staging app were deployed after two separate approvals. `phase4-sub.bicep` scoped `foundation.bicep` and `postgres.bicep` to the new resource group; `app.bicep` deployed the pinned image after a second approval. See `docs/AZURE_PRIMARY_PHASE4_RESULTS_2026-10-12.md` for actual inventory, verification and cost. `preflight-phase4.ps1` remains a read-only preview; the guarded deployment scripts refuse a second create over existing resources. The existing Azure evaluator VM, Render services, Neon projects and object stores are not inputs to these templates.

Build the existing `azure/Dockerfile` from the repository root. It bundles React into FastAPI under `FARMCRAFT_STATIC_DIR`; use a versioned image digest, not a mutable `latest` tag. Give the app identity **Storage Blob Data Contributor** on this one container. A separate user-assigned identity needs **AcrPull** on this registry.

`app.bicep` requires a private-network-reachable PostgreSQL URL (`postgresql+psycopg://...?...sslmode=require`) and newly generated staging admin secrets. Sessions and queue use the isolated PostgreSQL database, so no production Redis credential is needed. Enter all secrets through secure deployment parameters or a secret store; do not save parameter values in the repository. The preview defaults to zero minimum replicas to avoid idle app compute. Set one warm replica only for a separately approved live event. Test two replicas and database connection limits before raising scale. Set public origin and CORS settings only after the staging URL is known; same-origin traffic works without a separate frontend origin.

Before any deployment, compile all three Bicep files locally. The Azure for Students subscription lists B1ms in Korea Central, but deployment eligibility and regional capacity remain unproven until an explicitly approved create attempt. A read-only Bicep compile is not a deployment.

Readiness checks PostgreSQL sessions and Blob. Liveness checks only process health. A missing dependency keeps the new revision out of service. The first boot initializes schema on the **new empty database**; historical teams, results and objects must not be copied implicitly. Keep the old event archived. No evaluator is provisioned by these templates.

Rollback plan: keep Render deployed. During a future cutover, freeze new official submissions, record queue/attempt state, take a DB and object snapshot, then point clients to Azure after verification. Only one stack may accept writes at a time. For outage failover, stop Azure writes/worker claims first; restore the latest consistent database and matching objects to the backup stack, confirm queued job and official attempt integrity, and only then route traffic to Render. Returning to Azure requires the reverse reconciliation. A running Render app alone is not an independent database backup.
