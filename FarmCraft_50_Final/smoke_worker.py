"""Queue one real reference evaluation and confirm worker result persistence."""

import argparse
import json
import os
import time
import requests

BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
EXPECTED = {"farmcraft-kr-01", "farmcraft-kr-02", "farmcraft-id-01", "farmcraft-id-02"}
parser = argparse.ArgumentParser()
parser.add_argument("--job-id")
args = parser.parse_args()
password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD")
session = requests.Session()
response = session.post(BASE + "/api/admin/login", json={"password": password}, timeout=30)
response.raise_for_status()
password = None
session.headers["x-admin-csrf"] = response.json()["csrfToken"]


def call(method, path):
    response = session.request(method, BASE + path, timeout=30)
    response.raise_for_status()
    return response.json()


event = call("GET", "/api/admin/event")
assert event["mode"] == "MAINTENANCE" and not any(event[key] for key in
    ("registrationsEnabled", "uploadsEnabled", "sandboxEnabled", "officialEnabled", "tournamentEnabled"))
assert call("GET", "/api/admin/competition")["phase"] == "SETUP"
assert not call("GET", "/api/admin/contestants")["contestants"]
refs = call("GET", "/api/admin/reference-bots")["bots"]
selected = [x for x in refs if x["selected"] and x["enabled"] and not x["archived"]]
assert len(selected) == 3
job_id = args.job_id or call("POST", f"/api/admin/reference-bots/{selected[0]['id']}/test")["job"]["id"]
if not args.job_id:
    print(json.dumps({"smokeJobId": job_id, "status": "queued"}), flush=True)
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    job = call("GET", f"/api/admin/jobs/{job_id}")
    if job["status"] in ("completed", "failed", "timeout", "cancelled"):
        break
    time.sleep(5)
else:
    raise TimeoutError(f"Smoke job {job_id} did not finish in 300 seconds")
assert job["status"] == "completed", job["status"]
workers = call("GET", "/api/admin/remote-workers")["workers"]
by_id = {row["id"]: row["name"] for row in workers}
worker_name = by_id.get(job.get("worker"))
assert worker_name in EXPECTED, {"workerId": job.get("worker"), "name": worker_name}
persisted = call("GET", f"/api/admin/jobs/{job_id}")
assert persisted["status"] == "completed" and persisted.get("result")
print(json.dumps({"smokeJobId": job_id, "status": "completed",
                  "worker": worker_name, "persisted": True}), flush=True)
