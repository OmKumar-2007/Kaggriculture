"""Open Round 1 through the admin API on the isolated port 18000 only."""
from __future__ import annotations

import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:18000"
ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ROOT / "NITW_Farm_AI_Challenge_v1/examples/random_agent.py",
    ROOT / "NITW_Farm_AI_Challenge_v1/examples/starter_agent.py",
    ROOT / "NITW_Farm_AI_Challenge_v1/examples/example_agent.py",
    ROOT / "benchmarks/balanced_agent.py",
    ROOT / "benchmarks/trader_agent.py",
]


def checked(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text)
    return response.json()


def main():
    session = requests.Session()
    checked(session.get(BASE + "/ready", timeout=10))
    login = checked(session.post(BASE + "/api/admin/login",
                                 json={"password": "load-test-organizer"}, timeout=10))
    session.headers["X-Admin-CSRF"] = login["csrfToken"]
    competition = checked(session.get(BASE + "/api/admin/competition", timeout=10))
    assert competition["phase"] == "SETUP", "Use a fresh isolated rehearsal stack."
    for index, source in enumerate(SOURCES, 1):
        bot = checked(session.post(BASE + "/api/admin/reference-bots",
                                   data={"displayName": f"Smoke Reference {index}"},
                                   files={"file": ("agent.py", source.read_bytes(), "text/x-python")},
                                   timeout=10))
        job = checked(session.post(BASE + f"/api/admin/reference-bots/{bot['id']}/test",
                                   timeout=10))["job"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            result = checked(session.get(BASE + f"/api/admin/jobs/{job['id']}", timeout=10))
            if result["status"] in ("completed", "failed", "timeout"):
                break
            time.sleep(1)
        assert result["status"] == "completed", result
        checked(session.put(BASE + f"/api/admin/reference-bots/{bot['id']}",
                            json={"selected": True}, timeout=10))
        print(f"Reference {index}: tested and selected", flush=True)
    opened = checked(session.post(BASE + "/api/admin/competition/start-qualification",
                                  json={"confirmation": "START QUALIFICATION"}, timeout=10))
    assert opened["phase"] == "QUALIFICATION_OPEN", opened
    print("Round 1 open on isolated rehearsal stack.")


if __name__ == "__main__":
    main()
