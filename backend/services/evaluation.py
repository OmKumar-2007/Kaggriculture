"""Official hidden evaluation with multiple seeds and both player positions."""

from __future__ import annotations

import tempfile
import hashlib
from pathlib import Path

from backend.services.sandbox import _run_docker, _run_local
from backend.services.scoring import aggregate_games, load_scoring_config


ROOT = Path(__file__).resolve().parents[2]
PRIVATE_OPPONENTS = {
    "baseline_alpha": ROOT / "backend" / "private_benchmarks" / "baseline_alpha.py",
    "baseline_beta": ROOT / "backend" / "private_benchmarks" / "baseline_beta.py",
}


class EvaluationError(RuntimeError):
    pass

class ContestantEvaluationError(EvaluationError):
    pass


def evaluation_plan(config: dict | None = None) -> list[dict]:
    config = config or load_scoring_config()
    return [
        {"opponent": opponent, "seed": int(seed), "side": int(side)}
        for opponent in config["opponents"]
        for seed in config["seeds"]
        for side in config.get("sides", [0, 1])
    ]


def evaluate_source(source: str, *, trusted_local: bool = False, runner=None, config: dict | None = None,
                    reference_sources: dict | None = None, progress=None, on_stage=None) -> dict:
    config = config or load_scoring_config()
    runner = runner or (_run_local if trusted_local else _run_docker)
    games = []
    try:
        with tempfile.TemporaryDirectory(prefix="neural-coliseum-official-") as temp_dir:
            agent_path = Path(temp_dir) / "agent.py"
            agent_path.write_text(source, encoding="utf-8")
            replay_path = Path(temp_dir) / "official-replay.json"
            opponent_paths = dict(PRIVATE_OPPONENTS)
            if reference_sources is not None:
                opponent_paths = {}
                for name, item in reference_sources.items():
                    content = item["source"].encode("utf-8")
                    if hashlib.sha256(content).hexdigest() != item["sha256"]:
                        raise EvaluationError("Frozen reference source hash mismatch.")
                    path = Path(temp_dir) / f"reference-{len(opponent_paths)}.py"
                    path.write_bytes(content)
                    opponent_paths[name] = path
            plan = evaluation_plan(config)
            for index, item in enumerate(plan, 1):
                opponent_path = opponent_paths.get(item["opponent"])
                if not opponent_path or not opponent_path.is_file():
                    raise EvaluationError("Official evaluation configuration references an unavailable baseline.")
                first, second = (agent_path, opponent_path) if item["side"] == 0 else (opponent_path, agent_path)
                detail = f"game {index}/{len(plan)} · {item['opponent']} · seed {item['seed']} · side {item['side']}"
                if on_stage: on_stage("match", "running", detail)
                payload = runner(first, second, item["seed"], replay_path)
                failure = payload.get("failure")
                if failure:
                    detail = str(failure.get("error") or "Agent failed during the match.")[:500]
                    if failure.get("player") == item["side"]:
                        raise ContestantEvaluationError(detail)
                    raise EvaluationError(f"Reference opponent failed: {detail}")
                p1, p2 = float(payload["p1Score"]), float(payload["p2Score"])
                contestant, opponent = (p1, p2) if item["side"] == 0 else (p2, p1)
                games.append({
                    "seed": item["seed"], "side": item["side"],
                    "contestantMoney": contestant, "opponentMoney": opponent,
                })
                if on_stage: on_stage("match", "completed", detail)
                if progress:
                    progress(index, len(plan))
    except EvaluationError:
        raise
    except Exception as exc:
        raise EvaluationError(f"Official evaluation could not complete: {exc}") from exc
    summary = aggregate_games(games, config)
    if on_stage: on_stage("scoring", "completed", f"Aggregated {len(games)} side-swapped games")
    return {**summary, "status": "complete"}
