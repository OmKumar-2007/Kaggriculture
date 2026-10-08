"""One real Docker-backed evaluation and organizer cancellation on isolated port 18000."""
from __future__ import annotations

import secrets
import subprocess
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:18000"
SOURCE = Path("NITW_Farm_AI_Challenge_v1/examples/starter_agent.py").read_bytes()


def check(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text)
    return response.json()


def wait_job(client, job_id, statuses, limit=150):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        job = check(client.get(BASE + "/jobs/" + job_id, timeout=10))
        if job["status"] in statuses:
            return job
        time.sleep(.5)
    raise AssertionError(f"Job {job_id} did not reach {statuses}")


def main():
    check(requests.get(BASE + "/ready", timeout=10))
    admin = requests.Session()
    login = check(admin.post(BASE + "/api/admin/login", json={"password": "load-test-organizer"}, timeout=10))
    admin.headers["X-Admin-CSRF"] = login["csrfToken"]
    team = "real_" + secrets.token_hex(4)
    client = requests.Session()
    identity = check(client.post(BASE + "/api/participants/session", json={"team": team}, timeout=10))
    client.headers["X-Participant-CSRF"] = identity["csrfToken"]
    valid = check(client.post(BASE + "/botlab/upload", data={"username": team},
                              files={"agent": ("main.py", SOURCE, "text/x-python")}, timeout=10))
    assert valid["validation"]["valid"] is True
    invalid = check(client.post(BASE + "/botlab/upload", data={"username": team},
                                files={"agent": ("main.py", b"def agent(obs):\n return (", "text/x-python")}, timeout=10))
    assert invalid["validation"]["valid"] is False
    assert invalid["submission"]["official_score"] is None
    # Restore a valid current version and run a real Kaggle environment match.
    check(client.post(BASE + "/botlab/upload", data={"username": team},
                      files={"agent": ("main.py", SOURCE, "text/x-python")}, timeout=10))
    queued = check(client.post(BASE + f"/botlab/{team}/sandbox", data={"opponent": "random", "seed": 101}, timeout=10), 202)
    completed = wait_job(client, queued["id"], {"completed", "failed", "timeout"})
    assert completed["status"] == "completed", completed
    assert completed["result"]["replayId"]
    detail = check(admin.get(BASE + "/api/admin/jobs/" + queued["id"], timeout=10))
    assert any(event["stage"] == "container" for event in detail["pipeline"])
    assert any(event["stage"] == "result" and event["status"] == "completed" for event in detail["pipeline"])
    official = check(client.post(BASE + f"/botlab/{team}/submit", timeout=10), 202)
    official_id = official["id"]
    official_done = wait_job(client, official_id, {"completed", "failed", "timeout"}, limit=240)
    assert official_done["status"] == "completed", official_done
    leaderboard = check(client.get(BASE + "/leaderboard", timeout=10))["entries"]
    assert any(entry["team"] == team and entry["rating"] == official_done["result"]["rating"] for entry in leaderboard)
    official_detail = check(admin.get(BASE + "/api/admin/jobs/" + official_id, timeout=10))
    assert len([event for event in official_detail["pipeline"] if event["stage"] == "match" and event["status"] == "completed"]) == 8

    broken = b"def agent(obs):\n raise RuntimeError('bot failed')\n"
    check(client.post(BASE + "/botlab/upload", data={"username": team},
                      files={"agent": ("main.py", broken, "text/x-python")}, timeout=10))
    failed = check(client.post(BASE + f"/botlab/{team}/submit", timeout=10), 202)
    failed_done = wait_job(client, failed["id"], {"completed", "failed", "timeout"}, limit=90)
    assert failed_done["status"] == "failed", failed_done
    failed_detail = check(admin.get(BASE + "/api/admin/jobs/" + failed["id"], timeout=10))
    assert failed_detail["errorKind"] == "CONTESTANT_RUNTIME_ERROR", failed_detail
    leaderboard = check(client.get(BASE + "/leaderboard", timeout=10))["entries"]
    assert any(entry["team"] == team and entry["rating"] == official_done["result"]["rating"] for entry in leaderboard)

    loop = b"def agent(obs):\n while True:\n  pass\n"
    check(client.post(BASE + "/botlab/upload", data={"username": team},
                      files={"agent": ("main.py", loop, "text/x-python")}, timeout=10))
    slow = check(client.post(BASE + f"/botlab/{team}/sandbox", data={"opponent": "random", "seed": 102}, timeout=10), 202)
    wait_job(client, slow["id"], {"running"}, limit=30)
    # Wait for the evaluator container rather than only a worker claim.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        detail = check(admin.get(BASE + "/api/admin/jobs/" + slow["id"], timeout=10))
        if any(event["stage"] == "container" for event in detail["pipeline"]):break
        time.sleep(.5)
    assert any(event["stage"] == "container" for event in detail["pipeline"]), detail
    cancelled = check(admin.post(BASE + f"/api/admin/jobs/{slow['id']}/cancel",
                                 json={"confirmation": "CANCEL", "reason": "real container stop test"}, timeout=10))
    assert cancelled["stopPending"] is True
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        detail = check(admin.get(BASE + "/api/admin/jobs/" + slow["id"], timeout=10))
        if any(event["stage"] == "execution" and event["status"] == "cancelled" for event in detail["pipeline"]):break
        time.sleep(.5)
    assert any(event["stage"] == "execution" and event["status"] == "cancelled" for event in detail["pipeline"]), detail
    remaining = subprocess.run(["docker", "ps", "-a", "--filter", "name=farmcraft-eval-", "--format", "{{.Names}}"],
                               capture_output=True, text=True, timeout=10, check=True)
    assert not remaining.stdout.strip(), remaining.stdout
    assert check(admin.get(BASE + "/api/admin/jobs/" + slow["id"], timeout=10))["status"] == "cancelled"
    print({"team": team, "validJob": queued["id"], "score": completed["result"]["botFinalMoney"],
           "officialJob": official_id, "rating": official_done["result"]["rating"],
           "replay": completed["result"]["replayId"], "failedBotJob": failed["id"],
           "cancelledJob": slow["id"], "orphanContainers": 0})


if __name__ == "__main__":
    main()
