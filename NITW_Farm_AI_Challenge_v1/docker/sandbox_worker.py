"""Run two mounted agents in the isolated evaluator image."""

import argparse
import json
import sys
import importlib.util
import uuid
from pathlib import Path


def load_agent(path):
    spec = importlib.util.spec_from_file_location(f"agent_{uuid.uuid4().hex}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load agent: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, "agent", None)
    if not callable(function):
        raise RuntimeError("Submission does not expose callable agent(obs).")
    return function


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent1", required=True)
    parser.add_argument("--agent2", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--steps", type=int, default=720)
    parser.add_argument("--replay-output")
    args = parser.parse_args()
    try:
        from kaggle_environments import make
        env = make("kaggriculture", configuration={"episodeSteps": args.steps, "seed": args.seed}, debug=False)
        failures = [None, None]
        def prepare(index, path):
            try:
                function = load_agent(path)
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
        env.run([prepare(0, args.agent1), prepare(1, args.agent2)])
        if args.replay_output:
            Path(args.replay_output).write_text(json.dumps(env.toJSON()), encoding="utf-8")
        final = env.steps[-1]
        p1 = float(final[0].reward)
        p2 = float(final[1].reward)
        if failures[0] and failures[1]:
            raise RuntimeError("Both contestants failed; organizer review is required.")
        if failures[0]:
            p1, winner = 0.0, 1
        elif failures[1]:
            p2, winner = 0.0, 0
        else:
            winner = 0 if p1 > p2 else 1 if p2 > p1 else None
        failure = ({"type": "contestant", "player": 0, "error": failures[0]} if failures[0]
                   else {"type": "contestant", "player": 1, "error": failures[1]} if failures[1] else None)
        print(json.dumps({"status": "success", "p1Score": p1, "p2Score": p2, "winner": winner,
                          "tie": winner is None, "failure": failure}))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
