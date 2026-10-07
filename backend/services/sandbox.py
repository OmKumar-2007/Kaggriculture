"""Sandbox match execution against modest public benchmark agents."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from py_env import get_kaggle_python
from backend.services.analytics import analyze_replay


ROOT = Path(__file__).resolve().parents[2]
RUN_MATCH = ROOT / "run_match.py"
DOCKER_IMAGE = "nitw-farm-ai-evaluator"
MATCH_TIMEOUT_SECONDS = int(os.getenv("MATCH_TIMEOUT_SECONDS", "120"))
REPLAY_DIR = ROOT / "data" / "replays"
REPLAY_DIR.mkdir(parents=True, exist_ok=True)
BENCHMARKS = {
    "random": ROOT / "NITW_Farm_AI_Challenge_v1" / "examples" / "random_agent.py",
    "starter_crop": ROOT / "NITW_Farm_AI_Challenge_v1" / "examples" / "starter_agent.py",
    "balanced": ROOT / "benchmarks" / "balanced_agent.py",
    "trader": ROOT / "benchmarks" / "trader_agent.py",
    "animal": ROOT / "benchmarks" / "animal_agent.py",
}


class SandboxError(RuntimeError):
    pass


def list_benchmarks() -> list[dict]:
    labels = {"random": "Random Bot", "starter_crop": "Basic Farmer", "balanced": "Balanced Bot", "trader": "Basic Trader", "animal": "Basic Rancher"}
    return [{"id": key, "name": labels[key]} for key in BENCHMARKS]


def _parse_result(process: subprocess.CompletedProcess) -> dict:
    output = (process.stdout or "").strip()
    try:
        payload = json.loads(output.splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise SandboxError(f"Sandbox returned invalid output: {(process.stderr or output).strip()}") from exc
    if process.returncode != 0 or payload.get("error"):
        raise SandboxError(payload.get("error") or (process.stderr or "Sandbox process failed.").strip())
    return payload


def _run_local(agent_path: Path, opponent_path: Path, seed: int, replay_path: Path) -> dict:
    process = subprocess.run(
        [get_kaggle_python(), str(RUN_MATCH), "--agent1", str(agent_path), "--agent2", str(opponent_path),
         "--seed", str(seed), "--replay-output", str(replay_path)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=MATCH_TIMEOUT_SECONDS, check=False,
    )
    return _parse_result(process)


def _run_docker(agent_path: Path, opponent_path: Path, seed: int, replay_path: Path) -> dict:
    command = [
        "docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "512m",
        "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
        "-v", f"{agent_path.resolve()}:/competition/agent.py:ro",
        "-v", f"{opponent_path.resolve()}:/competition/opponent.py:ro",
        "-v", f"{replay_path.parent.resolve()}:/output:rw",
        "--entrypoint", "python", DOCKER_IMAGE, "/app/sandbox_worker.py",
        "--agent1", "/competition/agent.py", "--agent2", "/competition/opponent.py",
        "--seed", str(seed), "--steps", "720", "--replay-output", f"/output/{replay_path.name}",
    ]
    process = subprocess.run(command, capture_output=True, text=True, timeout=MATCH_TIMEOUT_SECONDS, check=False)
    return _parse_result(process)


def run_sandbox_source(source: str, opponent: str, seed: int, *, trusted_local: bool = False) -> dict:
    if opponent not in BENCHMARKS:
        raise SandboxError(f"Unknown opponent '{opponent}'.")
    if not 0 <= seed <= 2_147_483_647:
        raise SandboxError("Seed must be between 0 and 2147483647.")
    started = time.perf_counter()
    replay_id = uuid4().hex
    replay_path = REPLAY_DIR / f"{replay_id}.json"
    try:
        with tempfile.TemporaryDirectory(prefix="neural-coliseum-sandbox-") as temp_dir:
            agent_path = Path(temp_dir) / "agent.py"
            agent_path.write_text(source, encoding="utf-8")
            payload = (_run_local if trusted_local else _run_docker)(agent_path, BENCHMARKS[opponent], seed, replay_path)
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"Sandbox match exceeded {MATCH_TIMEOUT_SECONDS} seconds.") from exc
    except FileNotFoundError as exc:
        runner = "local Python" if trusted_local else "Docker"
        raise SandboxError(
            f"Match runner unavailable: {runner} could not be started."
        ) from exc
    except OSError as exc:
        raise SandboxError(f"Match runner could not start: {exc}") from exc
    runtime = time.perf_counter() - started
    p1 = float(payload["p1Score"])
    p2 = float(payload["p2Score"])
    winner = "bot" if p1 > p2 else "opponent" if p2 > p1 else "tie"
    analytics = analyze_replay(replay_path)
    failure = payload.get("failure")
    contestant_error = failure.get("error") if failure and failure.get("player") == 0 else None
    return {
        "status": "contestant_error" if contestant_error else "success", "winner": winner, "botFinalMoney": p1,
        "opponentFinalMoney": p2, "runtimeSeconds": runtime, "seed": seed,
        "opponent": opponent, "error": contestant_error, "replayId": replay_id,
        "analytics": analytics, "contestantFailure": failure,
    }
