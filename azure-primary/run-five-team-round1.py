"""Run five isolated staging contestant flows; never targets Render or Neon."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
OUT = ROOT / "config" / "local-profiles" / "five-team-e2e-20261012.json"
NAMES = ["E2E_ALPHA_261012", "E2E_BETA_261012", "E2E_GAMMA_261012", "E2E_DELTA_261012", "E2E_EPSILON_261012"]
BOT_NUMBERS = [1, 11, 21, 31, 41]
TERMINAL = {"completed", "failed", "timeout", "cancelled"}


def call(session: requests.Session, method: str, path: str, **kwargs):
    response = session.request(method, BASE + path, timeout=60, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:350]}")
    return response.json()


def save(record: dict):
    OUT.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    os.chmod(OUT, 0o600)


def wait_jobs(sessions: dict[str, requests.Session], jobs: dict[str, str], seconds: int, label: str):
    deadline = time.monotonic() + seconds
    pending = dict(jobs)
    done = {}
    while pending and time.monotonic() < deadline:
        for name, job_id in list(pending.items()):
            job = call(sessions[name], "GET", f"/jobs/{job_id}")
            if job["status"] in TERMINAL:
                done[name] = job
                del pending[name]
                print(f"{label} {name}: {job['status']} job={job_id} attempts={job.get('attempts')}", flush=True)
        if pending:
            time.sleep(5)
    if pending:
        raise RuntimeError(f"{label} timed out: {pending}")
    failed = {name: {"job": job["id"], "status": job["status"], "error": job.get("error")}
              for name, job in done.items() if job["status"] != "completed"}
    if failed:
        raise RuntimeError(f"{label} failed: {failed}")
    return done


def main():
    password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD", None)
    if not password:
        raise RuntimeError("Protected staging Admin password was not supplied.")
    admin = requests.Session()
    login = call(admin, "POST", "/api/admin/login", json={"password": password})
    password = None
    admin.headers.update({"x-admin-csrf": login["csrfToken"]})

    ready = call(admin, "GET", "/ready")
    version = call(admin, "GET", "/api/remote-workers/version")
    original = call(admin, "GET", "/api/admin/event")
    competition = call(admin, "GET", "/api/admin/competition")
    contestants = call(admin, "GET", "/api/admin/contestants")
    standings = call(admin, "GET", "/api/admin/competition/standings")
    tournament = call(admin, "GET", "/api/admin/tournament")
    workers = call(admin, "GET", "/api/admin/remote-workers")
    assert ready["status"] == "ready" and all(ready["checks"].values())
    assert version["evaluatorVersion"] == "2026.10.12"
    assert version["evaluationConfigSha256"] == "dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1"
    assert original["mode"] == "MAINTENANCE" and not any(original[k] for k in
        ("registrationsEnabled", "uploadsEnabled", "sandboxEnabled", "officialEnabled", "tournamentEnabled"))
    assert competition["phase"] == "QUALIFICATION_OPEN"
    assert len(competition["referencePool"]) == 3
    assert len(competition["evaluationConfig"]["seeds"]) == 1
    assert len(competition["evaluationConfig"]["sides"]) == 2
    assert tournament["status"] == "registration"
    existing = {str(row.get("team") or row.get("username") or "").casefold() for row in contestants["contestants"]}
    if OUT.exists():
        previous = json.loads(OUT.read_text(encoding="utf-8"))
        assert previous.get("teams") == NAMES, "Existing checkpoint belongs to another rehearsal."
    else:
        assert not any(name.casefold() in existing for name in NAMES), "Test names exist without a local checkpoint."
    online = {row["name"] for row in workers["workers"] if row["status"] == "idle" and row.get("availableSlots", 0) >= 1}
    assert {"farmcraft-kr-01", "farmcraft-kr-02", "farmcraft-id-01", "farmcraft-id-02"} <= online

    bot_sources = {}
    hashes = set()
    for name, number in zip(NAMES, BOT_NUMBERS):
        source = (ROOT / "FarmCraft_50_Full_Rehearsal" / "bots" / f"FC26_R50_{number:03d}" / "agent.py").read_bytes()
        assert len(source) < 100_000
        hashes.add(hashlib.sha256(source).hexdigest())
        bot_sources[name] = source
    assert len(hashes) == 5

    record = previous if OUT.exists() else {"startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "base": BASE, "before": {"event": original, "competition": competition,
                  "contestants": contestants, "standings": standings, "tournament": tournament},
              "teams": NAMES, "botSourceSha256": sorted(hashes), "jobs": {}}
    record.setdefault("attempts", []).append(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    save(record)
    print(f"Saved staging state; existing contestants={len(contestants['contestants'])}, standings={len(standings.get('standings', []))}", flush=True)

    keys = ("mode", "registrationsEnabled", "uploadsEnabled", "sandboxEnabled", "officialEnabled",
            "tournamentEnabled", "leaderboardVisible", "submissionLimit", "submissionCooldownSeconds")
    base_event = {key: original[key] for key in keys if key in original}

    def gates(**changes):
        event = call(admin, "PUT", "/api/admin/event", json={**base_event, **changes})
        print("Gates: " + ", ".join(f"{key}={event[key]}" for key in changes), flush=True)
        return event

    sessions: dict[str, requests.Session] = {}
    try:
        gates(registrationsEnabled=any(name.casefold() not in existing for name in NAMES), uploadsEnabled=True)
        for name in NAMES:
            session = requests.Session()
            if name.casefold() in existing:
                issued = call(admin, "POST", f"/api/admin/contestants/{name}/recovery",
                              json={"confirmation": "RESET SESSION", "reason": "Isolated staging E2E recovery"})
                login = call(session, "POST", "/api/participants/recover",
                             json={"team": name, "recoveryCode": issued["recoveryCode"]})
            else:
                login = call(session, "POST", "/api/participants/session", json={"team": name})
            assert login["team"] == name
            session.headers.update({"x-participant-csrf": login["csrfToken"]})
            assert call(session, "GET", "/api/participants/session")["team"] == name
            assert call(session, "GET", f"/botlab/{name}")
            sessions[name] = session
            print(f"Contestant session: {name}", flush=True)
        for name in NAMES:
            result = call(sessions[name], "POST", "/botlab/upload",
                          data={"username": name}, files={"agent": ("main.py", bot_sources[name], "text/x-python")})
            assert result["validation"]["valid"], f"Invalid bot: {name}: {result['validation']}"
            assert call(sessions[name], "POST", f"/botlab/{name}/validate")["valid"]
            record.setdefault("submissions", {})[name] = result["submission"]["id"]
            print(f"Valid Bot Lab upload: {name}", flush=True)
        denial = sessions[NAMES[0]].get(BASE + f"/botlab/{NAMES[1]}", timeout=30)
        assert denial.status_code == 403, f"Cross-team Bot Lab access returned {denial.status_code}"
        wrong_type = sessions[NAMES[0]].post(BASE + "/botlab/upload", data={"username": NAMES[0]},
                                            files={"agent": ("invalid.txt", b"bad", "text/plain")}, timeout=30)
        assert wrong_type.status_code == 400, f"Invalid type returned {wrong_type.status_code}"
        gates(registrationsEnabled=False, uploadsEnabled=False, sandboxEnabled=True)
        sandbox_jobs = {}
        for name in NAMES:
            job = call(sessions[name], "POST", f"/botlab/{name}/sandbox", data={"opponent": "starter_crop", "seed": 20261012})
            sandbox_jobs[name] = job["id"]
        record["jobs"]["sandbox"] = sandbox_jobs
        save(record)
        print("Queued five real Bot Lab sandbox jobs", flush=True)
        sandbox_done = wait_jobs(sessions, sandbox_jobs, 900, "sandbox")
        record["sandboxResults"] = {name: job["result"] for name, job in sandbox_done.items()}
        save(record)
        gates(sandboxEnabled=False, officialEnabled=True)
        def submit(name):
            return name, call(sessions[name], "POST", f"/botlab/{name}/submit")
        with ThreadPoolExecutor(max_workers=5) as pool:
            official_jobs = {name: result["id"] for name, result in pool.map(submit, NAMES)}
        record["jobs"]["official"] = official_jobs
        save(record)
        gates(officialEnabled=False)
        print("Queued five official six-game jobs concurrently", flush=True)
        official_done = wait_jobs(sessions, official_jobs, 1800, "official")
        record["officialResults"] = {name: job["result"] for name, job in official_done.items()}
        for name in NAMES:
            summary = call(sessions[name], "GET", f"/botlab/{name}")
            jobs = call(sessions[name], "GET", f"/teams/{name}/jobs")["jobs"]
            assert any(item["id"] == official_jobs[name] and item["status"] == "completed" for item in jobs)
            assert summary["currentSubmission"] is not None
        record["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save(record)
        print("ROUND1_FIVE_TEAMS_COMPLETE", flush=True)
    finally:
        try:
            restored = call(admin, "PUT", "/api/admin/event", json=base_event)
            record["restoredEvent"] = restored
            save(record)
            print("Restored original staging participant gates", flush=True)
        except Exception as exc:
            print(f"URGENT: could not restore staging gates: {exc}", file=sys.stderr, flush=True)
            raise


if __name__ == "__main__":
    main()
