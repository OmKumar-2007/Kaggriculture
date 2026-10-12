"""Live Azure staging 30-team rehearsal; state stays in ignored local-profiles.

Run with the protected admin password supplied only through the environment.
No production host is configurable here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.scoring import aggregate_games
BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
STATE = ROOT / "config/local-profiles/load30-20261012.json"
BOT_DIR = ROOT / "FarmCraft_50_Full_Rehearsal/bots"
NAMES = [f"LOAD30_20261012_{n:02d}" for n in range(1, 31)]
WORKERS = {"farmcraft-kr-01", "farmcraft-kr-02", "farmcraft-id-01", "farmcraft-id-02"}
TERMINAL = {"completed", "failed", "timeout", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


def request(s, method, path, **kw):
    response = s.request(method, BASE + path, timeout=60, **kw)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def save(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(STATE)


def admin_session():
    password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD", None)
    if not password:
        raise RuntimeError("Protected staging admin password missing")
    s = requests.Session()
    auth = request(s, "POST", "/api/admin/login", json={"password": password})
    password = None
    s.headers["x-admin-csrf"] = auth["csrfToken"]
    return s


def participant(name, *, create=False):
    s = requests.Session()
    if create:
        auth = request(s, "POST", "/api/participants/session", json={"team": name})
    else:
        raise RuntimeError("Existing participant sessions are not reissued automatically")
    assert auth["team"] == name
    s.headers["x-participant-csrf"] = auth["csrfToken"]
    return s


def bot_sources():
    rows = {}
    for index, name in enumerate(NAMES, 1):
        path = BOT_DIR / f"FC26_R50_{index:03d}/agent.py"
        source = path.read_bytes()
        assert len(source) < 100_000
        compile(source, str(path), "exec")
        rows[name] = {"source": source, "sha256": hashlib.sha256(source).hexdigest(), "path": str(path)}
    assert len({v["sha256"] for v in rows.values()}) == 30
    return rows


def gates(admin, event, **changes):
    keys = ("mode", "registrationsEnabled", "uploadsEnabled", "sandboxEnabled",
            "officialEnabled", "tournamentEnabled", "leaderboardVisible",
            "submissionLimit", "submissionCooldownSeconds")
    return request(admin, "PUT", "/api/admin/event",
                   json={**{k: event[k] for k in keys if k in event}, **changes})


def preflight(admin):
    ready = request(admin, "GET", "/ready")
    event = request(admin, "GET", "/api/admin/event")
    comp = request(admin, "GET", "/api/admin/competition")
    refs = request(admin, "GET", "/api/admin/reference-bots")["bots"]
    workers = request(admin, "GET", "/api/admin/remote-workers")["workers"]
    contestants = request(admin, "GET", "/api/admin/contestants")["contestants"]
    assert ready["status"] == "ready" and all(ready["checks"].values()), ready
    assert event["mode"] == "MAINTENANCE" and not any(event[k] for k in
        ("registrationsEnabled", "uploadsEnabled", "sandboxEnabled", "officialEnabled", "tournamentEnabled"))
    assert comp["phase"] == "SETUP" and not contestants
    selected = [r for r in refs if r["selected"] and r["enabled"] and not r["archived"]]
    assert len(selected) == 3 and all(r["validationStatus"] == "valid" and r["testStatus"] == "passed" for r in selected)
    online = {r["name"] for r in workers if r["status"] == "idle" and r.get("availableSlots", 0) >= 1}
    assert WORKERS <= online, {"expected": sorted(WORKERS), "online": sorted(online)}
    assert comp["settings"]["referenceCount"] == 3 and comp["settings"]["qualificationSeedCount"] == 1
    assert comp["settings"]["qualifierCount"] == 16
    assert len(bot_sources()) == 30
    result = {"at": now(), "event": event, "competition": comp, "references": refs,
              "workers": workers, "contestants": contestants, "ready": ready}
    print(json.dumps({"ready": True, "phase": comp["phase"], "selectedReferences": len(selected),
                      "healthyWorkers": sorted(online & WORKERS), "teams": len(contestants)}), flush=True)
    return result


def start(admin):
    if STATE.exists():
        raise RuntimeError(f"Prior live load30 state exists: {STATE}; reconcile before replay")
    before = preflight(admin)
    data = {"startedAt": now(), "base": BASE, "before": before, "teams": {}, "jobs": {}}
    save(data)
    event = before["event"]
    try:
        gates(admin, event, mode="DEVELOPMENT", registrationsEnabled=True,
              uploadsEnabled=True, sandboxEnabled=True, officialEnabled=False,
              tournamentEnabled=False, leaderboardVisible=True)
        bots = bot_sources()
        sessions = {}
        for name in NAMES:
            s = participant(name, create=True)
            assert request(s, "GET", "/api/participants/session")["team"] == name
            sessions[name] = s
            data["teams"][name] = {"createdAt": now(), "sha256": bots[name]["sha256"],
                                  "sourcePath": bots[name]["path"]}
            save(data)
            print(f"REGISTERED {name}", flush=True)
        for name in NAMES:
            output = request(sessions[name], "POST", "/botlab/upload", data={"username": name},
                             files={"agent": ("main.py", bots[name]["source"], "text/x-python")})
            assert output["validation"]["valid"], {name: output["validation"]}
            assert request(sessions[name], "POST", f"/botlab/{name}/validate")["valid"]
            data["teams"][name]["submissionId"] = output["submission"]["id"]
            data["teams"][name]["uploadedAt"] = now()
            save(data)
            print(f"UPLOADED {name}", flush=True)
        cross = sessions[NAMES[0]].get(BASE + f"/botlab/{NAMES[1]}", timeout=30)
        assert cross.status_code == 403, f"Cross-team access HTTP {cross.status_code}"
        data["crossTeamDenied"] = True
        gates(admin, event, mode="MAINTENANCE", registrationsEnabled=False, uploadsEnabled=False,
              sandboxEnabled=False, officialEnabled=False, tournamentEnabled=False)
        comp = request(admin, "POST", "/api/admin/competition/start-qualification",
                       json={"confirmation": "START QUALIFICATION", "openAccess": False})
        assert comp["phase"] == "QUALIFICATION_OPEN" and len(comp["referencePool"]) == 3
        assert len(comp["evaluationConfig"]["seeds"]) == 1 and comp["evaluationConfig"]["sides"] == [0, 1]
        data["qualificationOpenedAt"] = now()
        save(data)
        gates(admin, event, mode="QUALIFICATION", registrationsEnabled=False, uploadsEnabled=False,
              sandboxEnabled=False, officialEnabled=True, tournamentEnabled=False,
              leaderboardVisible=True)
        print("READY FOR LIVE 30-TEAM REHEARSAL", flush=True)
        def submit(name):
            return name, now(), request(sessions[name], "POST", f"/botlab/{name}/submit")
        with ThreadPoolExecutor(max_workers=30) as pool:
            futures = {pool.submit(submit, name): name for name in NAMES}
            for future in as_completed(futures):
                name, accepted, job = future.result()
                data["teams"][name]["acceptedAt"] = accepted
                data["teams"][name]["officialJobId"] = job["id"]
                save(data)
                print(f"OFFICIAL_ACCEPTED {name} {job['id']}", flush=True)
        assert len({data["teams"][name]["officialJobId"] for name in NAMES}) == 30
        data["officialBurstCompletedAt"] = now()
        save(data)
        gates(admin, event, mode="MAINTENANCE", registrationsEnabled=False, uploadsEnabled=False,
              sandboxEnabled=False, officialEnabled=False, tournamentEnabled=False,
              leaderboardVisible=True)
        print("ROUND1_30_ACCEPTED", flush=True)
    except Exception:
        gates(admin, event, mode="MAINTENANCE", registrationsEnabled=False, uploadsEnabled=False,
              sandboxEnabled=False, officialEnabled=False, tournamentEnabled=False)
        raise


def monitor(admin, minutes):
    data = json.loads(STATE.read_text(encoding="utf-8"))
    jobs = {name: row["officialJobId"] for name, row in data["teams"].items() if row.get("officialJobId")}
    if not jobs:
        raise RuntimeError("No official jobs recorded")
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        snapshot = request(admin, "GET", "/api/admin/jobs?job_type=official&limit=500")["jobs"]
        by_id = {j["id"]: j for j in snapshot}
        counts = {status: sum(by_id.get(jid, {}).get("status") == status for jid in jobs.values())
                  for status in ("queued", "running", "completed", "failed", "timeout", "cancelled")}
        data["jobs"] = {name: by_id.get(jid, {"id": jid, "status": "missing"}) for name, jid in jobs.items()}
        data.setdefault("observations", []).append({"at": now(), "counts": counts})
        save(data)
        print(json.dumps({"at": now(), **counts}), flush=True)
        if counts["completed"] + counts["failed"] + counts["timeout"] + counts["cancelled"] == len(jobs):
            break
        time.sleep(15)
    else:
        raise TimeoutError("Round 1 monitor timed out")
    if counts["completed"] != 30:
        raise RuntimeError(f"Round 1 not clean: {counts}")
    print("ROUND1_30_COMPLETED", flush=True)


def audit_round1(admin):
    data = json.loads(STATE.read_text(encoding="utf-8"))
    comp = request(admin, "GET", "/api/admin/competition")
    assert comp["phase"] == "QUALIFICATION_OPEN"
    rows = []
    all_replays = set()
    for name in NAMES:
        jid = data["teams"][name]["officialJobId"]
        job = request(admin, "GET", f"/api/admin/jobs/{jid}")
        result = job["result"]
        assert job["status"] == "completed" and result["status"] == "complete"
        games = result["matchResults"]
        assert len(games) == result["games"] == 6
        assert {g["opponent"] for g in games} == {f"ref_{r['id']}" for r in comp["referencePool"]}
        assert {g["side"] for g in games} == {0, 1}
        assert {g["seed"] for g in games} == set(comp["evaluationConfig"]["seeds"])
        independently = aggregate_games(games, comp["evaluationConfig"])
        assert abs(independently["rating"] - result["rating"]) < 0.00001
        for game in games:
            replay = game["replayId"]
            assert replay not in all_replays
            all_replays.add(replay)
            analytics = request(admin, "GET", f"/replays/{replay}/analytics")
            assert analytics["steps"] > 0
            first = request(admin, "GET", f"/replays/{replay}/frame/0")
            last = request(admin, "GET", f"/replays/{replay}/frame/{analytics['steps']-1}")
            assert first and last
        data.setdefault("details", {})[name] = job
        save(data)
        rows.append({"team": name, "jobId": jid, "rating": result["rating"],
                     "games": len(games), "replays": len(games), "queueWaitSeconds": job.get("queueWaitSeconds"),
                     "runtimeSeconds": job.get("runtimeSeconds"), "attempts": job.get("attempts"),
                     "createdAt": job.get("createdAt"), "startedAt": job.get("startedAt"),
                     "completedAt": job.get("completedAt")})
        print(f"AUDITED {name}: 6 games, 6 replays, score {result['rating']:.3f}", flush=True)
    assert len(all_replays) == 180
    standings = request(admin, "GET", "/api/admin/competition/standings")["entries"]
    assert len(standings) == 30
    assert {row["team"] for row in standings} == set(NAMES)
    by_name = {row["team"]: row for row in standings}
    assert all(abs(by_name[row["team"]]["rating"] - row["rating"]) < 0.00001 for row in rows)
    data["round1Audit"] = {"at": now(), "games": 180, "replays": 180, "teams": 30,
                            "standings": standings, "rows": rows}
    save(data)
    print("ROUND1_AUDIT_PASSED: 30 jobs, 180 games, 180 readable replay/analytics pairs", flush=True)


def round2(admin, minutes):
    data = json.loads(STATE.read_text(encoding="utf-8"))
    assert data.get("round1Audit", {}).get("games") == 180
    original = data["before"]["event"]
    comp = request(admin, "GET", "/api/admin/competition")
    if comp["phase"] == "QUALIFICATION_OPEN":
        comp = request(admin, "POST", "/api/admin/competition/close-qualification",
                       json={"confirmation": "CLOSE QUALIFICATION"})
        print("ROUND1_CLOSED", flush=True)
    if comp["phase"] == "QUALIFICATION_CLOSING":
        result = request(admin, "POST", "/api/admin/competition/finalize",
                         json={"confirmation": "FINALIZE QUALIFICATION"})
        assert len(result["qualifiers"]) == 16
        assert [r["team"] for r in result["qualifiers"]] == [r["team"] for r in data["round1Audit"]["standings"][:16]]
        data["qualifiers"] = result["qualifiers"]
        save(data)
        comp = request(admin, "GET", "/api/admin/competition")
        print("ROUND1_FINALIZED: 16 qualifiers", flush=True)
    if comp["phase"] == "QUALIFICATION_FINALIZED":
        preview = request(admin, "GET", "/api/admin/competition/bracket-preview")
        assert preview["capacity"] == 16 and preview["byes"] == 0
        data["bracketPreview"] = preview
        save(data)
        locked = request(admin, "POST", "/api/admin/competition/lock-bracket",
                         json={"confirmation": "LOCK BRACKET"})
        assert locked["qualifiers"] == 16
        comp = request(admin, "GET", "/api/admin/competition")
        print("ROUND2_BRACKET_LOCKED", flush=True)
    if comp["phase"] == "TOURNAMENT_READY":
        gates(admin, original, mode="TOURNAMENT", registrationsEnabled=False, uploadsEnabled=False,
              sandboxEnabled=False, officialEnabled=False, tournamentEnabled=True,
              leaderboardVisible=True)
        started = request(admin, "POST", "/api/admin/tournament/start",
                          json={"confirmation": "START TOURNAMENT"})
        data["round2JobId"] = started["job"]["id"]
        save(data)
        print(f"ROUND2_STARTED {data['round2JobId']}", flush=True)
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        comp = request(admin, "GET", "/api/admin/competition")
        tour = request(admin, "GET", "/api/admin/tournament")
        data["tournament"] = tour
        data.setdefault("round2Observations", []).append({"at": now(), "phase": comp["phase"],
                 "status": tour["status"], "round": tour.get("currentRound"),
                 "matches": len(tour.get("allMatches", []))})
        save(data)
        print(json.dumps(data["round2Observations"][-1]), flush=True)
        if comp["phase"] == "TOURNAMENT_COMPLETED":
            break
        if tour["status"] == "error":
            raise RuntimeError(f"Tournament failed: {tour.get('error')}")
        time.sleep(15)
    else:
        raise TimeoutError("Round 2 timed out")
    games = request(admin, "GET", "/api/admin/tournament/games")["games"]
    assert len(games) >= 30
    assert len({g["replayId"] for g in games}) == len(games)
    for game in games:
        analytics = request(admin, "GET", f"/replays/{game['replayId']}/analytics")
        assert analytics["steps"] > 0
    champion = tour.get("champion")
    champion_name = champion.get("username") if isinstance(champion, dict) else champion
    assert champion_name in {q["team"] for q in data["qualifiers"]}
    data["round2Audit"] = {"at": now(), "champion": champion_name,
                           "games": games, "matches": tour.get("allMatches", []),
                           "replayCount": len(games)}
    save(data)
    gates(admin, original, mode="MAINTENANCE", registrationsEnabled=False, uploadsEnabled=False,
          sandboxEnabled=False, officialEnabled=False, tournamentEnabled=False,
          leaderboardVisible=False)
    print(f"ROUND2_COMPLETED champion={champion_name} games={len(games)}", flush=True)


def audit_round2(admin):
    data = json.loads(STATE.read_text(encoding="utf-8"))
    round2 = data.get("round2Audit")
    assert round2 and round2.get("champion")
    games = round2["games"]
    matches = round2["matches"]
    assert len(matches) == 15 and len(games) >= 30
    assert len({game["gameId"] for game in games}) == len(games)
    assert len({game["replayId"] for game in games}) == len(games)
    by_match = {}
    for game in games:
        by_match.setdefault(game["matchId"], []).append(game)
        replay_id = game["replayId"]
        analytics = request(admin, "GET", f"/replays/{replay_id}/analytics")
        assert analytics["steps"] > 0
        assert request(admin, "GET", f"/replays/{replay_id}/frame/0")
        assert request(admin, "GET", f"/replays/{replay_id}/frame/{analytics['steps']-1}")
    all_players = {q["team"] for q in data["qualifiers"]}
    for match in matches:
        assert match["player1"] in all_players and match["player2"] in all_players
        legs = by_match[match["matchId"]]
        assert {game["replayId"] for game in legs} == set(match["replayIds"])
        p1 = sum(game["scoreZero"] if game["playerZero"] == match["player1"] else game["scoreOne"] for game in legs)
        p2 = sum(game["scoreZero"] if game["playerZero"] == match["player2"] else game["scoreOne"] for game in legs)
        assert abs(p1 - match["p1Score"]) < 0.001 and abs(p2 - match["p2Score"]) < 0.001
        assert match["winner"] in (match["player1"], match["player2"])
        if p1 != p2:
            assert match["winner"] == (match["player1"] if p1 > p2 else match["player2"])
    final = next(m for m in matches if m["round"] == 4)
    assert final["winner"] == round2["champion"]
    data["round2AuditVerified"] = {"at": now(), "matches": len(matches),
                                    "games": len(games), "replays": len(games),
                                    "champion": round2["champion"]}
    save(data)
    print(f"ROUND2_AUDIT_PASSED: {len(matches)} matches, {len(games)} games/replays, champion={round2['champion']}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "start", "monitor", "audit", "round2", "audit2"))
    parser.add_argument("--max-minutes", type=int, default=120)
    args = parser.parse_args()
    admin = admin_session()
    if args.action == "preflight":
        preflight(admin)
    elif args.action == "start":
        start(admin)
    elif args.action == "monitor":
        monitor(admin, args.max_minutes)
    elif args.action == "audit":
        audit_round1(admin)
    elif args.action == "round2":
        round2(admin, args.max_minutes)
    else:
        audit_round2(admin)


if __name__ == "__main__":
    main()
