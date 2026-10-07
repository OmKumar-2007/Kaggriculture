import sys
import json
import argparse
import os
import contextlib
import importlib.util
import uuid
from pathlib import Path


# ============================================================
# PROJECT PATHS
# ============================================================

ROOT = Path(__file__).resolve().parent

PROJECT_DIR = ROOT / "NITW_Farm_AI_Challenge_v1"

# Required because config.py is imported as:
#
#     from config import ...
#
sys.path.insert(0, str(PROJECT_DIR))


# ============================================================
# SAFE PATH RESOLUTION
# ============================================================

def resolve_agent_path(path_string):
    """
    Accept:
        - absolute Windows path
        - relative path from current terminal
        - relative path from project root

    Always return an absolute Path.
    """

    raw = Path(path_string).expanduser()

    # Absolute path
    if raw.is_absolute():
        path = raw.resolve()

    else:
        # First try relative to current working directory
        cwd_path = (Path.cwd() / raw).resolve()

        if cwd_path.exists():
            path = cwd_path
        else:
            # Then try relative to project root
            root_path = (ROOT / raw).resolve()
            path = root_path

    if not path.exists():
        raise FileNotFoundError(
            f"Agent file not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Agent path is not a file: {path}"
        )

    if path.suffix.lower() != ".py":
        raise ValueError(
            f"Agent must be a .py file: {path}"
        )

    return path


def load_agent_function(path):
    """Load the canonical agent callable while keeping each module isolated."""
    module_name = f"harvest_protocol_agent_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load agent module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, "agent", None)
    if not callable(function):
        raise RuntimeError("Submission does not expose callable agent(obs).")
    return function


# ============================================================
# SUPPRESS NATIVE STDOUT / STDERR
# ============================================================

@contextlib.contextmanager
def suppress_native_output():
    """
    Suppress both Python-level and OS-level stdout/stderr.

    This prevents kaggle_environments, OpenSpiel,
    agent execution, etc. from contaminating stdout.

    run_match.py must print ONLY JSON to stdout.
    """

    # Flush existing output first
    sys.stdout.flush()
    sys.stderr.flush()

    old_stdout_fd = os.dup(1)
    old_stderr_fd = os.dup(2)

    null_fd = os.open(os.devnull, os.O_WRONLY)

    try:

        # Redirect OS-level stdout/stderr
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)

        # Also redirect Python-level streams
        with open(os.devnull, "w") as devnull:

            with contextlib.redirect_stdout(devnull):
                with contextlib.redirect_stderr(devnull):

                    yield

    finally:

        sys.stdout.flush()
        sys.stderr.flush()

        # Restore stdout/stderr
        os.dup2(old_stdout_fd, 1)
        os.dup2(old_stderr_fd, 2)

        os.close(old_stdout_fd)
        os.close(old_stderr_fd)
        os.close(null_fd)


# ============================================================
# RUN ONE MATCH
# ============================================================

