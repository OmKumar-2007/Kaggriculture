"""Configurable official score aggregation."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "evaluation.json"


def load_scoring_config(path: Path = CONFIG_PATH) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    weights = config["weights"]
    if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-9:
        raise ValueError("Official scoring weights must sum to 1.")
    return config


def aggregate_games(games: list[dict], config: dict | None = None) -> dict:
    if not games:
        raise ValueError("At least one completed game is required.")
    config = config or load_scoring_config()
    wins = sum(1 for game in games if game["contestantMoney"] > game["opponentMoney"])
    ties = sum(1 for game in games if game["contestantMoney"] == game["opponentMoney"])
    win_rate = (wins + 0.5 * ties) / len(games)
    average_money = sum(game["contestantMoney"] for game in games) / len(games)
    average_diff = sum(game["contestantMoney"] - game["opponentMoney"] for game in games) / len(games)
    scale = max(1.0, float(config["economic_scale"]))
    economic = max(0.0, min(1.0, 0.5 + average_diff / (2 * scale)))
    weights = config["weights"]
    rating = float(config["rating_scale"]) * (
        float(weights["win_rate"]) * win_rate + float(weights["economic"]) * economic
    )
    return {
        "rating": round(rating, 2),
        "winRate": round(win_rate * 100, 2),
        "averageFinalMoney": round(average_money, 2),
        "averageMoneyDifferential": round(average_diff, 2),
        "wins": wins,
        "ties": ties,
        "games": len(games),
    }
