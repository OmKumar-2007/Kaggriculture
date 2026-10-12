"""Independently audit the finished 50-team Azure staging competition."""

import csv
import json
import os
from pathlib import Path
import statistics
import sys
from datetime import datetime

import requests

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
from backend.services.scoring import aggregate_games

BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
NAMES = {f"LOAD50_20261013_{n:03d}" for n in range(1, 51)}
state = json.loads((ROOT / "private-evidence/load50_state.json").read_text(encoding="utf-8"))
password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD")
session = requests.Session()
response = session.post(BASE + "/api/admin/login", json={"password": password}, timeout=30)
response.raise_for_status()
password = None
session.headers["x-admin-csrf"] = response.json()["csrfToken"]


def get(path):
    response = session.get(BASE + path, timeout=60)
    response.raise_for_status()
    return response.json()


def csv_file(name, rows):
    path = REPO / "reports" / name
    path.parent.mkdir(exist_ok=True)
    if not rows:
        raise RuntimeError(f"No rows for {name}")
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    return path


def replay(replay_id):
    analytics = get(f"/replays/{replay_id}/analytics")
    steps = analytics["steps"]
    assert steps > 0
    assert get(f"/replays/{replay_id}/frame/0")
    assert get(f"/replays/{replay_id}/frame/{steps - 1}")
    return {"replayId": replay_id, "steps": steps, "firstFrame": True, "lastFrame": True,
            "analytics": True}


comp = get("/api/admin/competition")
assert comp["phase"] == "TOURNAMENT_COMPLETED", comp["phase"]
assert len(get("/api/admin/contestants")["contestants"]) == 50
assert set(state["teams"]) == NAMES
workers = get("/api/admin/remote-workers")["workers"]
worker_by_id = {row["id"]: row["name"] for row in workers}
standings = get("/api/admin/competition/standings")["entries"]
assert len(standings) == 50 and {row["team"] for row in standings} == NAMES
ordered = sorted(standings, key=lambda item: (
    -item["rating"], -item["winRate"], -item["averageMoneyDifferential"],
    -item["averageFinalMoney"], item["team"].casefold(), item["submissionId"]))
assert [item["team"] for item in ordered] == [item["team"] for item in standings]
assert [item["rank"] for item in standings] == list(range(1, 51))
standings_by_team = {row["team"]: row for row in standings}
jobs = []
games = []
replays = []
replay_ids = set()
for index, name in enumerate(sorted(NAMES), 1):
    job_id = state["teams"][name]["jobId"]
    job = get(f"/api/admin/jobs/{job_id}")
    assert job["status"] == "completed" and job["team"] == name
    assert state["teams"][name].get("status") == "completed", "Runner did not finish this team's full replay/frame audit"
    result = job["result"]
    assert result["status"] == "complete" and result["games"] == 6
    matches = result["matchResults"]
    assert len(matches) == 6
    assert {row["side"] for row in matches} == {0, 1}
    assert {row["seed"] for row in matches} == set(comp["evaluationConfig"]["seeds"])
    assert {row["opponent"] for row in matches} == {f"ref_{item['id']}" for item in comp["referencePool"]}
    independent = aggregate_games(matches, comp["evaluationConfig"])
    assert abs(independent["rating"] - result["rating"]) < 1e-5
    assert abs(standings_by_team[name]["rating"] - result["rating"]) < 1e-5
    jobs.append({"team": name, "jobId": job_id, "status": job["status"],
                 "rating": result["rating"], "workerId": job.get("worker"),
                 "workerName": worker_by_id.get(job.get("worker")),
                 "attempts": job.get("attempts"),
                 "queueWaitSeconds": job.get("queueWaitSeconds"),
                 "runtimeSeconds": job.get("runtimeSeconds"),
                 "createdAt": job.get("createdAt"), "startedAt": job.get("startedAt"),
                 "completedAt": job.get("completedAt"),
                 "requestStartEpoch": state["teams"][name]["requestStartEpoch"],
                 "requestEndEpoch": state["teams"][name]["requestEndEpoch"]})
    for match in matches:
        rid = match["replayId"]
        assert rid not in replay_ids
        replay_ids.add(rid)
        games.append({"team": name, "jobId": job_id,
                      **{key: json.dumps(value) if isinstance(value, (dict, list)) else value
                         for key, value in match.items()}})
        replays.append({"round": 1, "team": name, "replayId": rid,
                        "firstFrame": True, "lastFrame": True, "analytics": True,
                        "verification": "live_runner_full_check"})
    print(f"ROUND1_AUDITED {index}/50 {name}", flush=True)
assert len(games) == len(replays) == 300

tour = get("/api/admin/tournament")
bracket = tour["allMatches"]
round2_games = get("/api/admin/tournament/games")["games"]
assert len(bracket) == 15 and len(round2_games) >= 30
assert len({game["replayId"] for game in round2_games}) == len(round2_games)
for game in round2_games:
    replays.append({"round": 2, "team": game.get("playerZero"), **replay(game["replayId"])})
