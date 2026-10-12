"""Reconcile five real staging evaluations with scoring, standings and Blob replays."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests
from backend.services.scoring import aggregate_games

BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
SOURCE = ROOT / "config/local-profiles/five-team-e2e-20261012.json"
OUTPUT = ROOT / "config/local-profiles/five-team-round1-audit-20261012.json"


def get(session, path):
    response = session.get(BASE + path, timeout=60)
    response.raise_for_status()
    return response.json()


def main():
    record = json.loads(SOURCE.read_text(encoding="utf-8"))
    password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD", None)
    if not password:
        raise RuntimeError("Protected staging Admin password was not supplied.")
    admin = requests.Session()
    response = admin.post(BASE + "/api/admin/login", json={"password": password}, timeout=60)
    response.raise_for_status()
    password = None
    standings = get(admin, "/api/admin/competition/standings")["entries"]
    competition = get(admin, "/api/admin/competition")
    event = get(admin, "/api/admin/event")
    assert competition["phase"] == "QUALIFICATION_OPEN"
    assert event["mode"] == "MAINTENANCE" and not any(event[k] for k in
        ("registrationsEnabled", "uploadsEnabled", "sandboxEnabled", "officialEnabled", "tournamentEnabled"))
    names = record["teams"]
    rows = {row["team"]: row for row in standings}
    assert all(name in rows for name in names), "A test team is absent from staging standings."
    expected_opponents = {f"ref_{row['id']}" for row in competition["referencePool"]}
    expected_seed = competition["evaluationConfig"]["seeds"][0]
    all_replays = set()
    game_count = 0
    analytics_count = 0
    checks = {}
    for name in names:
        result = record["officialResults"][name]
        games = result["matchResults"]
        assert result["games"] == len(games) == 6
        assert {game["opponent"] for game in games} == expected_opponents
        assert {game["seed"] for game in games} == {expected_seed}
        assert {(game["opponent"], game["side"]) for game in games} == {
            (opponent, side) for opponent in expected_opponents for side in (0, 1)}
        recomputed = aggregate_games(games, competition["evaluationConfig"])
        for key, value in recomputed.items():
            actual = result[key]
            if isinstance(value, (int, float)):
                assert math.isclose(actual, value, rel_tol=1e-9, abs_tol=1e-6), (name, key, actual, value)
        assert math.isclose(rows[name]["rating"], result["rating"], abs_tol=1e-6)
        for game in games:
            replay_id = game["replayId"]
            assert replay_id not in all_replays
            all_replays.add(replay_id)
            analytics = get(admin, f"/replays/{replay_id}/analytics")
            frame = get(admin, f"/replays/{replay_id}/frame/0")
            assert analytics["steps"] > 0 and frame["totalSteps"] == analytics["steps"]
            expected_player_zero = game["contestantMoney"] if game["side"] == 0 else game["opponentMoney"]
            assert math.isclose(analytics["finalCash"], expected_player_zero, abs_tol=1e-6), (replay_id, analytics["finalCash"], expected_player_zero)
            game_count += 1
            analytics_count += 1
        sample = get(admin, f"/replays/{games[0]['replayId']}/playback")
        assert len(sample.get("players", [])) == 2 and all(
            len(frames) == sample["totalSteps"] for frames in sample["players"]), "Playback bundle is incomplete."
        checks[name] = {"rating": result["rating"], "games": len(games), "replays": len(games),
                        "rank": rows[name]["rank"], "jobId": record["jobs"]["official"][name]}
        print(f"AUDITED {name}: 6 games, 6 replays, rating {result['rating']}, rank {rows[name]['rank']}", flush=True)
    assert game_count == analytics_count == len(all_replays) == 30
    anonymous = requests.get(BASE + f"/replays/{next(iter(all_replays))}/analytics", timeout=30)
    assert anonymous.status_code in (401, 404), f"Private replay exposed: HTTP {anonymous.status_code}"
    top_five = [row["team"] for row in standings[:5]]
    output = {"gameCount": game_count, "replayCount": len(all_replays), "analyticsCount": analytics_count,
              "checks": checks, "topFive": top_five, "topFiveAreE2E": set(top_five) == set(names),
              "allStandingTeams": [row["team"] for row in standings], "anonymousReplayHttp": anonymous.status_code}
    OUTPUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    os.chmod(OUTPUT, 0o600)
    print(f"ROUND1_AUDIT_OK games={game_count} replayReads={analytics_count} topFiveAreE2E={output['topFiveAreE2E']}", flush=True)


if __name__ == "__main__":
    main()
