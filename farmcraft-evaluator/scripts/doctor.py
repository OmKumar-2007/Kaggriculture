"""Read-only evaluator prerequisite check plus one isolated sample match."""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path

import psutil
import requests

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
sys.path.insert(0, str(PACKAGE / "app"))
sys.path.insert(0, str(ROOT))
from configuration import VERSION, settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-match", action="store_true", help="Only inspect prerequisites")
    args = parser.parse_args()
    config = settings()
    print("Platform:", platform.platform(), platform.machine())
    print("Python:", sys.version.split()[0])
    if sys.version_info < (3, 11) or sys.version_info >= (3, 13):
        raise SystemExit("Python 3.11 or 3.12 is required.")
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(ROOT))
    print(f"RAM available: {memory.available / 1024**3:.1f} GiB; disk free: {disk.free / 1024**3:.1f} GiB")
    if memory.available < 2 * 1024**3 or disk.free < 2 * 1024**3:
        raise SystemExit("At least 2 GiB available RAM and disk are required.")
    docker = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                            capture_output=True, text=True, timeout=20, check=False)
    if docker.returncode:
        raise SystemExit("Docker daemon is unavailable. Start Docker Desktop or Docker Engine.")
    print("Docker:", docker.stdout.strip())
    version = requests.get(config["FARMCRAFT_API_URL"] + "/api/remote-workers/version", timeout=90)
    version.raise_for_status()
    if version.json().get("evaluatorVersion") != VERSION:
        raise SystemExit("Cloud evaluator version differs from this checkout. Update the checkout before registering.")
    local_hash = hashlib.sha256((ROOT / "config" / "evaluation.json").read_bytes()).hexdigest()
    if version.json().get("evaluationConfigSha256") != local_hash:
        raise SystemExit("Cloud evaluation configuration differs from this checkout.")
    print("Cloud version:", VERSION)
    if args.skip_match: return
    for key in ("EVALUATOR_IMAGE", "EVALUATION_TIMEOUT_SECONDS", "EVALUATION_MEMORY_MB",
                "EVALUATION_CPU_LIMIT", "EVALUATION_PIDS_LIMIT"):
        if key in config: os.environ[key] = str(config[key])
    import backend.services.sandbox as sandbox
    sandbox.DOCKER_IMAGE = config["EVALUATOR_IMAGE"]
    source = (ROOT / "NITW_Farm_AI_Challenge_v1" / "examples" / "starter_agent.py").read_text(encoding="utf-8")
    result = sandbox.run_sandbox_source(source, "random", 41021)
    if result.get("status") != "success":
        raise SystemExit(f"Sample match failed: {result.get('error')}")
    print("Isolated sample match passed. Winner:", result.get("winner"))


if __name__ == "__main__": main()
