from __future__ import annotations

import json
import subprocess
import tempfile
import time
import traceback
from pathlib import Path

from config import (
    EPISODE_STEPS,
    GAME_NAME,
    MAX_RUNTIME_SECONDS,
    OFFICIAL_SEED,
    OPPONENT,
)
from competition.result import EvaluationResult
from competition.validator import validate_agent_file, ValidationError


DOCKER_IMAGE = "nitw-farm-ai-evaluator"


def evaluate_submission(
    submission: Path,
    team: str,
    *,
    seed: int = OFFICIAL_SEED,
    use_docker: bool = True,
) -> EvaluationResult:
    """
    Evaluate a participant submission.

    Official competition mode:
        use_docker=True

    Local development mode:
        use_docker=False

    The participant submission must be a valid main.py.
    """

    start = time.perf_counter()

    # ---------------------------------------------------------
    # 1. Validate submission
    # ---------------------------------------------------------
    try:
        validate_agent_file(submission)

    except ValidationError as exc:
        return EvaluationResult(
            team=team,
            score=0,
            reward=0,
            status="invalid",
            runtime_seconds=time.perf_counter() - start,
            seed=seed,
            error=str(exc),
        )

    # ---------------------------------------------------------
    # 2. Run Kaggriculture
    # ---------------------------------------------------------
    try:
        if use_docker:
            payload = _run_docker(submission, seed)
        else:
            payload = _run_trusted_local(submission, seed)

    except subprocess.TimeoutExpired:
        return EvaluationResult(
            team=team,
            score=0,
            reward=0,
            status="timeout",
            runtime_seconds=time.perf_counter() - start,
            seed=seed,
            error=f"Evaluation exceeded {MAX_RUNTIME_SECONDS} seconds.",
        )

    except Exception:
        error = traceback.format_exc()

        print("\n========== EVALUATION EXCEPTION ==========")
        print(error)
        print("==========================================\n")

        return EvaluationResult(
            team=team,
            score=0,
            reward=0,
            status="failed",
            runtime_seconds=time.perf_counter() - start,
            seed=seed,
            error=error,
        )

    # ---------------------------------------------------------
    # 3. Extract reward
    # ---------------------------------------------------------
    runtime = time.perf_counter() - start

    try:
        reward = float(payload.get("reward", 0))
    except (TypeError, ValueError):
        reward = 0.0

    status = str(payload.get("status", "")).lower()

    # ---------------------------------------------------------
    # 4. Successful game
    #
    # Kaggriculture's final reward is what matters for the
    # competition. If a numeric reward exists and the game
    # completed, don't incorrectly reject it because of a
    # non-"success" status string.
    # ---------------------------------------------------------
    if reward is not None and status in {
        "done",
        "success",
        "finished",
        "terminated",
        "active",
        "",
    }:
        return EvaluationResult(
            team=team,
            score=reward,
            reward=reward,
            status="success",
            runtime_seconds=runtime,
            seed=seed,
        )

    # ---------------------------------------------------------
    # 5. Kaggriculture reported an actual failure
    # ---------------------------------------------------------
    return EvaluationResult(
        team=team,
        score=reward,
        reward=reward,
        status="failed",
        runtime_seconds=runtime,
        seed=seed,
        error=payload.get(
            "error",
            f"Kaggriculture evaluation returned status: {status}",
        ),
    )


# =============================================================
# DOCKER EVALUATION
# =============================================================

def _run_docker(submission: Path, seed: int) -> dict:
    """
    Run an untrusted participant submission inside Docker.
    """

    submission = submission.resolve()

    with tempfile.TemporaryDirectory(prefix="nitw-farm-") as temp:
        temp_dir = Path(temp)
        copied = temp_dir / "main.py"

        copied.write_bytes(submission.read_bytes())

        command = [
            "docker",
            "run",
            "--rm",

            # No internet access.
            "--network",
            "none",

            # Resource limits.
            "--cpus",
            "1",
            "--memory",
            "512m",
            "--pids-limit",
            "128",

            # Read-only filesystem.
            "--read-only",

            # Temporary writable directory.
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",

            # Participant code.
            "-v",
            f"{copied}:/competition/main.py:ro",

            DOCKER_IMAGE,
            "--submission",
            "/competition/main.py",

            "--seed",
            str(seed),

            "--steps",
            str(EPISODE_STEPS),

            "--opponent",
            OPPONENT,
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=MAX_RUNTIME_SECONDS,
            check=False,
        )

        # -----------------------------------------------------
        # Docker process itself failed
        # -----------------------------------------------------
        if completed.returncode != 0:
            return {
                "status": "failed",
                "reward": 0,
                "error": (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or f"Docker exited with code {completed.returncode}"
                ),
            }

        # -----------------------------------------------------
        # Worker returned JSON
        # -----------------------------------------------------
        output = completed.stdout.strip()

        if not output:
            return {
                "status": "failed",
                "reward": 0,
                "error": "Evaluator worker returned empty output.",
            }

        try:
            return json.loads(output)

        except json.JSONDecodeError as exc:
            return {
                "status": "failed",
                "reward": 0,
                "error": (
                    "Worker returned invalid JSON.\n\n"
                    f"JSON error: {exc}\n\n"
                    f"Worker stdout:\n{completed.stdout}\n\n"
                    f"Worker stderr:\n{completed.stderr}"
                ),
            }


# =============================================================
# TRUSTED LOCAL DEVELOPMENT EVALUATION
# =============================================================

def _run_trusted_local(submission: Path, seed: int) -> dict:
    """
    Run participant code directly on the host.

    DEVELOPMENT ONLY.

    Never use this mode for real participant submissions.
    """

    from kaggle_environments import make

    submission = submission.resolve()

    env = make(
        GAME_NAME,
        configuration={
            "episodeSteps": EPISODE_STEPS,
            "seed": seed,
        },
        debug=False,
    )

    # ---------------------------------------------------------
    # Run participant against fixed starter opponent.
    # ---------------------------------------------------------
    env.run(
        [
            str(submission),
            OPPONENT,
        ]
    )

    # ---------------------------------------------------------
    # Make sure the environment produced steps.
    # ---------------------------------------------------------
    if not env.steps:
        raise RuntimeError(
            "Kaggriculture produced no steps."
        )

    # ---------------------------------------------------------
    # Final timestep.
    # ---------------------------------------------------------
    final_step = env.steps[-1]

    if not final_step:
        raise RuntimeError(
            "Kaggriculture final timestep is empty."
        )

    # Participant is player 0.
    state = final_step[0]

    # ---------------------------------------------------------
    # Extract reward safely.
    # ---------------------------------------------------------
    reward = getattr(state, "reward", None)

    if reward is None:
        raise RuntimeError(
            "Kaggriculture finished without a final reward."
        )

    # ---------------------------------------------------------
    # Extract status safely.
    # ---------------------------------------------------------
    status = getattr(state, "status", None)

    if status is None:
        status = "done"

    return {
        "status": str(status).lower(),
        "reward": float(reward),
    }
