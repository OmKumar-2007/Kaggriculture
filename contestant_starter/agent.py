"""Neural Coliseum beginner starter bot.

The helpers in the first section are provided infrastructure. Contestants are
expected to experiment mainly inside the CONTESTANT STRATEGY section. Defaults
are intentionally reasonable rather than tuned.
"""

from math import inf


# =============================================================================
# PROVIDED INFRASTRUCTURE — understand it, but you do not need to rewrite it.
# =============================================================================

CROPS = {
    "WHEAT": {"seed_cost": 10, "first_yield_day": 2},
    "CARROT": {"seed_cost": 20, "first_yield_day": 2},
    "TOMATO": {"seed_cost": 50, "first_yield_day": 8},
    "STRAWBERRY": {"seed_cost": 100, "first_yield_day": 10},
    "MELON": {"seed_cost": 80, "first_yield_day": 10},
}

BASE_PRICES = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
    "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200,
    "FERTILIZER": 100,
}

SHED_ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))
MOVES = {(-1, 0): "WEST", (1, 0): "EAST", (0, -1): "NORTH", (0, 1): "SOUTH"}


def distance(a, b):
    """Manhattan distance between two board positions."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def nearest(origin, positions):
    return min(positions, key=lambda pos: distance(origin, pos)) if positions else None


def step_toward(origin, target):
    """Return one safe cardinal movement toward a target."""
    ox, oy = origin
    tx, ty = target
    if ox != tx:
        return [MOVES[(1 if tx > ox else -1, 0)]]
    if oy != ty:
        return [MOVES[(0, 1 if ty > oy else -1)]]
    return ["PASS"]


def scan_farm(tiles):
    """Group visible farm tiles into useful categories."""
    scan = {"empty": [], "plants": [], "animals": [], "weeds": [], "locked": []}
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            position = (x, y)
            if tile is None:
                scan["empty"].append(position)
            elif tile == "LOCKED":
                scan["locked"].append(position)
            elif isinstance(tile, dict):
                kind = tile.get("kind")
                if kind == "PLANT":
                    scan["plants"].append((position, tile))
                elif kind in ("COOP", "PASTURE"):
                    scan["animals"].append((position, tile))
                elif kind == "WEED":
                    scan["weeds"].append(position)
    return scan


def build_state(obs):
    """Create a compact, friendly view of the raw observation."""
    player = obs["player"]
    farm = obs["farms"][player]
    opponent = obs["farms"][1 - player]
    private = obs["private"]
    units = [tuple(farm["farmer"])] + [tuple(pos) for pos in farm.get("hands", [])]
    inventories = private.get("inventories", [{} for _ in units])
    return {
        "obs": obs,
        "player": player,
        "day": obs["day"],
        "hour": obs["hour"],
        "farm": farm,
        "opponent": opponent,
        "money": farm["money"],
        "shed": private.get("shed", {}),
        "seeds": private.get("seeds", {}),
        "units": units,
        "inventories": inventories,
        "scan": scan_farm(farm["tiles"]),
        "prices": obs["market"]["prices"],
        "market_inventory": obs["market"]["inventory"],
        "shops": obs.get("town", {}).get("unlocked_shops", []),
    }


def make_job(kind, target, action, priority, details=None):
    return {"kind": kind, "target": target, "action": action, "priority": priority, "details": details or {}}


def discover_jobs(state, crop_choice):
    """Discover basic farm work without deciding the final priority order."""
    jobs = []
    for position, tile in state["scan"]["plants"]:
        if tile.get("yield_units", 0) > 0:
            jobs.append(make_job("harvest", position, ["HARVEST"], 65, {"crop": tile.get("crop")}))
        if not tile.get("watered_today", False):
            jobs.append(make_job("water", position, ["WATER"], 75, {"crop": tile.get("crop")}))
    for position in state["scan"]["weeds"]:
        jobs.append(make_job("clear", position, ["DIG"], 35))
    if state["seeds"].get(crop_choice, 0) > 0:
        for position in state["scan"]["empty"]:
            jobs.append(make_job("plant", position, ["PLANT", crop_choice], 40, {"crop": crop_choice}))
    return jobs


def inventory_size(inventory):
    return sum(value for value in inventory.values() if isinstance(value, (int, float)))


def assign_workers(jobs, state):
    """Greedily assign distinct jobs using the contestant's job_score hook."""
    actions = []
    remaining = list(jobs)
    for index, position in enumerate(state["units"]):
        inventory = state["inventories"][index] if index < len(state["inventories"]) else {}
        if inventory_size(inventory) > 0:
            target = nearest(position, SHED_ACCESS)
            actions.append(["DROP"] if position == target else step_toward(position, target))
            continue
        if not remaining:
            actions.append(["PASS"])
            continue
        best = max(remaining, key=lambda job: job_score(job, position, state))
        remaining.remove(best)
        actions.append(best["action"] if position == best["target"] else step_toward(position, best["target"]))
    return actions


