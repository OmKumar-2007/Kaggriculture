"""Finish a two-team real bracket on the isolated localhost rehearsal stack."""
from __future__ import annotations

import time

import requests

BASE = "http://127.0.0.1:18000"


def checked(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text)
    return response.json()


def action(client, path, phrase, reason=None):
    body = {"confirmation": phrase}
    if reason:
        body["reason"] = reason
    return checked(client.post(BASE + "/api/admin" + path, json=body, timeout=10))


def verify_finished(client, job_id=None):
    state = checked(client.get(BASE + "/tournament/status", timeout=10))
    assert state["status"] == "champion" and state["champion"], state
    games = checked(client.get(BASE + "/api/admin/tournament/games", timeout=10))["games"]
    assert len(games) >= 2, games
    assert checked(client.get(BASE + "/api/admin/competition", timeout=10))["phase"] == "TOURNAMENT_COMPLETED"
    print({"qualifiers": 2, "pairings": 1, "games": len(games),
           "champion": state["champion"], "tournamentJob": job_id})


def main():
    client = requests.Session()
    checked(client.get(BASE + "/ready", timeout=10))
    login = checked(client.post(BASE + "/api/admin/login",
                                json={"password": "load-test-organizer"}, timeout=10))
    client.headers["X-Admin-CSRF"] = login["csrfToken"]
    competition = checked(client.get(BASE + "/api/admin/competition", timeout=10))
    if competition["phase"] == "TOURNAMENT_COMPLETED":
        verify_finished(client)
        return
    assert competition["phase"] == "QUALIFICATION_OPEN", competition["phase"]
    standings = checked(client.get(BASE + "/api/admin/competition/standings", timeout=10))["entries"]
    assert len(standings) >= 2, "Run two real official identity smokes first."
    settings = competition["settings"]
    cutoff = {name: settings[name] for name in ("qualifierCount", "registrationCapacity",
              "officialAttemptLimit", "referenceCount", "qualificationSeedCount", "tieReplayLimit")}
    cutoff["qualifierCount"] = 2
    updated = checked(client.put(BASE + "/api/admin/competition/settings", json=cutoff, timeout=10))
    assert updated["settings"]["qualifierCount"] == 2
    closed = action(client, "/competition/close-qualification", "CLOSE QUALIFICATION")
    assert closed["phase"] == "QUALIFICATION_CLOSING"
    failed = checked(client.get(BASE + "/api/admin/jobs", params={"job_type": "official",
                               "status": "failed", "limit": 500}, timeout=10))["jobs"]
    for job in failed:
        if not (job.get("errorKind") or "").startswith("CONTESTANT_"):
            action(client, f"/competition/jobs/{job['id']}/adjudicate",
                   "ADJUDICATE FAILURE", "Isolated smoke used a fake worker before real mode.")
    finalized = action(client, "/competition/finalize", "FINALIZE QUALIFICATION")
    assert len(finalized["qualifiers"]) == 2
    preview = checked(client.get(BASE + "/api/admin/competition/bracket-preview", timeout=10))
    assert preview["requiredPairings"] == 1 and preview["byes"] == 0, preview
    locked = action(client, "/competition/lock-bracket", "LOCK BRACKET")
    assert locked["qualifiers"] == 2
    started = action(client, "/tournament/start", "START TOURNAMENT")
    job_id = started["job"]["id"]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = checked(client.get(BASE + f"/api/admin/jobs/{job_id}", timeout=10))
        if job["status"] in ("completed", "failed", "timeout"):
            break
        time.sleep(1)
    assert job["status"] == "completed", job
    verify_finished(client, job_id)


if __name__ == "__main__":
    main()
