"""Replay-backed analytics using only fields recorded by the game engine."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}


def load_replay(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _farm_counts(farm: dict) -> tuple[int, int, float]:
    animals = occupied = unlocked = 0
    for row in farm.get("tiles", []):
        for tile in row:
            if tile == "LOCKED":
                continue
            unlocked += 1
            if tile is not None:
                occupied += 1
            if isinstance(tile, dict) and tile.get("kind") in {"COOP", "PASTURE"} and tile.get("animal"):
                animals += 1
    utilization = occupied / unlocked if unlocked else 0.0
    return animals, unlocked, utilization


def analyze_replay(path: Path, player: int = 0) -> dict:
    replay = load_replay(path)
    steps = replay.get("steps", [])
    if not steps:
        raise ValueError("Replay contains no steps.")

    action_counts = Counter()
    products_sold = Counter()
    peak_cash = 0.0
    minimum_cash = float("inf")
    series = []

    for index, pair in enumerate(steps):
        state = pair[player]
        obs = state.get("observation", {})
        farm = obs.get("farms", [{}, {}])[player]
        money = float(farm.get("money", 0))
        peak_cash = max(peak_cash, money)
        minimum_cash = min(minimum_cash, money)
        action = state.get("action") or {}
        unit_actions = [action.get("farmer", ["PASS"])] + list(action.get("hands", []))
        for unit_action in unit_actions:
            if unit_action:
                action_counts[str(unit_action[0]).upper()] += 1
        for market_action in action.get("market", []):
            if not market_action:
                continue
            op = str(market_action[0]).upper()
            action_counts[op] += 1
            if op == "SELL" and len(market_action) >= 3:
                products_sold[str(market_action[1])] += int(market_action[2])

        if index % 12 == 0 or index == len(steps) - 1:
            animals, _, utilization = _farm_counts(farm)
            series.append({
                "step": index,
                "money": money,
                "workers": 1 + len(farm.get("hands", [])),
                "animals": animals,
                "utilization": round(utilization * 100, 2),
                "prices": obs.get("market", {}).get("prices", {}),
            })

    final_state = steps[-1][player]
    final_obs = final_state.get("observation", {})
    final_farm = final_obs.get("farms", [{}, {}])[player]
    final_animals, _, final_utilization = _farm_counts(final_farm)
    total_unit_actions = sum(action_counts[action] for action in action_counts if action not in {"SELL", "HIRE", "BUY_LAND", "BUY_SEED", "BUY_ANIMAL", "BUY_PRODUCT"})
    movement_actions = sum(action_counts[move] for move in MOVES)
    idle_actions = action_counts["PASS"]
    final_private = final_obs.get("private", {})
    final_shed = final_private.get("shed", {})
    final_prices = final_obs.get("market", {}).get("prices", {})
    unsold_units = sum(int(value or 0) for value in final_shed.values())
    unsold_value = sum(int(amount or 0) * float(final_prices.get(item, 0) or 0) for item, amount in final_shed.items())
    diagnostics = []
    movement_rate = movement_actions / total_unit_actions * 100 if total_unit_actions else 0
    idle_rate = idle_actions / total_unit_actions * 100 if total_unit_actions else 0
    if movement_rate > 45:
        diagnostics.append({"level": "warning", "title": "High travel load", "detail": f"{movement_rate:.0f}% of unit actions were movement. Task selection may benefit from travel cost.", "mission": "workforce", "prompt": "My workers spend too many turns walking. Improve only job scoring so distance reduces task attractiveness while urgent, valuable work can still justify travel."})
    if idle_rate > 25:
        diagnostics.append({"level": "warning", "title": "Idle capacity detected", "detail": f"{idle_rate:.0f}% of unit actions were PASS. Look for useful work before ending a turn.", "mission": "core", "prompt": "My bot passes too often. Add a safe fallback priority list for useful farm work without rewriting the whole strategy."})
    if action_counts["PLANT"] and action_counts["HARVEST"] < action_counts["PLANT"] * 0.6:
        diagnostics.append({"level": "warning", "title": "Low harvest conversion", "detail": f"The bot planted {action_counts['PLANT']} times but harvested only {action_counts['HARVEST']} times.", "mission": "crop_economics", "prompt": "My bot plants more often than it harvests. Help me inspect crop timing, watering and harvest priority, changing only the crop job logic."})
    if unsold_units:
        diagnostics.append({"level": "warning", "title": "Inventory left at finish", "detail": f"{unsold_units} stored units remained, worth about {unsold_value:,.0f} at final prices.", "mission": "trading", "prompt": "My bot ends matches with unsold inventory. Add a gradual endgame liquidation mode that prioritizes returning and selling goods before the final turn."})
    return {
        "steps": len(steps),
        "finalCash": float(final_farm.get("money", final_state.get("reward", 0) or 0)),
        "peakCash": peak_cash,
        "minimumCash": 0 if minimum_cash == float("inf") else minimum_cash,
        "landQuadrantsUnlocked": len(final_farm.get("unlocked_quadrants", [])),
        "plantsPlanted": action_counts["PLANT"],
        "plantsHarvested": action_counts["HARVEST"],
        "workersHired": action_counts["HIRE"],
        "animalsOwned": final_animals,
        "productsSold": dict(products_sold),
        "idleActions": action_counts["PASS"],
        "movementActions": movement_actions,
        "movementRate": round(movement_rate, 2),
        "idleRate": round(idle_rate, 2),
        "usefulActions": max(0, total_unit_actions - movement_actions - idle_actions),
        "finalUnsoldUnits": unsold_units,
        "finalUnsoldValue": round(unsold_value, 2),
        "farmUtilization": round(final_utilization * 100, 2),
        "diagnostics": diagnostics,
        "series": series,
    }


def replay_frame(path: Path, step: int, player: int = 0) -> dict:
    replay = load_replay(path)
    steps = replay.get("steps", [])
    if not steps:
        raise ValueError("Replay contains no steps.")
    step = max(0, min(step, len(steps) - 1))
    state = steps[step][player]
    obs = state.get("observation", {})
    farm = obs.get("farms", [{}, {}])[player]
    return {
        "step": step,
        "totalSteps": len(steps),
        "day": obs.get("day", step // 24),
        "hour": obs.get("hour", step % 24),
        "action": state.get("action"),
        "reward": state.get("reward"),
        "farm": {
            "money": farm.get("money"),
            "tiles": farm.get("tiles", []),
            "farmer": farm.get("farmer"),
            "hands": farm.get("hands", []),
            "unlockedQuadrants": farm.get("unlocked_quadrants", []),
        },
        "marketPrices": obs.get("market", {}).get("prices", {}),
    }
