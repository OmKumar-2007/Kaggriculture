"""Sample real Azure staging Admin metrics during the 30-team rehearsal."""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/FARMCRAFT_30_TEAM_WORKER_METRICS.csv"
BASE = "https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io"


def get(session, path):
    response = session.get(BASE + path, timeout=30)
    response.raise_for_status()
    return response.json()


def main():
    password = os.environ.pop("FARMCRAFT_STAGING_ADMIN_PASSWORD")
    session = requests.Session()
    response = session.post(BASE + "/api/admin/login", json={"password": password}, timeout=30)
    response.raise_for_status()
    password = None
    session.headers["x-admin-csrf"] = response.json()["csrfToken"]
    OUT.parent.mkdir(exist_ok=True)
    columns = ["atUtc", "apiP95LatencyMs", "queueJson", "workerName", "workerStatus",
               "availableSlots", "maxConcurrency", "lastHeartbeat", "telemetryJson", "error"]
    with OUT.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for _ in range(240):
            at = datetime.now(timezone.utc).isoformat()
            try:
                metrics = get(session, "/api/admin/metrics")
                workers = get(session, "/api/admin/remote-workers")["workers"]
                for worker in workers:
                    if worker["name"] not in {"farmcraft-kr-01", "farmcraft-kr-02", "farmcraft-id-01", "farmcraft-id-02"}:
                        continue
                    writer.writerow({"atUtc": at,
                        "apiP95LatencyMs": (metrics.get("api") or {}).get("p95LatencyMs"),
                        "queueJson": json.dumps(metrics.get("queues", {}), separators=(",", ":")),
                        "workerName": worker["name"], "workerStatus": worker.get("status"),
                        "availableSlots": worker.get("availableSlots"),
                        "maxConcurrency": worker.get("maxConcurrency"),
                        "lastHeartbeat": worker.get("lastHeartbeat"),
                        "telemetryJson": json.dumps(worker.get("telemetry", {}), separators=(",", ":"))})
            except Exception as exc:
                writer.writerow({"atUtc": at, "error": str(exc)[:250]})
            stream.flush()
            time.sleep(30)


if __name__ == "__main__":
    main()
