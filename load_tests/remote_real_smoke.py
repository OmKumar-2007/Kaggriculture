"""Isolated remote-protocol smoke with real Docker sandbox and official jobs."""
from __future__ import annotations

import os
import hashlib
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "farmcraft-evaluator"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PACKAGE / "app"))

from backend.services.blob_storage import LocalObjectStorage
from backend.services.storage import PlatformStore


def main():
    port = 18081
    url = f"http://127.0.0.1:{port}"
    version = (PACKAGE / "VERSION").read_text(encoding="utf-8").strip()
    image = f"nitw-farm-ai-evaluator:{version}"
    subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=True)
    with tempfile.TemporaryDirectory(prefix="farmcraft-remote-smoke-") as directory:
        root = Path(directory)
        database = root / "event.db"
        env = os.environ.copy()
        env.update({"DATABASE_URL": f"sqlite:///{database.as_posix()}", "QUEUE_BACKEND": "postgres",
                    "STORAGE_BACKEND": "local", "LOCAL_STORAGE_ROOT": str(root / "objects"),
                    "APP_ENV": "development", "FARMCRAFT_EVALUATOR_VERSION": version})
        log = (root / "server.log").open("wb")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app",
                                    "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=flags)
        try:
            for _ in range(60):
                try:
                    if requests.get(url + "/health", timeout=2).status_code == 200: break
                except requests.RequestException: pass
                time.sleep(1)
            else: raise RuntimeError("Isolated API failed to start.")
            store = PlatformStore(database)
            objects = LocalObjectStorage(root / "objects")
            token = store.issue_worker_registration()
            registered = requests.post(url + "/api/remote-workers/register",
                json={"token": token, "name": "Smoke Laptop", "version": version}, timeout=30)
            registered.raise_for_status()
            identity = registered.json()
            import worker
            import runner
            worker.execute = runner.execute
            config = {"FARMCRAFT_API_URL": url, "EVALUATOR_IMAGE": image,
                      "WORKER_CONCURRENCY": 1, "WORKER_HEARTBEAT_SECONDS": 15,
                      "WORKER_POLL_SECONDS": 5}
            store.register_team("remote_smoke")
            key = "submissions/remote_smoke/agent.py"
            source = (ROOT / "NITW_Farm_AI_Challenge_v1" / "examples" / "starter_agent.py").read_bytes()
            objects.put_bytes(key, source, "text/x-python")
            submission = store.create_submission("remote_smoke", key, valid=True)
            reference = (ROOT / "NITW_Farm_AI_Challenge_v1" / "examples" / "random_agent.py").read_bytes()
            reference_key = "references/remote_smoke/random.py"
            objects.put_bytes(reference_key, reference, "text/x-python")
            from backend.services.scoring import load_scoring_config
            qualification = {**load_scoring_config(), "opponents": ["ref_1"],
                             "seeds": [41021], "sides": [0, 1]}
            official_payload = {"evaluationConfig": qualification,
                                "submissionSha256": hashlib.sha256(source).hexdigest(),
                                "referencePool": [{"id": 1, "objectKey": reference_key,
                                                   "sha256": hashlib.sha256(reference).hexdigest()}]}
            client = worker.Client(config, identity)
            for kind in ("sandbox", "official"):
                job = store.create_job("remote_smoke", kind, submission_id=submission["id"],
                                       opponent="random" if kind == "sandbox" else None,
                                       seed=41021 if kind == "sandbox" else None,
                                       payload=official_payload if kind == "official" else None)
                claimed = client.claim()
                assert claimed and claimed["id"] == job["id"], "Remote worker did not claim the job."
                worker.run_job(config, identity, claimed)
                finished = store.get_job(job["id"])
                assert finished["status"] == "completed", f"{kind}: {finished['status']} {finished['error']}"
                print(f"{kind}: completed, result={finished['result'].get('rating', finished['result'].get('winner'))}")
            assert store.leaderboard_entry("remote_smoke"), "Official rating did not reach leaderboard."
            hanging = b"def agent(obs):\n    while True:\n        pass\n"
            hang_key = "submissions/remote_smoke/hanging.py"
            objects.put_bytes(hang_key, hanging, "text/x-python")
            hang_submission = store.create_submission("remote_smoke", hang_key, valid=True)
            stop_job = store.create_job("remote_smoke", "sandbox", submission_id=hang_submission["id"],
                                        opponent="random", seed=41021)
            claimed = client.claim()
            thread = threading.Thread(target=worker.run_job, args=(config, identity, claimed), daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                names = subprocess.run(["docker", "ps", "--filter", "name=farmcraft-eval-", "--format", "{{.Names}}"],
                                       capture_output=True, text=True, check=True).stdout.strip()
                if names: break
                time.sleep(.5)
            else: raise RuntimeError("The cancellable Docker evaluation never started.")
            store.request_job_cancel(stop_job["id"], "Isolated cancellation smoke")
            thread.join(timeout=40)
            assert not thread.is_alive(), "Cancelled evaluation did not terminate promptly."
            assert store.get_job(stop_job["id"])["status"] == "cancelled"
            remaining = subprocess.run(["docker", "ps", "--filter", "name=farmcraft-eval-", "--format", "{{.Names}}"],
                                       capture_output=True, text=True, check=True).stdout.strip()
            assert not remaining, f"Evaluator containers remain: {remaining}"
            print("Remote protocol, real Docker execution, cancellation cleanup, and leaderboard passed.")
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            log.close()


if __name__ == "__main__": main()
