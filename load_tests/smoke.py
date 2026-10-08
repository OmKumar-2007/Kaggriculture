"""End-to-end smoke check against the isolated Compose stack only."""
from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


def main() -> int:
    base = os.getenv("FARMCRAFT_SMOKE_URL", "http://127.0.0.1:18000").rstrip("/")
    parsed = urlparse(base)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.port != 18000:
        raise SystemExit("Smoke test is restricted to the isolated local port 18000.")
    team = "smoke_" + secrets.token_hex(4)
    client = requests.Session()
    health = client.get(base + "/ready", timeout=5)
    health.raise_for_status()
    assert health.json()["status"] == "ready"
    login = client.post(base + "/api/participants/session", json={"team": team}, timeout=5)
    login.raise_for_status()
    client.headers.update({"X-Participant-CSRF": login.json()["csrfToken"]})
    unauth = requests.get(base + f"/botlab/{team}", timeout=5)
    assert unauth.status_code == 401, unauth.text
    no_csrf = client.post(base + "/api/participants/heartbeat", json={"idle": False}, headers={"X-Participant-CSRF": "wrong"}, timeout=5)
    assert no_csrf.status_code == 403, no_csrf.text
    fixture = Path(__file__).with_name("agent.py").read_bytes()
    uploaded = client.post(base + "/botlab/upload", data={"username": team}, files={"agent": ("main.py", fixture, "text/x-python")}, timeout=10)
    uploaded.raise_for_status()
    submission = uploaded.json()["submission"]
    assert uploaded.json()["validation"]["valid"], uploaded.text
    queued = client.post(base + f"/botlab/{team}/sandbox", data={"opponent": "random", "seed": 1}, timeout=10)
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = client.get(base + f"/jobs/{job_id}", timeout=5).json()
        if job["status"] in ("completed", "failed", "timeout"):
            break
        time.sleep(1)
    else:
        raise AssertionError("Sandbox job did not finish within 60 seconds.")
    assert job["status"] == "completed", job
    summary = client.get(base + f"/botlab/{team}", timeout=5)
    summary.raise_for_status()
    assert summary.json()["sandboxRunCount"] >= 1
    official = client.post(base + f"/botlab/{team}/submit", timeout=10)
    assert official.status_code == 202, official.text
    official_id = official.json()["id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        evaluated = client.get(base + f"/jobs/{official_id}", timeout=5).json()
        if evaluated["status"] in ("completed", "failed", "timeout"):
            break
        time.sleep(1)
    else:
        raise AssertionError("Official job did not finish within 60 seconds.")
    assert evaluated["status"] == "completed", evaluated
    board = client.get(base + "/leaderboard", timeout=5)
    board.raise_for_status()
    assert any(entry.get("username", entry.get("team")) == team for entry in board.json()["entries"]), board.text
    print({"team": team, "submissionId": submission["id"], "sandboxJob": job_id,
           "officialJob": official_id, "officialRating": evaluated["result"]["rating"], "leaderboard": "updated"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
