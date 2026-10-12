"""Advance the isolated Azure staging top-five through a real seeded tournament."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
AUDIT = ROOT / "config/local-profiles/five-team-round1-audit-20261012.json"
BEFORE = ROOT / "config/local-profiles/five-team-e2e-20261012.json"
OUT = ROOT / "config/local-profiles/five-team-round2-20261012.json"


def call(session, method, path, **kwargs):
    response = session.request(method, BASE + path, timeout=60, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:400]}")
    return response.json()


def save(record):
    OUT.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    os.chmod(OUT, 0o600)


def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    names = before["teams"]
    assert audit["topFiveAreE2E"] and set(audit["topFive"]) == set(names)
    password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD", None)
    if not password:
        raise RuntimeError("Protected staging Admin password was not supplied.")
    admin = requests.Session()
    login = call(admin, "POST", "/api/admin/login", json={"password": password})
    password = None
    admin.headers.update({"x-admin-csrf": login["csrfToken"]})
    original_event = before["before"]["event"]
    event_keys = ("mode", "registrationsEnabled", "uploadsEnabled", "sandboxEnabled", "officialEnabled",
                  "tournamentEnabled", "leaderboardVisible", "submissionLimit", "submissionCooldownSeconds")
    restore = {key: original_event[key] for key in event_keys if key in original_event}
    record = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "teams": names}
    save(record)
    try:
        assert call(admin, "GET", "/ready")["status"] == "ready"
        event = call(admin, "GET", "/api/admin/event")
        assert event["mode"] in ("MAINTENANCE", "TOURNAMENT")
        competition = call(admin, "GET", "/api/admin/competition")
        phase = competition["phase"]
        if phase == "QUALIFICATION_OPEN":
            settings = competition["settings"]
            payload = {key: settings[key] for key in ("registrationCapacity", "officialAttemptLimit",
                "referenceCount", "qualificationSeedCount", "tieReplayLimit")}
            payload["qualifierCount"] = 5
            changed = call(admin, "PUT", "/api/admin/competition/settings", json=payload)
            assert changed["settings"]["qualifierCount"] == 5
            print("Set isolated staging qualifier cutoff to five", flush=True)
            competition = call(admin, "POST", "/api/admin/competition/close-qualification",
                               json={"confirmation": "CLOSE QUALIFICATION"})
            phase = competition["phase"]
            print(f"Closed staging qualification: {phase}", flush=True)
        if phase == "QUALIFICATION_CLOSING":
            finalized = call(admin, "POST", "/api/admin/competition/finalize",
                             json={"confirmation": "FINALIZE QUALIFICATION"})
            roster = finalized["qualifiers"]
            assert len(roster) == 5 and {row["team"] for row in roster} == set(names)
            record["qualifiers"] = roster
            save(record)
            phase = finalized["phase"]
            print("Finalized exactly the five test qualifiers", flush=True)
        if phase == "QUALIFICATION_FINALIZED":
            preview = call(admin, "GET", "/api/admin/competition/bracket-preview")
            assert preview["capacity"] == 8 and preview["byes"] == 3, preview
            record["bracketPreview"] = preview
            save(record)
            print("Previewed five-team bracket: capacity eight, three byes", flush=True)
            locked = call(admin, "POST", "/api/admin/competition/lock-bracket",
                          json={"confirmation": "LOCK BRACKET"})
            assert locked["status"] == "ready" and locked["qualifiers"] == 5
            phase = "TOURNAMENT_READY"
            print("Locked seeded Round 2 bracket", flush=True)
        if phase == "TOURNAMENT_READY":
            event = call(admin, "GET", "/api/admin/event")
            if not event["tournamentEnabled"]:
                payload = {**restore, "mode": "TOURNAMENT", "tournamentEnabled": True}
                call(admin, "PUT", "/api/admin/event", json=payload)
            started = call(admin, "POST", "/api/admin/tournament/start",
                           json={"confirmation": "START TOURNAMENT"})
            record["tournamentJobId"] = started["job"]["id"]
            save(record)
            phase = "TOURNAMENT_RUNNING"
            print(f"Queued real tournament job {record['tournamentJobId']}", flush=True)
        if phase not in ("TOURNAMENT_RUNNING", "TOURNAMENT_COMPLETED"):
            raise RuntimeError(f"Unexpected competition phase {phase}")
        if phase == "TOURNAMENT_RUNNING":
            current = call(admin, "GET", "/api/admin/tournament")
            if current.get("status") == "error" and not record.get("resumeJobId"):
                resumed = call(admin, "POST", "/api/admin/competition/resume-tournament",
                               json={"confirmation": "RESUME TOURNAMENT"})
                record["resumeJobId"] = resumed["job"]["id"]
                save(record)
                print(f"Resumed locked tournament job {record['resumeJobId']}", flush=True)
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            competition = call(admin, "GET", "/api/admin/competition")
            tournament = call(admin, "GET", "/api/admin/tournament")
            if competition["phase"] == "TOURNAMENT_COMPLETED" or tournament.get("status") in ("champion", "finished"):
                break
            if tournament.get("status") == "error":
                raise RuntimeError(f"Tournament error: {tournament.get('error')}")
            time.sleep(8)
        else:
            raise RuntimeError("Tournament did not complete within 30 minutes.")
        assert competition["phase"] == "TOURNAMENT_COMPLETED", competition["phase"]
        champion = tournament.get("champion")
        champion_name = champion.get("username") if isinstance(champion, dict) else champion
        assert champion_name in names, champion
        games = call(admin, "GET", "/api/admin/tournament/games")["games"]
        assert games and all(game.get("replayId") for game in games)
        replay_ids = {game["replayId"] for game in games}
        assert len(replay_ids) == len(games)
        for replay_id in replay_ids:
            analytics = call(admin, "GET", f"/replays/{replay_id}/analytics")
            assert analytics["steps"] > 0
        record.update({"completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "phase": competition["phase"], "champion": champion_name,
                       "tournamentStatus": tournament.get("status"), "games": games,
                       "tournamentReplayCount": len(replay_ids),
                       "roundsHistory": tournament.get("roundsHistory"), "allMatches": tournament.get("allMatches")})
        save(record)
        print(f"ROUND2_COMPLETE champion={champion_name} games={len(games)} replays={len(replay_ids)}", flush=True)
    finally:
        try:
            restored = call(admin, "PUT", "/api/admin/event", json=restore)
            record["restoredEvent"] = restored
            save(record)
            print("Restored original staging maintenance controls", flush=True)
        except Exception as exc:
            print(f"URGENT: could not restore event controls: {exc}", file=sys.stderr, flush=True)
            raise


if __name__ == "__main__":
    main()
