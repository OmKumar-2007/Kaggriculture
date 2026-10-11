"""Two small, explicitly requested sandbox jobs against the existing live service."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import argparse
import time
from uuid import uuid4

import requests

BASE = "https://neural-coliseum-api.onrender.com"
SOURCE = Path(__file__).with_name("agent.py")


def checked(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text[:500])
    return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Create two live test teams and sandbox jobs")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Pass --execute to authorize two persistent live test teams and sandbox jobs.")
    ready = checked(requests.get(BASE + "/ready", timeout=45))
    assert ready["status"] == "ready" and all(ready["checks"].values())
    phase = checked(requests.get(BASE + "/leaderboard", timeout=45))["phase"]
    assert phase == "SETUP", f"Live competition phase is {phase}; refusing to create test teams."
    assert checked(requests.get(BASE + "/event/status", timeout=45))["sandboxEnabled"]

    suffix = uuid4().hex[:7]
    teams = []
    for index in (1, 2):
        team = f"stabilize_{suffix}_{index}"
        session = requests.Session()
        identity = checked(session.post(BASE + "/api/participants/session",
                                        json={"team": team}, timeout=45))
        session.headers["X-Participant-CSRF"] = identity["csrfToken"]
        upload = checked(session.post(BASE + "/botlab/upload", data={"username": team},
                                      files={"agent": ("agent.py", SOURCE.read_bytes(), "text/x-python")},
                                      timeout=60))
        assert upload["submission"]["validation_status"] == "valid", upload
        teams.append((team, session))

    def submit(item):
        team, session = item
        job = checked(session.post(BASE + f"/botlab/{team}/sandbox",
                                   data={"opponent": "starter_crop", "seed": 20260929},
                                   timeout=45), 202)
        return team, session, job["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(submit, teams))
    finished = {}
    deadline = time.monotonic() + 240
    while len(finished) < 2 and time.monotonic() < deadline:
        for team, session, job_id in jobs:
            if job_id in finished:
                continue
            job = checked(session.get(BASE + f"/jobs/{job_id}", timeout=45))
            if job["status"] in ("completed", "failed", "timeout", "cancelled"):
                assert job["status"] == "completed", (team, job)
                assert job["result"].get("replayId"), (team, job)
                finished[job_id] = job
        time.sleep(1)
    assert len(finished) == 2, f"Only {len(finished)} jobs finished within four minutes."

    for team, session, job_id in jobs:
        replay_id = finished[job_id]["result"]["replayId"]
        bundle = checked(session.get(BASE + f"/replays/{replay_id}/playback", timeout=60))
        assert bundle["version"] == 1 and bundle["totalSteps"] > 0
        other = jobs[1 if team == jobs[0][0] else 0][1]
        assert other.get(BASE + f"/replays/{replay_id}/playback", timeout=45).status_code == 404
    intervals = [(datetime.fromisoformat(job["startedAt"]), datetime.fromisoformat(job["completedAt"]))
                 for job in finished.values()]
    assert max(intervals[0][0], intervals[1][0]) < min(intervals[0][1], intervals[1][1]), (
        "Jobs completed without overlapping in time", intervals)
    print({"teams": [team for team, _ in teams], "jobs": list(finished),
           "overlapped": True, "replayOwnerOnly": True})


if __name__ == "__main__":
    main()
