"""End-to-end passwordless identity and ownership check on isolated port 18000."""
from __future__ import annotations

import secrets
import time
from pathlib import Path

import requests


BASE = "http://127.0.0.1:18000"


def check(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text)
    return response.json()


def main():
    check(requests.get(BASE + "/ready", timeout=10))
    suffix = secrets.token_hex(4)
    name = "identity_" + suffix
    other_name = "other_" + suffix
    first, second, other, admin = (requests.Session() for _ in range(4))
    created = check(first.post(BASE + "/api/participants/session", json={"team": name}, timeout=10))
    first.headers["X-Participant-CSRF"] = created["csrfToken"]
    team_id = created["teamId"]
    assert check(first.get(BASE + "/api/participants/session", timeout=10))["teamId"] == team_id
    check(second.post(BASE + "/api/participants/session", json={"team": name.upper()}, timeout=10), 409)
    second_team = check(other.post(BASE + "/api/participants/session", json={"team": other_name}, timeout=10))
    assert second_team["teamId"] != team_id
    other.headers["X-Participant-CSRF"] = second_team["csrfToken"]
    check(other.get(BASE + "/botlab/" + name, timeout=10), 403)
    check(first.put(BASE + "/api/participants/strategy", json={"missionId": "livestock"}, timeout=10))
    assert check(first.get(BASE + "/api/participants/strategy", timeout=10))["missionId"] == "livestock"
    assert check(other.get(BASE + "/api/participants/strategy", timeout=10))["missionId"] is None
    check(first.post(BASE + "/api/participants/heartbeat", json={"idle": False}, headers={"X-Participant-CSRF": "wrong"}, timeout=10), 403)

    source = Path(__file__).with_name("agent.py").read_bytes()
    check(first.post(BASE + "/botlab/upload", data={"username": name}, files={"agent": ("main.py", b"", "text/x-python")}, timeout=10), 400)
    check(first.post(BASE + "/register", data={"username": name}, files={"agent": ("main.py", b"", "text/x-python")}, timeout=10), 400)
    upload = check(first.post(BASE + "/botlab/upload", data={"username": name}, files={"agent": ("main.py", source, "text/x-python")}, timeout=10))
    assert upload["submission"]["team_id"] == team_id
    check(other.get(BASE + "/botlab/" + name, timeout=10), 403)
    registration = check(first.post(BASE + "/register", data={"username": name}, files={"agent": ("main.py", source, "text/x-python")}, timeout=10))
    assert registration["player"]["username"] == name and registration["status"] == "registered"
    versions_before = len(check(first.get(BASE + "/botlab/" + name, timeout=10))["submissions"])
    check(first.post(BASE + "/register", data={"username": name}, files={"agent": ("main.py", source, "text/x-python")}, timeout=10), 409)
    assert len(check(first.get(BASE + "/botlab/" + name, timeout=10))["submissions"]) == versions_before
    official = check(first.post(BASE + f"/botlab/{name}/submit", timeout=10), 202)
    job_id = official["id"]
    for _ in range(300):
        job = check(first.get(BASE + "/jobs/" + job_id, timeout=10))
        if job["status"] in ("completed", "failed", "timeout"):
            break
        time.sleep(1)
    assert job["status"] == "completed", job
    assert any(row["team"] == name for row in check(first.get(BASE + "/leaderboard", timeout=10))["entries"])

    check(requests.get(BASE + "/api/admin/contestants", timeout=10), 401)
    login = check(admin.post(BASE + "/api/admin/login", json={"password": "load-test-organizer"}, timeout=10))
    admin.headers["X-Admin-CSRF"] = login["csrfToken"]
    contestants = check(admin.get(BASE + "/api/admin/contestants", timeout=10))["contestants"]
    row = next(item for item in contestants if item["team"] == name)
    assert row["teamId"] == team_id and row["savedStrategy"] == "livestock"
    recovery = check(admin.post(BASE + f"/api/admin/contestants/{name}/recovery", json={"confirmation": "RESET SESSION"}, timeout=10))
    check(first.get(BASE + "/api/participants/session", timeout=10), 401)
    recovered = check(second.post(BASE + "/api/participants/recover", json={"team": name, "recoveryCode": recovery["recoveryCode"]}, timeout=10))
    assert recovered["teamId"] == team_id
    second.headers["X-Participant-CSRF"] = recovered["csrfToken"]
    check(first.post(BASE + "/api/participants/recover", json={"team": name, "recoveryCode": recovery["recoveryCode"]}, timeout=10), 401)
    assert check(second.get(BASE + "/api/participants/strategy", timeout=10))["missionId"] == "livestock"
    check(second.post(BASE + "/api/participants/logout", timeout=10))
    check(second.get(BASE + "/api/participants/session", timeout=10), 401)
    print({"team": name, "teamId": team_id, "strategy": "livestock", "officialJob": job_id,
           "duplicateNameRejected": True, "crossTeamDenied": True, "oneTimeRecovery": True, "logoutInvalidated": True})


if __name__ == "__main__":
    main()
