"""Sample Azure staging queue and worker utilization during the load test."""

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


out = ROOT / "private-evidence" / "worker_samples.jsonl"
out.parent.mkdir(exist_ok=True)
deadline = time.monotonic() + 120 * 60
seen_rehearsal_jobs = False
with out.open("a", encoding="utf-8") as file:
    while time.monotonic() < deadline:
        try:
            workers = get("/api/admin/remote-workers")["workers"]
            jobs = get("/api/admin/jobs?job_type=official&limit=500")["jobs"]
            rehearsal = [row for row in jobs if row.get("team") in
                         {f"LOAD50_20261013_{n:03d}" for n in range(1, 51)}]
            if rehearsal:
                seen_rehearsal_jobs = True
            counts = {status: sum(row["status"] == status for row in rehearsal)
                      for status in ("queued", "running", "completed", "failed", "timeout", "cancelled")}
            row = {"at": datetime.now(timezone.utc).isoformat(), "jobs": counts,
                   "workers": [{"name": worker["name"], "status": worker["status"],
                                "availableSlots": worker.get("availableSlots"),
                                "lastHeartbeat": worker.get("lastHeartbeat")}
                               for worker in workers if worker["name"] in EXPECTED]}
            file.write(json.dumps(row) + "\n")
            file.flush()
            print(json.dumps({"at": row["at"], **counts,
                              "busyWorkers": sum(w["availableSlots"] == 0 for w in row["workers"])}),
                  flush=True)
            if seen_rehearsal_jobs and counts["completed"] + counts["failed"] + counts["timeout"] + counts["cancelled"] == 50:
                break
        except Exception as exc:
            file.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                   "sampleError": str(exc)[:300]}) + "\n")
            file.flush()
        time.sleep(15)
