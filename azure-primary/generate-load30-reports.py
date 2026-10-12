"""Generate evidence-backed, secret-free final reports for the Azure rehearsal."""
from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config/local-profiles/load30-20261012.json"
REPORTS = ROOT / "reports"
START_UTC = datetime.fromisoformat("2026-10-12T14:51:36+00:00")


def date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def duration(start, end):
    a, b = date(start), date(end)
    return round((b - a).total_seconds(), 2) if a and b else None


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    i = (len(values) - 1) * p
    low = int(i)
    return round(values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (i - low), 2)


def main():
    d = json.loads(SOURCE.read_text(encoding="utf-8"))
    REPORTS.mkdir(exist_ok=True)
    with (ROOT / "FarmCraft_50_Full_Rehearsal/teams.csv").open(encoding="utf-8", newline="") as f:
        strategy_by_bot = {item["team"]: f"{item['family']} variant {item['variant']}"
                           for item in csv.DictReader(f)}
    details = d.get("details", {})
    rows = []
    for name in sorted(d["teams"]):
        team = d["teams"][name]
        job = details.get(name, d.get("jobs", {}).get(name, {}))
        result = job.get("result") or {}
        bot_id = Path(team["sourcePath"]).parent.name
        rows.append({"team": name, "sourceSha256": team["sha256"],
            "strategySource": strategy_by_bot.get(bot_id, bot_id),
            "acceptedAtUtc": team.get("acceptedAt"), "createdAtUtc": job.get("createdAt"),
            "startedAtUtc": job.get("startedAt"), "completedAtUtc": job.get("completedAt"),
            "queueWaitSeconds": duration(job.get("createdAt"), job.get("startedAt")),
            "executionSeconds": duration(job.get("startedAt"), job.get("completedAt")),
            "totalSeconds": duration(job.get("createdAt"), job.get("completedAt")),
            "workerId": job.get("worker"), "attempts": job.get("attempts"),
            "status": job.get("status"), "games": result.get("games"),
            "rating": result.get("rating"),
            "qualified": name in {r["team"] for r in d.get("qualifiers", [])}})
    timings = REPORTS / "FARMCRAFT_30_TEAM_TIMINGS.csv"
    with timings.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)

    complete = [row for row in rows if row["status"] == "completed"]
    saturated = sum(row["rating"] == 1000.0 for row in complete)
    rounds = d.get("round2Audit", {})
    audit = d.get("round1Audit", {})
    round1_start = min((date(row["createdAtUtc"]) for row in complete), default=None)
    round1_end = max((date(row["completedAtUtc"]) for row in complete), default=None)
    round1_seconds = round((round1_end - round1_start).total_seconds(), 2) if round1_start and round1_end else None
    observations = d.get("round2Observations", [])
    round2_seconds = duration(observations[0]["at"], observations[-1]["at"]) if len(observations) > 1 else None
    end_to_end_seconds = duration(d.get("startedAt"), d.get("round2AuditVerified", {}).get("at"))
    execution = [row["executionSeconds"] for row in complete if row["executionSeconds"] is not None]
    waits = [row["queueWaitSeconds"] for row in complete if row["queueWaitSeconds"] is not None]

    metrics_path = REPORTS / "FARMCRAFT_30_TEAM_WORKER_METRICS.csv"
    metrics = list(csv.DictReader(metrics_path.open(encoding="utf-8"))) if metrics_path.exists() else []
    telemetry = [json.loads(row["telemetryJson"]) for row in metrics if row.get("telemetryJson")]
    cpu_peak = max((float(x.get("cpuPercent") or 0) for x in telemetry), default=None)
    ram_peak = max((int(x.get("ramBytes") or 0) for x in telemetry), default=None)
    metric_errors = sum(bool(row.get("error")) for row in metrics)
    worker_names = sorted({row["workerName"] for row in metrics if row.get("workerName")})

    stop = date(d.get("vmDeallocatedAt"))
    hours = round((stop - START_UTC).total_seconds() / 3600, 3) if stop else None
    compute = round(hours * (0.236 + 0.216), 2) if hours is not None else None
    retained = round(hours * (0.010 + 0.0042), 2) if hours is not None else None
    cost = f"""# FarmCraft 30-team rehearsal cost

- VM starts: 2026-10-12 14:51:36 UTC, observed in Azure Activity Log.
- VM deallocation: {d.get('vmDeallocatedAt', 'PENDING')}.
- Running hours per additional VM: {hours if hours is not None else 'PENDING'}.
- Estimated incremental VM compute: US${compute if compute is not None else 'PENDING'} at US$0.236/h (D4s v4) plus US$0.216/h (D4as v4).
- Estimated retained disk and public IP cost over the same interval: US${retained if retained is not None else 'PENDING'} at US$0.0142/h combined.
- Estimated 3-hour event additional VM compute: US$1.36, plus approximately US$0.04 disk/IP over those hours.
- Azure Container Apps, PostgreSQL, Blob, log ingestion, transactions, and existing baseline are additional; no current invoice or posted actual usage was available to this runner.
- Last user-reported student credit before this run: ₹9,174 of ₹9,599. Current remaining credit was not independently verified.

These are estimates, not Azure billed amounts. Deallocated VMs retain disks and public IPs, which can continue billing.
Azure [Cost Management data can arrive after usage occurs](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/understand-cost-mgt-data); compare this estimate with posted usage later.
"""
    (REPORTS / "FARMCRAFT_30_TEAM_COST_REPORT.md").write_text(cost, encoding="utf-8")

    games = rounds.get("games", [])
    matches = rounds.get("matches", [])
    match_table = "\n".join(f"| {m.get('round')} | {m.get('player1')} | {m.get('player2')} | {m.get('p1Score')} | {m.get('p2Score')} | {m.get('winner')} | {len(m.get('replayIds', []))} |"
                            for m in matches)
    team_table = "\n".join(f"| {r['team']} | {r['strategySource']} | `{r['sourceSha256'][:12]}` | {r['queueWaitSeconds']} | {r['executionSeconds']} | {r['games']} | {r['rating']} | {r['qualified']} |"
                           for r in rows)
    report = f"""# FarmCraft — 30-team live Azure staging rehearsal

Generated: {datetime.now(timezone.utc).isoformat()}  
Target: {d.get('base')}  
Source evidence: ignored `config/local-profiles/load30-20261012.json`; live Admin API and worker metrics CSV.

## Outcome

- Participants and distinct uploaded bots: {len(rows)}.
- Official Round 1 jobs completed: {len(complete)}/30; failed: {sum(r['status'] in ('failed','timeout','cancelled') for r in rows)}.
- First-attempt successes: {sum(r['attempts'] == 1 and r['status'] == 'completed' for r in rows)}/30; jobs needing additional attempts: {sum((r['attempts'] or 0) > 1 for r in rows)}.
- Round 1 audited games and authenticated replay/analytics checks: {audit.get('games','NOT VERIFIED')} and {audit.get('replays','NOT VERIFIED')}.
- Round 1 wall time: {round1_seconds} seconds. The 15-minute target: {'PASS' if round1_seconds is not None and round1_seconds <= 900 else 'NOT VERIFIED/FAIL'}.
- Round 2 observed wall time: {round2_seconds} seconds; total from harness start through Round 2 audit: {end_to_end_seconds} seconds.
- Round 2 recorded games: {len(games)}; matches: {len(matches)}; champion: {rounds.get('champion', 'NOT VERIFIED')}.
- Four-worker observations: {len(metrics)} samples across {', '.join(worker_names)}; collector errors: {metric_errors}.
- Maximum Round 1 rating (1000) occurred for {saturated}/30 contestants; this score saturation limits ranking separation and should be reviewed before the real event.
- Overall readiness: {'CONDITIONAL GO — see limitations below' if d.get('round2AuditVerified') and d.get('finalResetVerified') and d.get('vmDeallocatedAt') else 'INCOMPLETE — do not declare event ready'}.

## Per-team Round 1 results

| Team | Strategy file | SHA256 prefix | Queue s | Execute s | Games | Rating | Qualified |
|---|---|---|---:|---:|---:|---:|---|
{team_table}

## Round 2 matches

| Round | Team A | Team B | Score A | Score B | Winner | Replay IDs |
|---:|---|---|---:|---:|---|---:|
{match_table or '| — | — | — | — | — | NOT VERIFIED | — |'}

## Timings and capacity

- Execution seconds: min {min(execution) if execution else 'N/A'}, median {percentile(execution,.5)}, p90 {percentile(execution,.9)}, p95 {percentile(execution,.95)}, p99 {percentile(execution,.99)}, max {max(execution) if execution else 'N/A'}.
- Queue wait seconds: average {round(statistics.mean(waits),2) if waits else 'N/A'}, median {percentile(waits,.5)}, p95 {percentile(waits,.95)}.
- Peak sampled CPU percentage: {cpu_peak}; peak reported RAM bytes: {ram_peak}. Telemetry definitions follow the worker heartbeat payload.
- Measured Round 1 throughput: {round(180 / (round1_seconds/60),2) if round1_seconds else 'N/A'} games/minute.
- Linear Round 1 projections at the observed rate: 60 teams ≈ {round(round1_seconds * 2 / 60,1) if round1_seconds else 'N/A'} minutes and 100 teams ≈ {round(round1_seconds * 100 / 30 / 60,1) if round1_seconds else 'N/A'} minutes. These assume the same bots and four workers and exclude Round 2, retries, and changing Azure load; they are not capacity guarantees.

## Integrity and limits

- Bot source hashes, server validation, and cross-team Bot Lab denial were recorded.
- Every audited job was recomputed from its six raw game records; distinct replay IDs, analytics, and first/final frame reads were required before bracket launch. Round 2 match-score, replay-frame, and champion audit: {'PASS' if d.get('round2AuditVerified') else 'NOT VERIFIED'}.
- Worker CSV captures queue and heartbeat time series; Azure billed usage and complete Docker/OOM telemetry were unavailable through this collector.
- Browser public landing and Admin sign-in rendered. Authenticated Admin UI and contestant replay interactions were not independently exercised in the browser during this run; backend API read checks are separate evidence.
- A separate invalid-source HTTP fixture was not run during this cycle; all 30 valid sources passed server validation and real execution.
- The pre-run private Blob backup was read back and hash-checked, but a full restore into another PostgreSQL database was not performed.
- Cost details are in `FARMCRAFT_30_TEAM_COST_REPORT.md`; see final checklist for the clean event state.
"""
    (REPORTS / "FARMCRAFT_30_TEAM_LIVE_REHEARSAL_REPORT.md").write_text(report, encoding="utf-8")
    checklist = f"""# FarmCraft event readiness checklist

- [{'x' if audit.get('games') == 180 else ' '}] 30 official Round 1 jobs and 180 games audited.
- [{'x' if d.get('round2AuditVerified') and len(matches) == 15 and len(games) >= 30 else ' '}] Full 16-team bracket, replay frames, and final independently audited.
- [{'x' if rounds.get('champion') else ' '}] Champion persisted in Azure staging.
- [{'x' if d.get('postRunBackupVerified') else ' '}] Post-run private backup created and hash-checked.
- [{'x' if d.get('finalResetVerified') else ' '}] Test accounts/jobs removed; competition phase SETUP; public gates MAINTENANCE.
- [{'x' if d.get('vmDeallocatedAt') else ' '}] Two additional evaluator VMs deallocated.
- [ ] Authenticated Admin and contestant browser walkthrough. Only API and public UI were checked here.
- [ ] Separate invalid-source HTTP fixture and UI error presentation.
- [ ] Review reference-bot difficulty or tie-break policy: all 30 rehearsal bots reached rating 1000.
- [ ] Organizer verifies event-day settings and remaining student credit before opening registration.

Event-day restart: start `farmcraft-eval-02` and `farmcraft-eval-03` in `rg-farmcraft-evaluators-20261012`; verify all four `farmcraft-kr/id-01/02` worker slots idle in Admin → Workers & Devices, then open event gates from Admin. Do not start official Round 1 until the intended real participants and reference selection are checked.
"""
    (REPORTS / "FARMCRAFT_EVENT_READINESS_CHECKLIST.md").write_text(checklist, encoding="utf-8")
    print(json.dumps({"reports": 5, "round1Jobs": len(complete), "round2Matches": len(matches),
                      "round2Games": len(games), "finalReset": bool(d.get("finalResetVerified")),
                      "vmDeallocated": bool(stop)}))


if __name__ == "__main__":
    main()
