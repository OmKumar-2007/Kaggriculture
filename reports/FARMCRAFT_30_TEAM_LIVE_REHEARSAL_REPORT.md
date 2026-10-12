# FarmCraft — 30-team live Azure staging rehearsal

Generated: 2026-10-12T15:27:06.180410+00:00
Target: https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io
Source evidence: ignored `config/local-profiles/load30-20261012.json`; live Admin API and worker metrics CSV.

## Outcome

- Participants and distinct uploaded bots: 30.
- Official Round 1 jobs completed: 30/30; failed: 0.
- First-attempt successes: 30/30; jobs needing additional attempts: 0.
- Round 1 audited games and authenticated replay/analytics checks: 180 and 180.
- Round 1 wall time: 438.0 seconds. The 15-minute target: PASS.
- Round 2 observed wall time: 276.73 seconds; total from harness start through Round 2 audit: 1225.0 seconds.
- Round 2 recorded games: 30; matches: 15; champion: LOAD30_20261012_26.
- Four-worker observations: 148 samples across farmcraft-id-01, farmcraft-id-02, farmcraft-kr-01, farmcraft-kr-02; collector errors: 0.
- Maximum Round 1 rating (1000) occurred for 30/30 contestants; this score saturation limits ranking separation and should be reviewed before the real event.
- Overall readiness: CONDITIONAL GO — see limitations below.

## Per-team Round 1 results

| Team | Strategy file | SHA256 prefix | Queue s | Execute s | Games | Rating | Qualified |
|---|---|---|---:|---:|---:|---:|---|
| LOAD30_20261012_01 | MelonCompound variant 1 | `32c4daa3f00e` | 1.0 | 57.0 | 6 | 1000.0 | False |
| LOAD30_20261012_02 | MelonCompound variant 2 | `c42487169d90` | 4.0 | 54.0 | 6 | 1000.0 | False |
| LOAD30_20261012_03 | MelonCompound variant 3 | `f02bf42e4093` | 2.0 | 57.0 | 6 | 1000.0 | False |
| LOAD30_20261012_04 | MelonCompound variant 4 | `de7f4e08b0e9` | 4.0 | 54.0 | 6 | 1000.0 | False |
| LOAD30_20261012_05 | MelonCompound variant 5 | `7ad650899a00` | 121.0 | 49.0 | 6 | 1000.0 | True |
| LOAD30_20261012_06 | BerryCapital variant 1 | `31a59e757ee4` | 60.0 | 47.0 | 6 | 1000.0 | False |
| LOAD30_20261012_07 | BerryCapital variant 2 | `34a017f08cad` | 220.0 | 50.0 | 6 | 1000.0 | True |
| LOAD30_20261012_08 | BerryCapital variant 3 | `96b9b101dfe8` | 107.0 | 52.0 | 6 | 1000.0 | True |
| LOAD30_20261012_09 | BerryCapital variant 4 | `a7dcb0f39b26` | 284.0 | 50.0 | 6 | 1000.0 | True |
| LOAD30_20261012_10 | BerryCapital variant 5 | `dbb393d36374` | 64.0 | 51.0 | 6 | 1000.0 | True |
| LOAD30_20261012_11 | CarrotVelocity variant 1 | `28a9bcd93d67` | 121.0 | 49.0 | 6 | 1000.0 | False |
| LOAD30_20261012_12 | CarrotVelocity variant 2 | `83b72dd25098` | 177.0 | 48.0 | 6 | 1000.0 | False |
| LOAD30_20261012_13 | CarrotVelocity variant 3 | `63e207b610e9` | 282.0 | 47.0 | 6 | 1000.0 | False |
| LOAD30_20261012_14 | CarrotVelocity variant 4 | `6393aa9aab3b` | 60.0 | 50.0 | 6 | 1000.0 | False |
| LOAD30_20261012_15 | CarrotVelocity variant 5 | `2b9910db76dd` | 225.0 | 51.0 | 6 | 1000.0 | False |
| LOAD30_20261012_16 | TomatoPerennial variant 1 | `dc80c23bc567` | 332.0 | 52.0 | 6 | 1000.0 | False |
| LOAD30_20261012_17 | TomatoPerennial variant 2 | `64df2ebce185` | 282.0 | 45.0 | 6 | 1000.0 | False |
| LOAD30_20261012_18 | TomatoPerennial variant 3 | `5df224e2762d` | 386.0 | 50.0 | 6 | 1000.0 | True |
| LOAD30_20261012_19 | TomatoPerennial variant 4 | `3dde9be08260` | 64.0 | 51.0 | 6 | 1000.0 | False |
| LOAD30_20261012_20 | TomatoPerennial variant 5 | `2445e087a92d` | 340.0 | 51.0 | 6 | 1000.0 | True |
| LOAD30_20261012_21 | MarketRotation variant 1 | `0481ce66b474` | 177.0 | 47.0 | 6 | 1000.0 | True |
| LOAD30_20261012_22 | MarketRotation variant 2 | `48a77781f8f4` | 276.0 | 51.0 | 6 | 1000.0 | True |
| LOAD30_20261012_23 | MarketRotation variant 3 | `008cf45f63fb` | 330.0 | 54.0 | 6 | 1000.0 | True |
| LOAD30_20261012_24 | MarketRotation variant 4 | `fd6ee0481506` | 163.0 | 51.0 | 6 | 1000.0 | True |
| LOAD30_20261012_25 | MarketRotation variant 5 | `cffae275f64b` | 225.0 | 51.0 | 6 | 1000.0 | True |
| LOAD30_20261012_26 | PortfolioHedge variant 1 | `6a533966a32b` | 171.0 | 50.0 | 6 | 1000.0 | True |
| LOAD30_20261012_27 | PortfolioHedge variant 2 | `77a1c4d78fcb` | 228.0 | 50.0 | 6 | 1000.0 | True |
| LOAD30_20261012_28 | PortfolioHedge variant 3 | `a946a54ea5ea` | 386.0 | 50.0 | 6 | 1000.0 | False |
| LOAD30_20261012_29 | PortfolioHedge variant 4 | `2aa0429c4fb7` | 330.0 | 54.0 | 6 | 1000.0 | True |
| LOAD30_20261012_30 | PortfolioHedge variant 5 | `8cefa216a82c` | 115.0 | 51.0 | 6 | 1000.0 | True |

