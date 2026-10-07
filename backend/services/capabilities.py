"""Explainable, conservative capability hints from source and match telemetry."""

from __future__ import annotations

import ast


CROPS = {"WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"}
ANIMAL_ACTIONS = {"BUY_ANIMAL", "BUILD_COOP", "BUILD_PASTURE", "FEED", "CARE"}


def detect_source_capabilities(source: str) -> list[dict]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    strings = {node.value.upper() for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    comparisons = sum(isinstance(node, ast.Compare) for node in ast.walk(tree))
    arithmetic = sum(isinstance(node, (ast.BinOp, ast.UnaryOp)) for node in ast.walk(tree))
    rules = [
        ("core", "Produces structured farm actions", {"FARMER", "HANDS", "MARKET"}.issubset(strings)),
        ("crop_mix", "Can choose between multiple crop types", len(strings & CROPS) >= 2),
        ("market", "Reads market information", "MARKET" in strings and ({"PRICES", "INVENTORY"} & strings)),
        ("season", "Changes decisions using match time", "DAY" in strings and comparisons >= 2),
        ("workers", "Can hire or coordinate workers", "HIRE" in strings or "HANDS" in strings),
        ("animals", "Supports livestock actions", bool(strings & ANIMAL_ACTIONS)),
        ("expansion", "Can invest in additional land", "BUY_LAND" in strings),
        ("distance", "Uses arithmetic for travel-aware decisions", "abs" in calls and arithmetic >= 3),
        ("opponent", "Reads both visible farms", "FARMS" in strings and "PLAYER" in strings and arithmetic >= 3),
    ]
    return [{"id": key, "label": label, "detected": bool(value)} for key, label, value in rules]