champion = tour["champion"]
champion_name = champion.get("username") if isinstance(champion, dict) else champion
assert champion_name in {row["team"] for row in comp["qualifiers"]}
assert next(row for row in bracket if row["round"] == 4)["winner"] == champion_name
by_match = {}
for game in round2_games:
    by_match.setdefault(game["matchId"], []).append(game)
for match in bracket:
    legs = by_match[match["matchId"]]
    assert {game["replayId"] for game in legs} == set(match["replayIds"])
    p1 = sum(game["scoreZero"] if game["playerZero"] == match["player1"] else game["scoreOne"] for game in legs)
    p2 = sum(game["scoreZero"] if game["playerZero"] == match["player2"] else game["scoreOne"] for game in legs)
    assert abs(p1 - match["p1Score"]) < 0.001 and abs(p2 - match["p2Score"]) < 0.001
    assert match["winner"] in (match["player1"], match["player2"])
    if p1 != p2:
        assert match["winner"] == (match["player1"] if p1 > p2 else match["player2"])

csv_file("FARMCRAFT_LOAD50_SUBMISSIONS.csv", jobs)
csv_file("FARMCRAFT_LOAD50_ROUND1_GAMES.csv", games)
csv_file("FARMCRAFT_LOAD50_STANDINGS.csv", standings)
csv_file("FARMCRAFT_LOAD50_BRACKET.csv", bracket)
csv_file("FARMCRAFT_LOAD50_REPLAYS.csv", replays)
samples = [json.loads(line) for line in (ROOT / "private-evidence/worker_samples.jsonl").read_text().splitlines()]
worker_rows = [{"at": sample["at"], **sample["jobs"],
                "workerName": worker["name"], "status": worker["status"],
                "availableSlots": worker["availableSlots"], "lastHeartbeat": worker["lastHeartbeat"]}
               for sample in samples if "workers" in sample for worker in sample["workers"]]
csv_file("FARMCRAFT_LOAD50_WORKERS.csv", worker_rows)
round2_sample_path = ROOT / "private-evidence/round2_worker_samples.jsonl"
if round2_sample_path.exists():
    round2_samples = [json.loads(line) for line in round2_sample_path.read_text().splitlines()]
    round2_rows = [{"at": sample["at"], "phase": sample["phase"],
                    "tournamentStatus": sample["tournamentStatus"],
                    "round": sample["round"], "matches": sample["matches"],
                    "workerName": worker["name"], "status": worker["status"],
                    "availableSlots": worker["availableSlots"],
                    "lastHeartbeat": worker["lastHeartbeat"]}
                   for sample in round2_samples if "workers" in sample
                   for worker in sample["workers"]]
    if round2_rows:
        csv_file("FARMCRAFT_LOAD50_ROUND2_WORKERS.csv", round2_rows)

def quantile(values, index):
    numbers = sorted(float(value) for value in values if value is not None)
    if not numbers:
        return None
    return numbers[min(len(numbers) - 1, int((len(numbers) - 1) * index))]


summary = {
    "teams": len(jobs), "round1Games": len(games), "round2Games": len(round2_games),
    "replaysVerified": len(replays), "matches": len(bracket), "champion": champion_name,
    "ratingsDistinct": len({job["rating"] for job in jobs}),
    "ratingMin": min(job["rating"] for job in jobs), "ratingMax": max(job["rating"] for job in jobs),
    "requestStartSkewSeconds": max(job["requestStartEpoch"] for job in jobs) - min(job["requestStartEpoch"] for job in jobs),
    "queueWaitMedianSeconds": quantile([job["queueWaitSeconds"] for job in jobs], .5),
    "queueWaitP95Seconds": quantile([job["queueWaitSeconds"] for job in jobs], .95),
    "runtimeMedianSeconds": quantile([job["runtimeSeconds"] for job in jobs], .5),
    "runtimeP95Seconds": quantile([job["runtimeSeconds"] for job in jobs], .95),
    "workerJobs": {name: sum(job["workerName"] == name for job in jobs)
                   for name in sorted({job["workerName"] for job in jobs})},
    "workerSamples": len(samples),
}
def parsed(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


summary["round1WallSeconds"] = (max(parsed(job["completedAt"]) for job in jobs) -
                                 min(parsed(job["createdAt"]) for job in jobs)).total_seconds()
summary["round1Meets15Minutes"] = summary["round1WallSeconds"] <= 900
if state.get("round2JobId"):
    tournament_job = get(f"/api/admin/jobs/{state['round2JobId']}")
    assert tournament_job["status"] == "completed"
    summary["round2WallSeconds"] = (parsed(tournament_job["completedAt"]) -
                                    parsed(tournament_job["createdAt"])).total_seconds()
summary["totalWallSeconds"] = (parsed(state["finishedAt"]) - parsed(state["startedAt"])).total_seconds()
(ROOT / "private-evidence/audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
