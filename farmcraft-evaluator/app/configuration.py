"""Portable, local-only evaluator configuration; secrets live in credentials.json."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
VERSION = (PACKAGE / "VERSION").read_text(encoding="utf-8").strip()


def profile_path(variable: str, default: str) -> Path:
    """Allow the launcher to select isolated Azure/Render worker identity files."""
    path = Path(os.environ.get(variable, str(PACKAGE / default))).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError(f"{variable} must remain inside the FarmCraft checkout.")
    return path


def settings() -> dict:
    values = {}
    path = profile_path("FARMCRAFT_WORKER_ENV_FILE", ".env")
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({key: value for key, value in os.environ.items() if key in {
        "FARMCRAFT_API_URL", "WORKER_NAME", "WORKER_CONCURRENCY", "WORKER_HEARTBEAT_SECONDS",
        "WORKER_POLL_SECONDS", "EVALUATION_TIMEOUT_SECONDS", "EVALUATION_MEMORY_MB",
        "EVALUATION_CPU_LIMIT", "EVALUATION_PIDS_LIMIT", "EVALUATOR_IMAGE"}})
    url = values.get("FARMCRAFT_API_URL", "").rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")):
        raise ValueError("FARMCRAFT_API_URL must use HTTPS (localhost may use HTTP for development).")
    values["FARMCRAFT_API_URL"] = url
    values["WORKER_CONCURRENCY"] = max(1, min(int(values.get("WORKER_CONCURRENCY", "2")), 16))
    values["WORKER_HEARTBEAT_SECONDS"] = max(5, min(int(values.get("WORKER_HEARTBEAT_SECONDS", "15")), 30))
    values["WORKER_POLL_SECONDS"] = max(3, min(int(values.get("WORKER_POLL_SECONDS", "8")), 60))
    values["WORKER_NAME"] = values.get("WORKER_NAME", "FarmCraft Evaluator")
    values["EVALUATOR_IMAGE"] = values.get("EVALUATOR_IMAGE", f"nitw-farm-ai-evaluator:{VERSION}")
    return values


def credentials() -> dict:
    path = profile_path("FARMCRAFT_WORKER_CREDENTIAL_FILE", "credentials.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("workerId") or not data.get("credential"):
        raise ValueError("Worker credentials are missing. Run setup and register this laptop.")
    return data