def safe_market_actions(actions):
    """Keep only well-formed market orders and respect the per-turn cap."""
    return [action for action in actions if isinstance(action, list) and action][:10]


# =============================================================================
# CONTESTANT STRATEGY — ask an LLM to help you improve these choices.
# =============================================================================

PARAMS = {
    "distance_penalty": 2.0,
    "cash_reserve": 400,
    "sell_threshold": 0.80,
    "seed_batch": 2,
    "desired_workers": 2,
    "worker_budget": 40,
    "land_aggression": 0.25,
    "animal_aggression": 0.20,
}


def crop_score(crop, state):
    """Higher means the crop looks more attractive. Deliberately simple."""
    data = CROPS[crop]
    sale_price = state["prices"].get(crop, BASE_PRICES[crop])
    days = max(1, data["first_yield_day"])
    return (sale_price - data["seed_cost"]) / days


def job_score(job, worker, state):
    """Higher means a worker should prefer this job."""
    travel = distance(worker, job["target"])
    return job["priority"] - PARAMS["distance_penalty"] * travel


def desired_workers(state):
    """Return total desired units, including the main farmer."""
    return PARAMS["desired_workers"]


def market_strategy(state, crop_choice):
    actions = []
    for product, quantity in state["shed"].items():
        if quantity <= 0 or product not in BASE_PRICES:
            continue
        price = state["prices"].get(product, 0)
        if price >= BASE_PRICES[product] * PARAMS["sell_threshold"]:
            actions.append(["SELL", product, quantity])
    seed_cost = CROPS[crop_choice]["seed_cost"]
    if state["seeds"].get(crop_choice, 0) == 0 and state["money"] - PARAMS["cash_reserve"] >= seed_cost * PARAMS["seed_batch"]:
        actions.append(["BUY_SEED", crop_choice, PARAMS["seed_batch"]])
    if len(state["units"]) < desired_workers(state) and state["money"] > PARAMS["cash_reserve"] + PARAMS["worker_budget"]:
        actions.append(["HIRE"])
    return actions


def animal_strategy(state):
    """Optional hook: return animal-related market orders."""
    return []


def land_strategy(state):
    """Optional hook: return ["BUY_LAND"] when expansion is worthwhile."""
    return None


def choose_crop(state):
    return max(CROPS, key=lambda crop: crop_score(crop, state))


def agent(obs):
    state = build_state(obs)
    crop_choice = choose_crop(state)
    jobs = discover_jobs(state, crop_choice)
    unit_actions = assign_workers(jobs, state)
    while len(unit_actions) < len(state["units"]):
        unit_actions.append(["PASS"])

    market = market_strategy(state, crop_choice) + animal_strategy(state)
    land_order = land_strategy(state)
    if land_order:
        market.append(land_order)

    return {
        "farmer": unit_actions[0] if unit_actions else ["PASS"],
        "hands": unit_actions[1:],
        "market": safe_market_actions(market),
    }
