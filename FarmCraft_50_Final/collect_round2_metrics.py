"""Sample live Round 2 tournament job and four worker heartbeats."""

import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone

import requests

ROOT = Path(__file__).resolve().parent
BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
EXPECTED = {"farmcraft-kr-01", "farmcraft-kr-02", "farmcraft-id-01", "farmcraft-id-02"}
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


out = ROOT / "private-evidence/round2_worker_samples.jsonl"
out.parent.mkdir(exist_ok=True)
seen = False
deadline = time.monotonic() + 120 * 60
with out.open("a", encoding="utf-8") as file:
    while time.monotonic() < deadline:
        try:
            phase = get("/api/admin/competition")["phase"]
            tournament = get("/api/admin/tournament")
            workers = get("/api/admin/remote-workers")["workers"]
            jobs = get("/api/admin/jobs?job_type=tournament&limit=500")["jobs"]
            if any(row["status"] in ("queued", "running", "completed") for row in jobs):
                seen = True
            row = {"at": datetime.now(timezone.utc).isoformat(), "phase": phase,
                   "tournamentStatus": tournament["status"],
                   "round": tournament.get("currentRound"),
                   "matches": len(tournament.get("allMatches", [])),
                   "jobs": [{"id": job["id"], "status": job["status"]} for job in jobs],
                   "workers": [{"name": worker["name"], "status": worker["status"],
                                "availableSlots": worker.get("availableSlots"),
                                "lastHeartbeat": worker.get("lastHeartbeat")}
                               for worker in workers if worker["name"] in EXPECTED]}
            file.write(json.dumps(row) + "\n")
            file.flush()
            if seen:
                print(json.dumps({"at": row["at"], "phase": phase,
                                  "round": row["round"], "matches": row["matches"],
                                  "busyWorkers": sum(w["availableSlots"] == 0 for w in row["workers"])}),
                      flush=True)
            if seen and phase == "TOURNAMENT_COMPLETED":
                break
        except Exception as exc:
            file.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                   "sampleError": str(exc)[:300]}) + "\n")
            file.flush()
        time.sleep(15)
