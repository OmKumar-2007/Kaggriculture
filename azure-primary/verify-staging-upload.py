"""Verify a real Bot Lab upload on the existing isolated staging fixture."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"
TEAM = "E2E_ALPHA_261012"
ROOT = Path(__file__).resolve().parents[1]


def checked(response: requests.Response) -> dict:
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code} from {response.url}: {response.text[:300]}")
    return response.json()


def main() -> None:
    password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD", None)
    if not password:
        raise RuntimeError("Protected staging Admin password is required.")
    admin = requests.Session()
    login = checked(admin.post(BASE + "/api/admin/login", json={"password": password}, timeout=30))
    password = None
    admin.headers["x-admin-csrf"] = login["csrfToken"]
    event = checked(admin.get(BASE + "/api/admin/event", timeout=30))
    print(f"event mode={event['mode']} uploadsEnabled={event['uploadsEnabled']} phase independent")
    if not event["uploadsEnabled"]:
        raise RuntimeError("Upload gate is closed; no attempt made.")

    issued = checked(admin.post(BASE + f"/api/admin/contestants/{TEAM}/recovery",
                                json={"confirmation": "RESET SESSION", "reason": "Staging upload verification"},
                                timeout=30))
    user = requests.Session()
    session = checked(user.post(BASE + "/api/participants/recover",
                                json={"team": TEAM, "recoveryCode": issued["recoveryCode"]}, timeout=30))
    user.headers["x-participant-csrf"] = session["csrfToken"]
    before = checked(user.get(BASE + f"/botlab/{TEAM}", timeout=30))
    verify_only = "--verify-only" in sys.argv
    if not verify_only:
        source = (ROOT / "FarmCraft_50_Full_Rehearsal" / "bots" / "FC26_R50_001" / "agent.py").read_bytes()
        uploaded = checked(user.post(BASE + "/botlab/upload", data={"username": TEAM},
                                     files={"agent": ("agent.py", source, "text/x-python")}, timeout=60))
        assert uploaded["validation"]["valid"], uploaded["validation"]
    after = checked(user.get(BASE + f"/botlab/{TEAM}", timeout=30))
    before_version = int(str(before["currentVersion"]).removeprefix("v"))
    after_version = int(str(after["currentVersion"]).removeprefix("v"))
    if not verify_only:
        assert after_version == before_version + 1
        assert after_version == uploaded["submission"]["version"]
    else:
        assert after_version >= 3
    validation = checked(user.post(BASE + f"/botlab/{TEAM}/validate", timeout=30))
    assert validation["valid"]
    print(f"PASS {TEAM}: current version {after['currentVersion']}; source validation passed")
    if "--check-official-gate" in sys.argv:
        official = user.post(BASE + f"/botlab/{TEAM}/submit", timeout=30)
        assert official.status_code == 423, (official.status_code, official.text[:200])
        print("PASS official gate: HTTP 423 while completed rehearsal bracket is preserved")
    if "--sandbox" in sys.argv or "--check-existing-job" in sys.argv:
        assert event["sandboxEnabled"]
        if "--check-existing-job" in sys.argv:
            job = {"id": "8b006c7b-4277-4e87-a776-0c44583ecedf"}
        else:
            job = checked(user.post(BASE + f"/botlab/{TEAM}/sandbox",
                                    data={"opponent": "starter_crop", "seed": 20261012}, timeout=30))
            print(f"Sandbox queued: {job['id']}")
        for _ in range(90):
            current = checked(user.get(BASE + f"/jobs/{job['id']}", timeout=30))
            if current["status"] in ("completed", "failed", "timeout", "cancelled"):
                break
            time.sleep(3)
        else:
            raise RuntimeError("Sandbox did not finish within 270 seconds.")
        if current["status"] != "completed":
            raise RuntimeError(f"Sandbox status={current['status']} error={current.get('error')}")
        replay_id = current["result"]["replayId"]
        checked(user.get(BASE + f"/replays/{replay_id}/analytics", timeout=30))
        if "--check-playback" in sys.argv:
            bundle = checked(user.get(BASE + f"/replays/{replay_id}/playback", timeout=90))
            assert bundle["totalSteps"] == len(bundle["players"][0]) > 0
            print(f"PASS playback: {bundle['totalSteps']} frames; first frame available")
        print(f"PASS sandbox: job={job['id']} replay analytics readable")


if __name__ == "__main__":
    main()
