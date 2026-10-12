"""Drain or rearm the four known Azure worker registrations after the rehearsal."""

import argparse
import json
import os
import requests

BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
EXPECTED = {"farmcraft-kr-01", "farmcraft-kr-02", "farmcraft-id-01", "farmcraft-id-02"}
parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("drain", "resume"))
args = parser.parse_args()
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


event = get("/api/admin/event")
assert event["mode"] == "MAINTENANCE" and not any(event[key] for key in
    ("registrationsEnabled", "uploadsEnabled", "sandboxEnabled", "officialEnabled", "tournamentEnabled"))
assert get("/api/admin/competition")["phase"] == "SETUP"
assert not get("/api/admin/contestants")["contestants"]
assert not any(job["status"] in ("queued", "running") for job in get("/api/admin/jobs?limit=500")["jobs"])
workers = get("/api/admin/remote-workers")["workers"]
chosen = [worker for worker in workers if worker["name"] in EXPECTED]
assert {worker["name"] for worker in chosen} == EXPECTED
for worker in chosen:
    response = session.post(BASE + f"/api/admin/remote-workers/{worker['id']}/{args.action}",
                            json={"confirmation": args.action.upper()}, timeout=30)
    response.raise_for_status()
    print(json.dumps({"name": worker["name"], "mode": response.json()["status"]}), flush=True)
