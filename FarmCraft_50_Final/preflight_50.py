"""Read-only snapshot of the Azure staging event for the 50-team rehearsal."""

import json
import os
import requests

BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD")
session = requests.Session()
login = session.post(BASE + "/api/admin/login", json={"password": password}, timeout=30)
login.raise_for_status()
password = None
session.headers["x-admin-csrf"] = login.json()["csrfToken"]


def get(path):
    response = session.get(BASE + path, timeout=30)
    response.raise_for_status()
    return response.json()


event = get("/api/admin/event")
competition = get("/api/admin/competition")
workers = get("/api/admin/remote-workers")["workers"]
contestants = get("/api/admin/contestants")["contestants"]
jobs = get("/api/admin/jobs?limit=500")["jobs"]
references = get("/api/admin/reference-bots")["bots"]
standings = get("/api/admin/competition/standings")["entries"]
print(json.dumps({
    "ready": get("/ready"),
    "event": event,
    "phase": competition["phase"],
    "settings": competition["settings"],
    "contestantCount": len(contestants),
    "standingsCount": len(standings),
    "referenceBotCount": len(references),
    "selectedReferenceBotCount": sum(item.get("selected") and item.get("enabled") and not item.get("archived") for item in references),
    "contestantTeams": [x["team"] for x in contestants],
    "workers": [{"name": x["name"], "status": x["status"],
                 "availableSlots": x.get("availableSlots"), "lastHeartbeat": x.get("lastHeartbeat")}
                for x in workers],
    "activeJobs": [{"id": x["id"], "status": x["status"], "type": x.get("jobType")}
                   for x in jobs if x["status"] in ("queued", "running")],
}, indent=2))