def execute_match(agent1_path, agent2_path, seed, replay_output=None):
    """
    Execute one complete Harvest Protocol 1v1 match.

    Returns:

        {
            "p1Score": float,
            "p2Score": float,
            "winner": 0 or 1
        }
    """

    # Resolve agent paths before entering the
    # output-suppression block so path errors are preserved.
    agent1 = resolve_agent_path(agent1_path)
    agent2 = resolve_agent_path(agent2_path)

    # Everything inside this block is silent.
    with suppress_native_output():

        # Import inside the protected block.
        from kaggle_environments import make

        # ----------------------------------------------------
        # Create the Harvest Protocol environment using its upstream engine ID.
        # ----------------------------------------------------

        env = make(
            "kaggriculture",
            configuration={
                "episodeSteps": 720,
                "seed": seed,
            },
            debug=False,
        )

        failures = [None, None]

        def prepare(index, path):
            try:
                function = load_agent_function(path)
            except Exception as exc:
                failures[index] = f"{type(exc).__name__}: {exc}"
                function = lambda obs: {}

            def guarded(obs):
                try:
                    return function(obs)
                except Exception as exc:
                    if failures[index] is None:
                        failures[index] = f"{type(exc).__name__}: {exc}"
                    return {}
            return guarded

        # Wrappers expose contestant failures that kaggle_environments otherwise
        # converts into silent no-op turns.
        env.run([prepare(0, agent1), prepare(1, agent2)])

        if replay_output:
            replay_path = Path(replay_output).resolve()
            replay_path.parent.mkdir(parents=True, exist_ok=True)
            replay_path.write_text(json.dumps(env.toJSON()), encoding="utf-8")

        # ----------------------------------------------------
        # Verify steps
        # ----------------------------------------------------

        if not env.steps:
            raise RuntimeError(
                "Harvest Protocol produced no steps."
            )

        final_step = env.steps[-1]

        if not final_step or len(final_step) < 2:
            raise RuntimeError(
                "Final timestep does not contain two players."
            )

        # ----------------------------------------------------
        # Extract final states
        # ----------------------------------------------------

        p1_state = final_step[0]
        p2_state = final_step[1]
        p1_status = str(getattr(p1_state, "status", "UNKNOWN"))
        p2_status = str(getattr(p2_state, "status", "UNKNOWN"))

        # ----------------------------------------------------
        # Extract final rewards
        # ----------------------------------------------------

        p1_reward = getattr(
            p1_state,
            "reward",
            None
        )

        p2_reward = getattr(
            p2_state,
            "reward",
            None
        )

        p1_failed = failures[0] is not None or p1_status == "ERROR"
        p2_failed = failures[1] is not None or p2_status == "ERROR"

        if p1_failed and not p2_failed:
            return {"p1Score": 0.0, "p2Score": float(p2_reward or 0), "winner": 1,
                    "tie": False, "p1Status": p1_status, "p2Status": p2_status,
                    "failure": {"type": "contestant", "player": 0, "error": failures[0] or p1_status}}

        if p2_failed and not p1_failed:
            return {"p1Score": float(p1_reward or 0), "p2Score": 0.0, "winner": 0,
                    "tie": False, "p1Status": p1_status, "p2Status": p2_status,
                    "failure": {"type": "contestant", "player": 1, "error": failures[1] or p2_status}}

        if p1_failed and p2_failed:
            raise RuntimeError("Both contestants failed; the match requires organizer review.")

        if p1_reward is None:
            raise RuntimeError(
                "Player 1 has no final reward."
            )

        if p2_reward is None:
            raise RuntimeError(
                "Player 2 has no final reward."
            )

        p1_score = float(p1_reward)
        p2_score = float(p2_reward)

        # ----------------------------------------------------
        # Determine winner
        #
        # 0 = Player 1
        # 1 = Player 2
        #
        # Current tie policy:
        # Player 1 wins a tie.
        #
        # This can later be replaced with a proper
        # tournament tie-breaker.
        # ----------------------------------------------------

        if p1_score > p2_score:
            winner = 0
            tie = False

        elif p2_score > p1_score:
            winner = 1
            tie = False

        else:
            # Exact tie
            winner = None
            tie = True

        return {
            "p1Score": p1_score,
            "p2Score": p2_score,
            "winner": winner,
            "tie": tie,
            "p1Status": p1_status,
            "p2Status": p2_status,
        }

# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Run one Harvest Protocol 1v1 match."
    )

    parser.add_argument(
        "--agent1",
        required=True,
        help="Path to Player 1 agent"
    )

    parser.add_argument(
        "--agent2",
        required=True,
        help="Path to Player 2 agent"
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=20260929,
        help="Harvest Protocol random seed"
    )

    parser.add_argument(
        "--replay-output",
        help="Optional JSON path for development replay capture"
    )

    args = parser.parse_args()

    try:

        result = execute_match(
            args.agent1,
            args.agent2,
            args.seed,
            args.replay_output,
        )

        # ====================================================
        # CRITICAL:
        # stdout contains ONLY this JSON.
        # ====================================================

        print(
            json.dumps(
                result,
                separators=(",", ":")
            )
        )

        sys.exit(0)

    except Exception as e:

        # ====================================================
        # Errors are also machine-readable JSON.
        # ====================================================

        error_result = {
            "error": str(e)
        }

        print(
            json.dumps(
                error_result,
                separators=(",", ":")
            )
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
