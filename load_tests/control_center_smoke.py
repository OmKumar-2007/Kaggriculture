"""Run only on the isolated port 18000 with a disposable fake worker."""
from __future__ import annotations

import secrets
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:18000"
SOURCE = Path(__file__).with_name("agent.py").read_bytes()


def result(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text)
    return response.json()


def main():
    result(requests.get(BASE + "/ready", timeout=10))
    admin = requests.Session()
    login = result(admin.post(BASE + "/api/admin/login", json={"password": "load-test-organizer"}, timeout=10))
    admin.headers["X-Admin-CSRF"] = login["csrfToken"]
    team = "control_" + secrets.token_hex(4)
    participant = requests.Session()
    session = result(participant.post(BASE + "/api/participants/session", json={"team": team}, timeout=10))
    participant.headers["X-Participant-CSRF"] = session["csrfToken"]
    team_id = session["teamId"]
    listing = result(admin.get(BASE + f"/api/admin/teams/{team_id}/sessions", timeout=10))["sessions"]
    assert len(listing) == 1
    result(admin.post(BASE + f"/api/admin/teams/{team_id}/sessions/{listing[0]['id']}/revoke",
                      json={"confirmation": "REVOKE", "reason": "smoke"}, timeout=10))
    result(participant.get(BASE + "/api/participants/session", timeout=10), 401)

    recovery = result(admin.post(BASE + f"/api/admin/contestants/{team}/recovery",
                                 json={"confirmation": "RESET SESSION"}, timeout=10))
    renewed = result(participant.post(BASE + "/api/participants/recover",
                                      json={"team": team, "recoveryCode": recovery["recoveryCode"]}, timeout=10))
    participant.headers["X-Participant-CSRF"] = renewed["csrfToken"]
    result(admin.put(BASE + f"/api/admin/teams/{team_id}/state",
                     json={"action": "suspend", "reason": "smoke review"}, timeout=10))
    result(participant.get(BASE + "/api/participants/session", timeout=10), 423)
    result(admin.put(BASE + f"/api/admin/teams/{team_id}/state",
                     json={"action": "unsuspend", "reason": "cleared"}, timeout=10))
    result(admin.put(BASE + f"/api/admin/teams/{team_id}/state",
                     json={"action": "block", "reason": "smoke"}, timeout=10))
    result(admin.put(BASE + f"/api/admin/teams/{team_id}/state",
                     json={"action": "unblock", "reason": "cleared"}, timeout=10))

    config = result(admin.get(BASE + "/api/admin/event", timeout=10))
    changed = {**config, "registrationsEnabled": False, "leaderboardVisible": False}
    result(admin.put(BASE + "/api/admin/event", json=changed, timeout=10))
    result(requests.post(BASE + "/api/participants/session", json={"team": "locked_" + secrets.token_hex(3)}, timeout=10), 409)
    assert result(requests.get(BASE + "/leaderboard", timeout=10))["locked"] is True
    result(admin.put(BASE + "/api/admin/event", json=config, timeout=10))

    worker = result(admin.get(BASE + "/api/admin/metrics", timeout=10))["workers"]["items"][0]["id"]
    result(admin.post(BASE + f"/api/admin/workers/{worker}/pause", json={"confirmation": "PAUSE"}, timeout=10))
    recovery = result(admin.post(BASE + f"/api/admin/contestants/{team}/recovery",
                                 json={"confirmation": "RESET SESSION"}, timeout=10))
    renewed = result(participant.post(BASE + "/api/participants/recover",
                                      json={"team": team, "recoveryCode": recovery["recoveryCode"]}, timeout=10))
    participant.headers["X-Participant-CSRF"] = renewed["csrfToken"]
    uploaded = result(participant.post(BASE + "/botlab/upload", data={"username": team},
                                       files={"agent": ("main.py", SOURCE, "text/x-python")}, timeout=10))
    assert uploaded["submission"]["team_id"] == team_id
    queued = result(participant.post(BASE + f"/botlab/{team}/sandbox", data={"opponent": "random", "seed": 102}, timeout=10), 202)
    job_id = queued["id"]
    cancelled = result(admin.post(BASE + f"/api/admin/jobs/{job_id}/cancel",
                                  json={"confirmation": "CANCEL", "reason": "smoke"}, timeout=10))
    assert cancelled["status"] == "cancelled"
    result(admin.post(BASE + f"/api/admin/workers/{worker}/resume", json={"confirmation": "RESUME"}, timeout=10))
    assert result(admin.get(BASE + f"/api/admin/jobs/{job_id}", timeout=10))["status"] == "cancelled"

    running = result(participant.post(BASE + f"/botlab/{team}/sandbox", data={"opponent": "random", "seed": 103}, timeout=10), 202)
    running_id = running["id"]
    for _ in range(30):
        detail = result(admin.get(BASE + f"/api/admin/jobs/{running_id}", timeout=10))
        if detail["status"] == "running":break
        time.sleep(.5)
    assert detail["status"] == "running", detail
    stopped = result(admin.post(BASE + f"/api/admin/jobs/{running_id}/cancel",
                                json={"confirmation": "CANCEL", "reason": "smoke running stop"}, timeout=10))
    assert stopped["stopPending"] is True
    for _ in range(30):
        pipeline = result(admin.get(BASE + f"/api/admin/jobs/{running_id}", timeout=10))["pipeline"]
        if any(event["stage"] == "execution" and event["status"] == "cancelled" for event in pipeline):break
        time.sleep(.5)
    assert any(event["stage"] == "execution" and event["status"] == "cancelled" for event in pipeline), pipeline
    assert result(admin.get(BASE + f"/api/admin/jobs/{running_id}", timeout=10))["status"] == "cancelled"
    assert any(event["stage"] == "cancellation" for event in pipeline)
    assert any(row["action"] == "job_cancel" and row["target"] == running_id for row in result(admin.get(BASE + "/api/admin/audit", timeout=10))["actions"])
    assert result(admin.get(BASE + "/api/admin/pipeline", timeout=10))["counts"]["cancelled"] >= 2
    print({"team": team, "queuedCancelled": job_id, "runningCancelled": running_id,
           "sessionRevoked": True, "suspendBlock": True, "workerPause": True, "eventSettings": True})


if __name__ == "__main__":
    main()