## Round 2 matches

| Round | Team A | Team B | Score A | Score B | Winner | Replay IDs |
|---:|---|---|---:|---:|---|---:|
| 1 | LOAD30_20261012_25 | LOAD30_20261012_21 | 53368.0 | 60820.0 | LOAD30_20261012_21 | 2 |
| 1 | LOAD30_20261012_27 | LOAD30_20261012_07 | 52320.0 | 59545.0 | LOAD30_20261012_07 | 2 |
| 1 | LOAD30_20261012_23 | LOAD30_20261012_05 | 52240.0 | 38816.0 | LOAD30_20261012_23 | 2 |
| 1 | LOAD30_20261012_09 | LOAD30_20261012_24 | 55516.0 | 52815.0 | LOAD30_20261012_09 | 2 |
| 1 | LOAD30_20261012_10 | LOAD30_20261012_26 | 54842.0 | 55412.0 | LOAD30_20261012_26 | 2 |
| 1 | LOAD30_20261012_29 | LOAD30_20261012_20 | 51370.0 | 47257.0 | LOAD30_20261012_29 | 2 |
| 1 | LOAD30_20261012_08 | LOAD30_20261012_18 | 60735.0 | 56126.0 | LOAD30_20261012_08 | 2 |
| 1 | LOAD30_20261012_22 | LOAD30_20261012_30 | 60134.0 | 57024.0 | LOAD30_20261012_22 | 2 |
| 2 | LOAD30_20261012_21 | LOAD30_20261012_07 | 58148.0 | 57223.0 | LOAD30_20261012_21 | 2 |
| 2 | LOAD30_20261012_23 | LOAD30_20261012_09 | 60529.0 | 52534.0 | LOAD30_20261012_23 | 2 |
| 2 | LOAD30_20261012_26 | LOAD30_20261012_29 | 55002.0 | 49369.0 | LOAD30_20261012_26 | 2 |
| 2 | LOAD30_20261012_08 | LOAD30_20261012_22 | 55712.0 | 56768.0 | LOAD30_20261012_22 | 2 |
| 3 | LOAD30_20261012_21 | LOAD30_20261012_23 | 57749.0 | 54463.0 | LOAD30_20261012_21 | 2 |
| 3 | LOAD30_20261012_26 | LOAD30_20261012_22 | 61826.0 | 53224.0 | LOAD30_20261012_26 | 2 |
| 4 | LOAD30_20261012_21 | LOAD30_20261012_26 | 51980.0 | 59280.0 | LOAD30_20261012_26 | 2 |

## Timings and capacity

- Execution seconds: min 45.0, median 51.0, p90 54.0, p95 55.65, p99 57.0, max 57.0.
- Queue wait seconds: average 184.57, median 177.0, p95 365.3.
- Peak sampled CPU percentage: 39.4; peak reported RAM bytes: 1113493504. Telemetry definitions follow the worker heartbeat payload.
- Measured Round 1 throughput: 24.66 games/minute.
- Linear Round 1 projections at the observed rate: 60 teams ≈ 14.6 minutes and 100 teams ≈ 24.3 minutes. These assume the same bots and four workers and exclude Round 2, retries, and changing Azure load; they are not capacity guarantees.

## Integrity and limits

- Bot source hashes, server validation, and cross-team Bot Lab denial were recorded.
- Every audited job was recomputed from its six raw game records; distinct replay IDs, analytics, and first/final frame reads were required before bracket launch. Round 2 match-score, replay-frame, and champion audit: PASS.
- Worker CSV captures queue and heartbeat time series; Azure billed usage and complete Docker/OOM telemetry were unavailable through this collector.
- Browser public landing and Admin sign-in rendered. Authenticated Admin UI and contestant replay interactions were not independently exercised in the browser during this run; backend API read checks are separate evidence.
- A separate invalid-source HTTP fixture was not run during this cycle; all 30 valid sources passed server validation and real execution.
- The pre-run private Blob backup was read back and hash-checked, but a full restore into another PostgreSQL database was not performed.
- Cost details are in `FARMCRAFT_30_TEAM_COST_REPORT.md`; see final checklist for the clean event state.
