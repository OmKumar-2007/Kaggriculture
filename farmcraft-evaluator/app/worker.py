"""Outbound-only FarmCraft evaluator controller."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil
import requests

from configuration import PACKAGE, VERSION, credentials, settings

STOP_FILE = PACKAGE / ".stop"


def telemetry(config: dict) -> dict:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(PACKAGE))
    docker = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                            capture_output=True, text=True, timeout=8, check=False)
    return {"cpuPercent": psutil.cpu_percent(interval=None), "ramBytes": memory.used,
            "ramAvailableBytes": memory.available, "ramTotalBytes": memory.total,
            "diskFreeBytes": disk.free, "diskUsedBytes": disk.used, "dockerHealthy": docker.returncode == 0,
            "dockerVersion": docker.stdout.strip()[:60] if docker.returncode == 0 else None,
            "maxConcurrency": config["WORKER_CONCURRENCY"], "evaluatorVersion": VERSION,
            "platform": platform.platform()[:120]}


class Client:
    def __init__(self, config: dict, identity: dict):
        self.config = config
        self.base = config["FARMCRAFT_API_URL"] + "/api/remote-workers"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {identity['workerId']}.{identity['credential']}"})

    def call(self, method: str, path: str, **kwargs):
        response = self.session.request(method, self.base + path, timeout=90, **kwargs)
        response.raise_for_status()
        return response

    def heartbeat(self, job=None):
        data = {"telemetry": telemetry(self.config)}
        if job: data.update({"jobId": job["id"], "attemptId": job["attemptId"]})
        return self.call("POST", "/heartbeat", json=data).json()

    def claim(self):
        return self.call("POST", "/claim").json()["job"]

    def source(self, job, submission_id: int) -> str:
        response = self.call("GET", f"/jobs/{job['id']}/source/{submission_id}",
                             params={"attemptId": job["attemptId"]})
        payload = response.content
        if len(payload) > 256 * 1024 or hashlib.sha256(payload).hexdigest() != response.headers.get("X-Source-SHA256"):
            raise ValueError("Submission download failed integrity or size checks.")
        return payload.decode("utf-8")

    def replay(self, job, replay_id: str, payload: bytes):
        if len(payload) > 8 * 1024 * 1024: raise ValueError("Replay exceeds upload limit.")
        self.call("PUT", f"/jobs/{job['id']}/replay/{replay_id}",
                  params={"attemptId": job["attemptId"]}, data=payload)

    def progress(self, job, stage, status, detail, current=None, total=None, event=None, data=None):
        self.call("POST", f"/jobs/{job['id']}/progress", json={"attemptId": job["attemptId"],
            "stage": stage, "status": status, "detail": str(detail)[:500], "current": current,
            "total": total, "tournamentEvent": event, "tournamentData": data})

    def result(self, job, result=None, error=None, error_kind=None):
        self.call("POST", f"/jobs/{job['id']}/result", json={"attemptId": job["attemptId"],
                  "result": result or {}, "error": error, "errorKind": error_kind})


def run_job(config: dict, identity: dict, job: dict):
    client = Client(config, identity)
    heartbeat_client = Client(config, identity)
    cancelled = threading.Event()
    stopped = threading.Event()

    def beat():
        failures = 0
        while not stopped.wait(config["WORKER_HEARTBEAT_SECONDS"]):
            try:
                response = heartbeat_client.heartbeat(job)
                failures = 0
                if response.get("cancel") or not response.get("valid"): cancelled.set()
            except Exception as exc:
                failures += 1
                print(f"Heartbeat failed for {job['id']}: {type(exc).__name__}", flush=True)
                if failures >= 3: cancelled.set()  # Lost lease: stop untrusted execution.

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        if heartbeat_client.heartbeat(job).get("cancel"):
            cancelled.set()
            return
        print(f"Running {job['type']} job {job['id']} attempt {job['attemptId']}", flush=True)
        result = execute(job, client, lambda: cancelled.is_set() or STOP_FILE.exists())
        if cancelled.is_set() or STOP_FILE.exists(): return
        if job["type"] == "sandbox" and result.get("contestantFailure"):
            client.result(job, result, error=result["contestantFailure"].get("error") or "Contestant failed",
                          error_kind="CONTESTANT_RUNTIME_ERROR")
        else:
            client.result(job, result)
        print(f"Finished job {job['id']}", flush=True)
    except Exception as exc:
        if not cancelled.is_set() and not STOP_FILE.exists():
            try: client.result(job, error=str(exc)[:8000], error_kind="WORKER_FAILURE")
            except Exception as report_exc:
                print(f"Result report failed for {job['id']}: {type(report_exc).__name__}", flush=True)
        print(f"Job {job['id']} failed: {type(exc).__name__}: {exc}", flush=True)
    finally:
        stopped.set()
        thread.join(timeout=2)


def register(config: dict):
    token = getpass.getpass("Single-use registration token: ").strip()
    response = requests.post(config["FARMCRAFT_API_URL"] + "/api/remote-workers/register",
        json={"token": token, "name": config["WORKER_NAME"], "version": VERSION}, timeout=90)
    response.raise_for_status()
    identity = response.json()
    save_identity(identity)
    print(f"Registered {config['WORKER_NAME']} ({identity['workerId']}). Credentials saved locally.")


def save_identity(identity: dict):
    target = PACKAGE / "credentials.json"
    pending = target.with_suffix(".pending")
    pending.write_text(json.dumps(identity), encoding="utf-8")
    if os.name != "nt": pending.chmod(0o600)
    else:
        account = os.environ.get("USERNAME", "")
        if not account: raise RuntimeError("Cannot secure worker credential: Windows username unavailable.")
        subprocess.run(["icacls", str(pending), "/inheritance:r", "/grant:r", f"{account}:F"],
                       capture_output=True, check=True, timeout=15)
    pending.replace(target)


def update_credential():
    worker_id, secret = getpass.getpass("Rotated worker ID.credential: ").strip().split(".", 1)
    save_identity({"workerId": worker_id, "credential": secret})
    print("Rotated credential saved locally. Restart the worker.")


def main():
    global execute
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--update-credential", action="store_true")
    args = parser.parse_args()
    config = settings()
    for key in ("EVALUATOR_IMAGE", "EVALUATION_TIMEOUT_SECONDS", "EVALUATION_MEMORY_MB",
                "EVALUATION_CPU_LIMIT", "EVALUATION_PIDS_LIMIT"):
        if key in config: os.environ[key] = str(config[key])
    from runner import execute as local_execute
    execute = local_execute
    if args.register:
        register(config)
        return
    if args.update_credential:
        update_credential()
        return
    identity = credentials()
    STOP_FILE.unlink(missing_ok=True)
    client = Client(config, identity)
    with ThreadPoolExecutor(max_workers=config["WORKER_CONCURRENCY"]) as pool:
        active = set()
        while not STOP_FILE.exists():
            active = {future for future in active if not future.done()}
            try:
                if not active:
                    status = client.heartbeat()
                    if status.get("cancel"):
                        time.sleep(config["WORKER_POLL_SECONDS"])
                        continue
                while len(active) < config["WORKER_CONCURRENCY"]:
                    job = client.claim()
                    if not job: break
                    active.add(pool.submit(run_job, config, identity, job))
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 401:
                    raise SystemExit("Worker credentials revoked or invalid. Re-register this laptop.") from exc
                print(f"Cloud request failed: {exc}", flush=True)
            except requests.RequestException as exc:
                print(f"Cloud unavailable: {type(exc).__name__}", flush=True)
            time.sleep(config["WORKER_POLL_SECONDS"])
        for future in active:
            try: future.result(timeout=int(os.getenv("EVALUATION_TIMEOUT_SECONDS", "120")) + 30)
            except Exception: pass


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("Worker shutting down.")
