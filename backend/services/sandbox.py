"""Sandbox match execution against modest public benchmark agents."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from contextvars import ContextVar
from typing import Callable
from pathlib import Path
from uuid import uuid4

from py_env import get_kaggle_python
from backend.services.analytics import analyze_replay


ROOT = Path(__file__).resolve().parents[2]
RUN_MATCH = ROOT / "run_match.py"
DOCKER_IMAGE = os.getenv("EVALUATOR_IMAGE", "nitw-farm-ai-evaluator")
MATCH_TIMEOUT_SECONDS = int(os.getenv("EVALUATION_TIMEOUT_SECONDS", os.getenv("MATCH_TIMEOUT_SECONDS", "120")))
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

class EvaluationCancelled(SandboxError):
    pass

ACTIVE_JOB_ID: ContextVar[str | None] = ContextVar("active_evaluation_job", default=None)
REMOTE_CANCEL_CHECK: ContextVar[Callable[[], bool] | None] = ContextVar("remote_cancel_check", default=None)


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
    memory_mb = max(128, min(int(os.getenv("EVALUATION_MEMORY_MB", "512")), 4096))
    cpu_limit = max(0.25, min(float(os.getenv("EVALUATION_CPU_LIMIT", "1")), 8.0))
    pids_limit = max(32, min(int(os.getenv("EVALUATION_PIDS_LIMIT", "128")), 512))
    container = f"farmcraft-eval-{uuid4().hex}"
    job_id = ACTIVE_JOB_ID.get()
    remote_cancel = REMOTE_CANCEL_CHECK.get()
    connection = None
    container_status = "failed"
    if job_id:
        from backend.services.queueing import redis_connection
        connection = redis_connection()
        if connection.exists(f"arena:job:cancel:{job_id}"):
            raise EvaluationCancelled("Evaluation cancelled by an organizer.")
    if remote_cancel and remote_cancel():
        raise EvaluationCancelled("Evaluation cancelled by an organizer.")
    with tempfile.TemporaryDirectory(prefix="farmcraft-eval-output-") as output_root:
        output_dir = Path(output_root)
        if os.name != "nt":
            output_dir.chmod(0o777)
        command = [
            "docker", "run", "--rm", "--name", container, "--network", "none",
            "--cpus", str(cpu_limit), "--memory", f"{memory_mb}m", "--memory-swap", f"{memory_mb}m",
            "--pids-limit", str(pids_limit), "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m,mode=1777",
            "--ulimit", "nofile=256:256",
            "-v", f"{agent_path.resolve()}:/competition/agent.py:ro",
            "-v", f"{opponent_path.resolve()}:/competition/opponent.py:ro",
            "-v", f"{output_dir.resolve()}:/output:rw",
            "--entrypoint", "python", DOCKER_IMAGE, "/app/sandbox_worker.py",
            "--agent1", "/competition/agent.py", "--agent2", "/competition/opponent.py",
            "--seed", str(seed), "--steps", "720", "--replay-output", "/output/replay.json",
        ]
        try:
            if connection and job_id:
                connection.setex(f"arena:job:container:{job_id}", MATCH_TIMEOUT_SECONDS + 60, container)
                from backend.services.storage import store
                store.pipeline_event(job_id, "container", "running", container)
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + MATCH_TIMEOUT_SECONDS
            while process.poll() is None:
                if (connection and job_id and connection.exists(f"arena:job:cancel:{job_id}")) or (remote_cancel and remote_cancel()):
                    container_status = "cancelled"
                    try:
                        subprocess.run(["docker", "stop", "-t", str(max(1, min(int(os.getenv("EVALUATION_CANCEL_GRACE_SECONDS", "3")), 15))), container],
                                       capture_output=True, timeout=20, check=False)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    process.kill()
                    process.communicate(timeout=5)
                    raise EvaluationCancelled("Evaluation cancelled by an organizer.")
                if time.monotonic() >= deadline:
                    container_status = "timeout"
                    process.kill()
                    process.communicate(timeout=5)
                    raise subprocess.TimeoutExpired(command, MATCH_TIMEOUT_SECONDS)
                time.sleep(0.25)
            stdout, stderr = process.communicate(timeout=5)
            payload = _parse_result(subprocess.CompletedProcess(command, process.returncode, stdout, stderr))
            container_status = "completed"
            generated = output_dir / "replay.json"
            if generated.is_file():
                replay_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(generated, replay_path)
            return payload
        finally:
            if connection and job_id:
                connection.delete(f"arena:job:container:{job_id}")
                try:
                    from backend.services.storage import store
                    store.pipeline_event(job_id,"container",container_status,container)
                except Exception:
                    pass
            # Killing the Docker CLI on timeout does not reliably stop its container.
            try:
                subprocess.run(["docker", "rm", "-f", container], capture_output=True,
                               text=True, timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass


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
