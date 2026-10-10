"""Deterministic seeded single-elimination bracket mathematics."""
from __future__ import annotations


def bracket_capacity(qualifiers: int) -> int:
    if qualifiers < 2:
        raise ValueError("At least two qualifiers are required.")
    return 1 << (qualifiers - 1).bit_length()


def seed_positions(capacity: int) -> list[int]:
    if capacity < 2 or capacity & (capacity - 1):
        raise ValueError("Bracket capacity must be a power of two of at least 2.")
    positions = [1, 2]
    while len(positions) < capacity:
        size = len(positions) * 2
        positions = [seed for old in positions for seed in (old, size + 1 - old)]
    return positions


def opening_bracket(roster: list[dict]) -> dict:
    """Roster is ordered by frozen qualification rank, highest first."""
    count = len(roster)
    capacity = bracket_capacity(count)
    names = [str(row.get("team",row.get("username"))).casefold() for row in roster]
    if len(set(names)) != count:
        raise ValueError("The qualifier roster contains duplicate teams.")
    by_seed = {index: {**row, "seed": index} for index, row in enumerate(roster, 1)}
    slots = seed_positions(capacity)
    matches = []
    for index in range(0, capacity, 2):
        left = by_seed.get(slots[index])
        right = by_seed.get(slots[index + 1])
        if not left:
            raise ValueError("The seeded bracket has an empty upper slot.")
        matches.append({"id": f"R1_M{index // 2 + 1}", "round": 1,
                        "position": index // 2 + 1, "teamA": left, "teamB": right,
                        "status": "bye" if right is None else "pending",
                        "winner": left if right is None else None})
    return {"qualifiers": count, "capacity": capacity, "byes": capacity - count,
            "rounds": capacity.bit_length() - 1, "requiredPairings": count - 1,
            "matches": matches}


def aggregate_swapped_legs(first: dict, second: dict) -> tuple[float, float]:
    """First leg A/B, second leg B/A. Never conflate player zero with A."""
    if first.get("failure") or second.get("failure"):
        raise ValueError("A failed game cannot decide a knockout pairing.")
    return (float(first["p1Score"]) + float(second["p2Score"]),
            float(first["p2Score"]) + float(second["p1Score"]))
