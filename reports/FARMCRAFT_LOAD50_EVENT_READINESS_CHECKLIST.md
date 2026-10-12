# FarmCraft event readiness after the 50-bot Azure rehearsal

## Verified on 2026-10-13 IST

- [x] Azure staging API `/ready`: database, sessions, and private storage ready.
- [x] 50 distinct supplied bots matched the manifest SHA256 and passed source validation and one real local Kaggriculture game each.
- [x] Four existing Azure workers handled 50 real official jobs with no failed or timed-out job; a separate reference smoke job persisted.
- [x] Round 1: 300 games and 300 replay/analytics/frame checks; 50 standings recomputed and deterministic ordering checked.
- [x] Round 2: 16 qualifiers, 15 matches, 30 games, champion independently verified as `LOAD50_20261013_026`.
- [x] Post-run private Blob snapshot uploaded and SHA256-verified before cleanup.
- [x] Exactly 50 rehearsal accounts and owned competition rows removed with guarded reset; three reference bots and worker registrations preserved.
- [x] Final competition phase `SETUP`, event mode `MAINTENANCE`, zero contestants, zero active jobs, empty leaderboard.
- [x] `farmcraft-eval-02` and `farmcraft-eval-03` deallocated; four worker registrations rearmed and currently offline.

## Before opening the real event

- [ ] Confirm current Azure for Students credit in the Education Overview; the API did not return a fresh balance for this run.
- [ ] Start the two VMs with [the worker guide](../docs/FARMCRAFT_FOUR_AZURE_WORKERS.md), then confirm four fresh idle heartbeats and one available slot per identity.
- [ ] Run a signed-in browser check for participant registration, upload, official submission status, replay playback, and Admin bracket visibility. This run verified those flows through live APIs; it did not record an independent authenticated browser pass.
- [ ] Decide whether the 15-minute window covers job completion or exhaustive replay audit and publication. Jobs finished in 8m 38s, while the 300-replay audit reached completion 14m 51s after the burst, leaving little margin.
- [ ] Deliberately open the desired registration and qualification gates only when the organizer is ready. All public gates are currently closed.

**Readiness decision: CONDITIONAL GO.** The evaluation and tournament pipeline passed; the four items above require organizer action or an explicit timing decision before the event.
