# FarmCraft final 50-bot Azure staging rehearsal

Date: 2026-10-13 IST (2026-10-12 UTC)

Target: Azure staging API, `farmcraft-staging-api`

Result: **CONDITIONAL GO** for the event, subject to the readiness conditions below.

## Confirmed end-to-end outcome

| Check | Observed result |
| --- | ---: |
| Supplied bot files / matching manifest SHA256 | 50 / 50 |
| Local authoritative-engine completion smoke | 50 / 50 |
| Accounts created and bots uploaded/validated on Azure | 50 / 50 |
| Concurrent official submissions accepted | 50 / 50 |
| Request-start spread across the 50 independent sessions | 0.0125 s |
| Round 1 official jobs / real games | 50 / 50; 300 |
| Failed, timed-out, cancelled jobs | 0 |
| First-attempt completions | 50 / 50 |
| Round 1 job window | 518 s (8m 38s) |
| Round 1 full replay audit from burst start | 891 s (14m 51s) |
| Round 2 matches / real games | 15 / 30 |
| Round 2 tournament job window | 171 s (2m 51s) |
| Readable replay, analytics, and frame checks | 330 / 330 |
| Persisted and independently checked champion | `LOAD50_20261013_026` |

The full harness from first account preparation through Round 2 verification took 1,163 seconds (19m 23s). The 15-minute Round 1 execution target passed: 518 seconds versus 438 seconds measured for 30 teams in the previous rehearsal. Full replay auditing and bracket launch used nearly the entire 15-minute window, leaving about nine seconds of headroom from submission burst to completion of the 300-replay audit. This is **not** a reliable margin for an event with live participants or slower network conditions.

## Score and bracket integrity

Each Round 1 rating was independently recomputed from its six raw game records using the frozen evaluation configuration. The 50 standings entries were checked against those ratings and the server's deterministic sort order: rating, win rate, average money differential, average final money, case-folded team name, then submission ID. All 15 bracket match scores were recomputed from their game legs, and the final winner matches the persisted champion.

The previous 30-team rehearsal had all 30 ratings saturated at 1000. Here there were **31 distinct ratings**, from 94.8033 to 657.8088, and none at 1000. Ties remain possible; the listed tie-break fields determine their order. The supplied 50 bots use ten strategy families with five variants each. Their one-game local engine scores had 30 distinct values. These synthetic strategies do not establish how real contestants will rank.

## Queue and worker behavior

- Four Azure worker identities were healthy before the burst. A separate live reference-bot smoke job completed on `farmcraft-id-02` and persisted its result.
- Round 1 jobs by worker: `farmcraft-kr-01` 13, `farmcraft-kr-02` 13, `farmcraft-id-01` 12, `farmcraft-id-02` 12.
- Queue wait: median 236 s, P95 445 s, maximum 485 s. Job execution: median 35 s, P95 37 s, maximum 43 s.
- The Round 1 collector recorded 32 queue/worker snapshots with zero collector errors and up to four busy slots. The Round 2 collector recorded 21 snapshots with zero errors; the tournament orchestration job used one slot.
- Azure Monitor returned 28 one-minute CPU readings for each VM. Peak observed average CPU: 33.505% on `farmcraft-eval-02`, 26.815% on `farmcraft-eval-03`.
- Two host samples during/after Round 1 showed roughly 675–833 MiB used of 15,939 MiB RAM. Root disk had about 27 GB free on VM 02 and 25 GB on VM 03. Both worker services were active, with zero systemd restarts in the observed sample. These are sampled values, not peak RAM or disk utilization.

## Backup, reset, and cost

Before the test, 16 explicitly approved disposable staging accounts and their completed tournament were captured in a private Blob snapshot. After the 50-team tournament, a second private snapshot containing the 50-team results was uploaded, read back, and SHA256-verified. A full restore into a separate database was not performed. The guarded reset removed only the 50 expected rehearsal teams and their owned competition records. Three reference bots, eight remote worker identities, ten worker registrations, and the Admin audit history were preserved. The final API check showed `SETUP`, `MAINTENANCE`, zero contestants, and zero active jobs.

The two existing VM sizes are Standard D4s v4 in Korea Central and Standard D4as v4 in Indonesia Central. The [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) returned US$0.236/hour and US$0.216/hour, respectively, for Linux consumption pricing, or **US$0.452/hour combined** while both run. Based on the observed start times and deallocation evidence, incremental VM compute for this rehearsal is estimated at **less than US$0.26**. A three-hour event would project to US$1.356 in VM compute at the same rates. See [the cost report](FARMCRAFT_LOAD50_COST_REPORT.md) for the timing and limits. Managed disks, reserved public IPs, PostgreSQL, Container Apps, Blob, and other baseline services may continue to incur charges. Azure billed usage is not yet available; [Cost Management data can arrive later and can be rerated](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/understand-cost-mgt-data).

## Event readiness

**CONDITIONAL GO.** The real Azure evaluation pipeline, queue, four workers, 330 games, replay artifacts, scoring, and seeded tournament completed without job failures. Before opening the event, start the two existing VMs using the [four-worker guide](../docs/FARMCRAFT_FOUR_AZURE_WORKERS.md), confirm fresh four-slot heartbeats, verify the current student credit balance, and perform a signed-in contestant/Admin browser check for upload and replay. The 15-minute window has only a small margin if it includes the exhaustive 300-replay audit; parallelize that audit or allow more time for final publication. Keep gates in maintenance until the organizer deliberately opens registration.

## Evidence files

- `FARMCRAFT_LOAD50_SUBMISSIONS.csv` — 50 jobs, worker assignment, attempts, queue/runtime, request timestamps.
- `FARMCRAFT_LOAD50_ROUND1_GAMES.csv` — 300 raw game results.
- `FARMCRAFT_LOAD50_STANDINGS.csv` — 50 scored standings rows.
- `FARMCRAFT_LOAD50_BRACKET.csv` — 15 match results.
- `FARMCRAFT_LOAD50_REPLAYS.csv` — 330 replay checks.
- `FARMCRAFT_LOAD50_WORKERS.csv`, `FARMCRAFT_LOAD50_ROUND2_WORKERS.csv`, `FARMCRAFT_LOAD50_AZURE_VM_CPU.csv` — observed utilization.
- `FARMCRAFT_LOAD50_COST_REPORT.md` — cost timing and estimate.

Session and backup evidence stays in ignored `FarmCraft_50_Final/private-evidence/`; no credentials or participant cookies are committed.
