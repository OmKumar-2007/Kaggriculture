"""Actual laptop and evaluator telemetry, sampled by the trusted host worker."""
from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from backend.services.queueing import QUEUE_PRIORITY, redis_connection

CURRENT = "arena:telemetry:host"
HISTORY = "arena:telemetry:history"
ALERTS = "arena:telemetry:alerts"
_last_network: tuple[float, int, int] | None = None
_worker_process = psutil.Process()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _metric_alerts(connection, sample: dict, history: list[dict]) -> None:
    recent = (history + [sample])[-3:]
    sustained = len(recent) == 3
    cpu_limit = float(os.getenv("HOST_CPU_WARNING_PERCENT", "85"))
    ram_limit = float(os.getenv("HOST_RAM_WARNING_PERCENT", "90"))
    free_limit = float(os.getenv("HOST_DISK_CRITICAL_GIB", "2")) * 1024**3
    conditions = {
        "cpu": ("warning", f"CPU stayed above {cpu_limit:g}%.", sustained and all(x["cpuPercent"] >= cpu_limit for x in recent)),
        "memory": ("warning", f"RAM stayed above {ram_limit:g}%.", sustained and all(x["ramPercent"] >= ram_limit for x in recent)),
        "disk": ("critical", f"Less than {free_limit / 1024**3:g} GiB of disk space remains.", min(sample["diskFreeBytes"], sample["dataDiskFreeBytes"]) < free_limit),
        "queue": ("warning", "The evaluation queue is growing.", sustained and recent[-1]["queueLength"] > recent[0]["queueLength"] + 10),
        "failures": ("critical", "Evaluator failures increased repeatedly.", sustained and recent[-1]["failedJobs"] > recent[0]["failedJobs"] + 3),
    }
    for subsystem, (severity, message, active) in conditions.items():
        state_key = f"arena:telemetry:alert-state:{subsystem}"
        was_active = connection.get(state_key) == b"1"
        if active == was_active:
            continue
        connection.set(state_key, "1" if active else "0")
        event = {"at": sample["at"], "subsystem": subsystem, "severity": severity if active else "recovered",
                 "message": message if active else f"{subsystem.capitalize()} returned to normal.", "active": active}
        connection.lpush(ALERTS, json.dumps(event))
        connection.ltrim(ALERTS, 0, 39)


def publish_host_sample() -> dict:
    global _last_network
    connection = redis_connection()
    now = time.time()
    memory = psutil.virtual_memory()
    system_path = os.getenv("HOST_DISK_PATH", (os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else "/")
    data_path = os.getenv("LOCAL_STORAGE_ROOT", str(Path(__file__).resolve().parents[2]))
    disk = psutil.disk_usage(system_path)
    data_disk = psutil.disk_usage(data_path)
    network = psutil.net_io_counters()
    previous = _last_network
    elapsed = max(0.001, now - previous[0]) if previous else 1.0
    upload = max(0, (network.bytes_sent - previous[1]) / elapsed) if previous else 0
    download = max(0, (network.bytes_recv - previous[2]) / elapsed) if previous else 0
    _last_network = (now, network.bytes_sent, network.bytes_recv)
    queue_length = sum(connection.llen(f"rq:queue:{name}") for name in QUEUE_PRIORITY)
    from backend.services.storage import store
    from backend.services.participants import connected_devices
    jobs = store.admin_metrics()
    presence = connected_devices()
    prior_raw = connection.lindex(HISTORY, 11)
    prior = json.loads(prior_raw) if prior_raw else {}
    submitted_jobs = sum(jobs.get(key, 0) for key in ("queued", "running", "completed", "failed", "timeout", "cancelled"))
    sample = {"at": _now(), "node": os.getenv("WORKER_NODE_NAME", socket.gethostname()),
              "cpuPercent": round(psutil.cpu_percent(interval=None), 1), "ramUsedBytes": memory.used,
              "ramTotalBytes": memory.total, "ramAvailableBytes": memory.available,
              "ramPercent": memory.percent, "diskUsedBytes": disk.used, "diskTotalBytes": disk.total,
              "diskFreeBytes": disk.free, "diskPercent": disk.percent, "dataDiskFreeBytes": data_disk.free,
              "dataDiskPercent": data_disk.percent,
              "uploadBytesPerSecond": round(upload), "downloadBytesPerSecond": round(download),
              "uptimeSeconds": int(now - psutil.boot_time()), "queueLength": queue_length,
              "runningJobs": jobs.get("running", 0), "completedJobs": jobs.get("completed", 0),
              "failedJobs": jobs.get("failed", 0) + jobs.get("timeout", 0),
              "connectedTeams": presence["connectedTeams"], "submittedJobs": submitted_jobs,
              "submissionsLastMinute": max(0, submitted_jobs - prior.get("submittedJobs", submitted_jobs)),
              "completionsLastMinute": max(0, jobs.get("completed", 0) - prior.get("completedJobs", jobs.get("completed", 0))),
              "averageEvaluationSeconds": jobs.get("averageJobRuntime")}
    raw_history = connection.lrange(HISTORY, 0, 2)
    history = [json.loads(item) for item in reversed(raw_history)]
    _metric_alerts(connection, sample, history)
    with connection.pipeline() as pipe:
        pipe.setex(CURRENT, 30, json.dumps(sample))
        pipe.lpush(HISTORY, json.dumps(sample))
        pipe.ltrim(HISTORY, 0, 359)
        pipe.execute()
    return sample


def publish_worker_sample(worker_id: str, *, busy: bool) -> None:
    process = _worker_process
    payload = {"id": worker_id, "node": os.getenv("WORKER_NODE_NAME", socket.gethostname()),
               "status": "busy" if busy else "idle", "cpuPercent": process.cpu_percent(interval=None),
               "ramBytes": process.memory_info().rss, "maxConcurrency": 1, "at": _now()}
    redis_connection().setex(f"arena:telemetry:worker:{worker_id}", 30, json.dumps(payload))


def host_snapshot() -> dict:
    connection = redis_connection()
    current = connection.get(CURRENT)
    history = [json.loads(item) for item in reversed(connection.lrange(HISTORY, 0, 359))]
    alerts = [json.loads(item) for item in connection.lrange(ALERTS, 0, 39)]
    return {"current": json.loads(current) if current else None, "history": history, "alerts": alerts}


def worker_snapshot(worker_id: str) -> dict | None:
    payload = redis_connection().get(f"arena:telemetry:worker:{worker_id}")
    return json.loads(payload) if payload else None
