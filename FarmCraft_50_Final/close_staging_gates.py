"""Close public staging gates before a verified rehearsal backup/reset."""

import json
import os
import requests

BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
EXPECTED = {"Beta", "Codewarts", "Dark", "DM", "Eleven", "elonmusk", "FarmCraft",
            "Nimbus2000", "sdec_test", "team", "TeamMasterBlaster_TheWinner",
            "temp1", "TheGodfather", "X", "y", "Z"}
password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD")
session = requests.Session()
response = session.post(BASE + "/api/admin/login", json={"password": password}, timeout=30)
response.raise_for_status()
password = None
session.headers["x-admin-csrf"] = response.json()["csrfToken"]


def get(path):
    response = session.get(BASE + path, timeout=30)
    response.raise_for_status()
    return response.json()


teams = {item["team"] for item in get("/api/admin/contestants")["contestants"]}
assert teams == EXPECTED, f"Team inventory changed: {len(teams)} teams. Refusing mutation."
jobs = get("/api/admin/jobs?limit=500")["jobs"]
assert not any(item["status"] in ("queued", "running") for item in jobs), "Active jobs remain"
event = get("/api/admin/event")
fields = ("mode", "registrationsEnabled", "uploadsEnabled", "sandboxEnabled",
          "officialEnabled", "tournamentEnabled", "leaderboardVisible",
          "submissionLimit", "submissionCooldownSeconds")
payload = {key: event[key] for key in fields if key in event}
payload.update(mode="MAINTENANCE", registrationsEnabled=False, uploadsEnabled=False,
               sandboxEnabled=False, officialEnabled=False, tournamentEnabled=False,
               leaderboardVisible=False)
response = session.put(BASE + "/api/admin/event", json=payload, timeout=30)
response.raise_for_status()
after = response.json()
assert after["mode"] == "MAINTENANCE" and not any(after[key] for key in
    ("registrationsEnabled", "uploadsEnabled", "sandboxEnabled", "officialEnabled", "tournamentEnabled"))
print(json.dumps({"gatesClosed": True, "teamCount": len(teams),
                  "phase": get("/api/admin/competition")["phase"]}))
