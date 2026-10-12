"""Generated FarmCraft load-test agent 03: yield_hunter.

Synthetic test fixture. This is not an optimized tournament solution.
"""
CFG = {'primary': 'MELON', 'secondary': 'STRAWBERRY', 'dynamic_crop': 2, 'cash_reserve': 75, 'seed_batch': 3, 'seed_min': 1, 'sell_threshold': 0.71, 'hire_workers': 1, 'hire_budget': 40, 'distance_penalty': 2.2, 'water_priority': 75, 'harvest_priority': 110, 'plant_priority': 42, 'weed_priority': 25, 'harvest_age_bias': 0, 'price_weight': 0.6}
SEED_COST = {"WHEAT": 10, "CARROT": 20, "MELON": 80, "TOMATO": 50, "STRAWBERRY": 100}
GROW = {"WHEAT": 2, "CARROT": 2, "MELON": 10, "TOMATO": 8, "STRAWBERRY": 10}
BASE = {"WHEAT": 25, "CARROT": 35, "MELON": 250, "TOMATO": 60, "STRAWBERRY": 120}

def distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def move(src, dest):
    if src[0] < dest[0]:
        return ["EAST"]
    if src[0] > dest[0]:
        return ["WEST"]
    if src[1] < dest[1]:
        return ["SOUTH"]
    if src[1] > dest[1]:
        return ["NORTH"]
    return ["PASS"]

def select_crop(day, money, seeds, prices):
    candidates = (CFG["primary"], CFG["secondary"], "WHEAT")
    # Varied crop preferences and economic behavior across the test fleet.
    if CFG["dynamic_crop"]:
        affordable = [c for c in candidates if money > SEED_COST[c] + CFG["cash_reserve"]
                      and day + GROW[c] < 30]
        if affordable:
            if CFG["dynamic_crop"] == 1:
                return max(affordable, key=lambda c: (prices.get(c, BASE[c]) - SEED_COST[c]) / max(1, GROW[c]))
            return max(affordable, key=lambda c: (prices.get(c, BASE[c]) - SEED_COST[c]) * CFG["price_weight"] / max(1, GROW[c] ** 0.5))
    for crop in candidates:
        if seeds.get(crop, 0) > 0 or money >= SEED_COST[crop] + CFG["cash_reserve"]:
            if day + GROW[crop] < 30:
                return crop
    return "WHEAT"

def agent(obs):
    player = obs["player"]
    farm = obs["farms"][player]
    private = obs["private"]
    money = farm.get("money", 0)
    day = obs.get("day", 0)
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})
    inventories = private.get("inventories", [])
    prices = obs.get("market", {}).get("prices", {})
    positions = [tuple(farm["farmer"])] + [tuple(p) for p in farm.get("hands", [])]
    crop = select_crop(day, money, seeds, prices)
    market = []
    # Sell accumulated produce when it reaches this bot's price preference.
    for product, count in shed.items():
        if count and product in BASE and prices.get(product, BASE[product]) >= BASE[product] * CFG["sell_threshold"]:
            market.append(["SELL", product, int(count)])
    if (day + GROW[crop] < 30 and seeds.get(crop, 0) < CFG["seed_min"]
            and money >= CFG["cash_reserve"] + SEED_COST[crop] * CFG["seed_batch"]):
        market.append(["BUY_SEED", crop, CFG["seed_batch"]])
    if CFG["hire_workers"] > len(positions) and money > CFG["cash_reserve"] + CFG["hire_budget"]:
        market.append(["HIRE"])

    jobs = []
    for y, row in enumerate(farm["tiles"]):
        for x, tile in enumerate(row):
            point = (x, y)
            if tile == "LOCKED":
                continue
            if tile is None:
                if seeds.get(crop, 0) > 0 and day + GROW[crop] < 30:
                    jobs.append((CFG["plant_priority"], point, ["PLANT", crop]))
            elif isinstance(tile, dict):
                kind = tile.get("kind")
                if kind == "PLANT":
                    plant_crop = tile.get("crop")
                    available = tile.get("yield_units", 0)
                    age = day - tile.get("planted_day", day)
                    if available > 0 and age >= CFG["harvest_age_bias"]:
                        jobs.append((CFG["harvest_priority"] + min(available, 6) * 2, point, ["HARVEST"]))
                    if not tile.get("watered_today", False):
                        jobs.append((CFG["water_priority"], point, ["WATER"]))
                elif kind == "WEED":
                    jobs.append((CFG["weed_priority"], point, ["DIG"]))

    actions = []
    available_jobs = list(jobs)
    for i, pos in enumerate(positions):
        inventory = inventories[i] if i < len(inventories) else {}
        if sum(v for v in inventory.values() if isinstance(v, (int, float))) > 0:
            shed_positions = ((4, 4), (5, 4), (4, 5), (5, 5))
            dest = min(shed_positions, key=lambda p: distance(pos, p))
            actions.append(["DROP"] if pos == dest else move(pos, dest))
            continue
        if not available_jobs:
            actions.append(["PASS"])
            continue
        best_index = max(range(len(available_jobs)), key=lambda j:
            available_jobs[j][0] - CFG["distance_penalty"] * distance(pos, available_jobs[j][1]))
        priority, target, action = available_jobs.pop(best_index)
        actions.append(action if pos == target else move(pos, target))
    if not actions:
        actions = [["PASS"]]
    return {"farmer": actions[0], "hands": actions[1:], "market": market[:10]}
