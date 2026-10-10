# FarmCraft stabilization acceptance targets

Defined before the Azure concurrency and 100-user load runs. Expected validation and authorization 4xx responses are excluded from the server-error target; unexpected 4xx responses count as errors.

| Area | Target |
| --- | --- |
| Integrity | Zero double claims, duplicate final results, score changes, or unauthorized replay disclosures. |
| API at 100 users | p95 response under 2 s, p99 under 5 s, unexpected request errors under 1%, and no persistent 5xx burst. |
| Sessions | At least 99% successful session restoration and heartbeats during the sustained test; transient 5xx must not log out a valid team. |
| Workers | Zero failed real games in an 8-game sample at a chosen concurrency; heartbeat age under 45 s; at least 1 GiB host RAM available; no Docker cleanup leftovers. |
| Replay | One playback request per viewed replay, no requests when seeking, initial bundle load under 3 s at p95 for a representative full match, fixed 60 ms per turn. |
| Competition time | For 100 teams and five reference bots, 2,000 real games must complete within 180 minutes, including a capacity reserve. This means at least 11.1 games/min across the pool before reserve and Round 2. |

The concurrency benchmark uses eight real Docker games at each level 1, 2, 3 and 4 on the existing Standard_D2as_v4 VM. A short sample identifies obvious resource pressure; sustained event readiness requires a longer test. Do not relax these targets after observing results merely to report success.
