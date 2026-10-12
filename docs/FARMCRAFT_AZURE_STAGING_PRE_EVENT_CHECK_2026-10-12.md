# Azure staging pre-event verification — 2026-10-12

## Result: upload and sandbox pass; official Round 1 is blocked

Target: `https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/`. No Render or Neon changes were made.

The Azure API accepted two fresh `agent.py` uploads for the existing isolated rehearsal team `E2E_ALPHA_261012`. Bot Lab advanced from v1 to v3, reported valid source, and a subsequent validation passed. The verification script initially used the wrong version/replay key names; those **test assertions** were corrected. The uploads themselves succeeded.

The two new evaluator VMs were restarted. All four existing worker identities became idle with fresh heartbeats, Docker healthy, and four available slots. The existing `trytemp` sandbox job `f00c64b2-318c-4aed-bfd1-0615c22abeba` completed. A new sandbox job `8b006c7b-4277-4e87-a776-0c44583ecedf` completed on `E2E_ALPHA_261012`, and its replay analytics loaded from private storage. At final check, the API returned `ready`, all three dependency checks were true, Admin system status was `HEALTHY`, and there were zero queued/running jobs.

**Do not hold a new Round 1 on this staging database yet.** Its competition phase is `TOURNAMENT_COMPLETED` from the five-team rehearsal. The event controls initially said `QUALIFICATION` and `officialEnabled=true`, but the actual official submission endpoint returned HTTP 423 because `QUALIFICATION_OPEN` is required. This mismatch was reproduced using the rehearsal account. The user chose to preserve the completed rehearsal and declined a fresh database/storage cutover, so the bracket and data were left unchanged. The reversible event controls were corrected to `DEVELOPMENT`, with registration, uploads, and sandbox still open and official/tournament switches off. Official qualification is not available.

## Scheduled VM stop and cost

Both new VMs remain running temporarily so sandbox jobs can execute. Azure auto-shutdown is enabled for `farmcraft-eval-02` at **14:10 UTC / 19:40 IST on 2026-10-12**. The Azure auto-shutdown resource type is unavailable in Indonesia Central. A local Windows Scheduled Task `FarmCraft-stop-eval-03-20261012` is set for the same time to deallocate `farmcraft-eval-03`; it requires this computer to be on and the user signed in. Verify both VMs are deallocated after 19:40 IST. The Korea auto-shutdown is daily until removed, so it will also affect future manual restarts. Retained disks and public IPs continue to bill after deallocation.

The previous Azure retail preflight estimated about **US$0.45 per running hour for both VM compute** plus disks and static IPs. This is an estimate, not posted Azure usage.

## Checks

- `python -m pytest tests -q`: **105 passed, 2 skipped**.
- `npm run build` in `frontend/`: **passed**.
- Live upload, Bot Lab revalidation, sandbox execution, replay analytics, API readiness, queue, and worker health: **passed**.
- Live official Round 1 submission: **blocked with HTTP 423 by completed competition phase**.

No production branches were pushed or merged. No completed rehearsal records were deleted.
