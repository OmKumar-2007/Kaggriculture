# Existing Azure VM real Docker concurrency benchmark

Run on 10 October 2026 on the already running `farmcraft-eval-01` (Standard_D2as_v4, 2 vCPUs, 8 GiB RAM, Korea Central). The registered worker was paused with no jobs queued before the run, then resumed. The command used the VM's existing evaluator image and eight actual Kaggriculture games at each concurrency level:

```bash
cd /opt/farmcraft
farmcraft-evaluator/.venv/bin/python farmcraft-evaluator/scripts/benchmark.py --levels 1,2,3,4 --games 8
```

| Concurrent games | Completed / failed | Wall time | Mean game | P95 game | Games/min | Peak host CPU | Peak host RAM |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 8 / 0 | 31.64 s | 3.96 s | 4.02 s | 15.17 | 53.5% | 0.80 GiB |
| 2 | 8 / 0 | 25.35 s | 6.34 s | 6.52 s | 18.93 | 100% | 0.88 GiB |
| 3 | 8 / 0 | 25.34 s | 8.69 s | 9.55 s | 18.94 | 100% | 0.97 GiB |
| 4 | 8 / 0 | 24.82 s | 12.22 s | 13.03 s | 19.34 | 100% | 1.07 GiB |

**Provisional choice: two one-game worker instances.** Two games improve throughput by 24.8% over one. A third or fourth consumes the same two vCPUs and raises game latency with almost no throughput gain. Eight games per level are enough to reject 3–4 as inefficient in this sample; they do not prove sustained three-hour throughput, failure rates, Docker startup distribution, or API upload latency.

At the measured 18.93 games/min, 2,000 Round 1 games would take about 106 minutes of uninterrupted engine work, before reference-bot variation, uploads, queue waits, cold starts, recovery, Round 2, and capacity reserve. A 25% reserve raises that idealized estimate to about 141 minutes. The event requirement is 11.1 games/min across the pool; a longer realistic official-job run must establish that the measured rate holds. No capacity claim for 100 contestants is made from this short benchmark.

The benchmark report is also saved on the VM at `/opt/farmcraft/farmcraft-evaluator/benchmark.json`. It exercises real Docker games but does not register extra workers or submit HTTP jobs; independent worker registration and concurrent claim/result verification are separate deployment gates.
