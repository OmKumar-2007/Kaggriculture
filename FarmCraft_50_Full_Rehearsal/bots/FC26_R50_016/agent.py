"""FarmCraft QA competitive agent: TomatoPerennial, variant 1.\nGenerated solely from public benchmark concepts. Full policy below.\n"""
POLICY = {'family': 'TomatoPerennial', 'variant': 1, 'focus': 'tomato', 'weights': {'TOMATO': 2.244, 'CARROT': 0.792, 'MELON': 0.88}, 'plot_limit': 24, 'goose_target': 0, 'goose_stop_day': 18, 'coop_radius': 5, 'desired_units': 8, 'land_stop_day': 15, 'bootstrap_day': 2, 'bootstrap_plots': 4, 'sell_floor': 0.46, 'supply_penalty': 0.0045, 'diversity_penalty': 0.0, 'travel_penalty': 3.1, 'caps': {'MELON': 18, 'STRAWBERRY': 5, 'TOMATO': 15, 'CARROT': 16, 'WHEAT': 10}}

"""Crop Titan — Cash-Crop Expansion — FarmCraft Harvest Protocol tournament agent.

Self-contained submission. Different families use different scoring and investment policies.
No network, filesystem access, external dependencies, or hidden information.
"""

CONFIG = "GOOSE" if POLICY["goose_target"] else "CROP"

CROPS = {
    "WHEAT": (10, 4, 25, 4),
    "CARROT": (20, 3, 35, 3),
    "TOMATO": (50, 11, 60, 4),
    "STRAWBERRY": (100, 16, 120, 4),
    "MELON": (80, 10, 250, 6),
}
LAST_PLANT = {"WHEAT": 25, "CARROT": 26, "TOMATO": 18,
              "STRAWBERRY": 13, "MELON": 19}
BASE = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60,
        "STRAWBERRY": 120, "MELON": 250, "EGG": 50,
        "MILK": 160, "WOOL": 200, "FERTILIZER": 100}
SHED = ((4, 4), (5, 4), (4, 5), (5, 5))


def num(value, fallback=0):
    try:
        return float(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def qty(mapping, key):
    return max(0, int(num(mapping.get(key, 0))))


def distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def towards(a, b):
    if a[0] < b[0]:
        return ["EAST"]
    if a[0] > b[0]:
        return ["WEST"]
    if a[1] < b[1]:
        return ["SOUTH"]
    if a[1] > b[1]:
        return ["NORTH"]
    return ["PASS"]


def nearest(a, pts):
    return min(pts, key=lambda p: distance(a, p))


def tile_at(tiles, pos):
    x, y = pos
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
        return tiles[y][x]
    return "LOCKED"


def stock(inv):
    return sum(max(0, int(num(v))) for v in inv.values())


def crop_choice(day, price, tiles, position, crops_planted):
    """Different economic families use different crop scheduling and scoring."""
    if day >= 27:
        return None
    focus=POLICY['focus']
    # Early-game bootstrap ensures there is cash for the main investment plan.
    if day <= POLICY['bootstrap_day'] and crops_planted.get('CARROT',0) < POLICY['bootstrap_plots']:
        if focus not in ('melon','market') or distance(position,(4,4))<=3:
            return 'CARROT'
    if focus=='goose' and distance(position,(4,4))<=POLICY['coop_radius'] and day>=3:
        return None   # reserve valuable shed-side plots for animal structures
    prices=price or {}
    thresholds={'WHEAT':12,'CARROT':13,'TOMATO':35,'STRAWBERRY':62,'MELON':58}
    remaining=29-day
    weights=POLICY['weights']
    choices=[]
    for crop,(seed,maturity,base,yields) in CROPS.items():
        if day > LAST_PLANT[crop] or remaining < maturity+1:
            continue
        count=crops_planted.get(crop,0)
        limit=POLICY['caps'].get(crop,20)
        if count>=limit:
            continue
        observed=num(prices.get(crop,base),base)
        if observed<thresholds[crop]:
            continue
        # Mark-to-market profitability penalizes long cycles and nearby oversupply.
        expected=max(1,observed*(1.0 - count*POLICY['supply_penalty']))
        rate=(max(0,expected*yields-seed)/(maturity+1.0))
        # Distinct investment policies.
        if focus=='endgame' and remaining<=9:
            rate*=1.45 if crop in ('CARROT','WHEAT') else 0.35
        elif focus=='strawberry' and day<9 and crop=='STRAWBERRY':
            rate*=1.45
        elif focus=='melon' and day<=7 and crop=='MELON':
            rate*=1.40
        elif focus=='tomato' and day<=13 and crop=='TOMATO':
            rate*=1.35
        elif focus=='balanced':
            rate/=1.0+0.08*count
        elif focus=='market':
            rate*=max(0.5,min(1.8,observed/base))
        elif focus=='labor':
            rate*=1.25 if crop in ('CARROT','MELON') else 1.0
        score=rate*weights.get(crop,0.92)-count*POLICY['diversity_penalty']
        # Preserve some short crops near the shed for cheap trips.
        if crop=='CARROT' and distance(position,(4,4))<=2:
            score*=1.25
        choices.append((score,crop))
    return max(choices)[1] if choices and max(choices)[0]>0 else None

def farm_plan(obs, farm, private):
    day = int(num(obs.get("day")))
    hour = int(num(obs.get("hour")))
    tiles = farm.get("tiles") or []
    prices = (obs.get("market") or {}).get("prices") or {}
    seeds = private.get("seeds") or {}
    shed = private.get("shed") or {}
    money = num(farm.get("money"))
    units = [tuple(farm.get("farmer", [4, 4]))] + [tuple(p) for p in farm.get("hands", [])]
    inventories = private.get("inventories") or []
    inv = [inventories[i] if i < len(inventories) and isinstance(inventories[i], dict)
           else {} for i in range(len(units))]

    free, weeds, plants, livestock, empty_coops = [], [], [], [], []
    planted = {c: 0 for c in CROPS}
    for y, row in enumerate(tiles):
        for x, item in enumerate(row):
            p = (x, y)
            if item is None:
                free.append(p)
            elif not isinstance(item, dict):
                continue
            elif item.get("kind") == "WEED":
                weeds.append(p)
            elif item.get("kind") == "PLANT":
                crop = item.get("crop")
                planted[crop] = planted.get(crop, 0) + 1
                plants.append((p, item))
            elif item.get("kind") in ("COOP", "PASTURE"):
                if item.get("animal"):
                    livestock.append((p, item))
                elif item.get("kind") == "COOP":
                    empty_coops.append(p)

    # Coops are clustered around the shed so wheat deliveries take fewer moves.
    potential = sorted(free + weeds, key=lambda p: (distance(p, (4, 4)), p[1], p[0]))
    reserved = set()
    if POLICY["goose_target"] > 0 and 3 <= day <= POLICY["goose_stop_day"]:
        geese = sum(t.get("animal") == "GOOSE" for _, t in livestock)
        target = min(POLICY["goose_target"], (4 if day <= 6 else 8 if day <= 10 else
                  12 if day <= 16 else POLICY["goose_target"]))
        # Never reserve more coop sites than the remaining labor could manage.
        target = min(target, POLICY["goose_target"])
        need = max(0, target - geese - len(empty_coops))
        for p in potential:
            if need <= 0:
                break
            if distance(p, (4, 4)) <= POLICY["coop_radius"]:
                reserved.add(p)
                need -= 1

    available = [p for p in free if p not in reserved]
    # Cap active crop fields to prevent losing them through understaffing.
    plot_limit = POLICY["plot_limit"]
    extra_slots = max(0, plot_limit - len(plants))
    available.sort(key=lambda p: (distance(p, (4, 4)), p[1], p[0]))
    plant_positions = available[:extra_slots]
    planting = {}
    planned_counts = dict(planted)
    for p in plant_positions:
        choice = crop_choice(day, prices, tiles, p, planned_counts)
        if choice:
            planting[p] = choice
            planned_counts[choice] = planned_counts.get(choice, 0) + 1

    return {"day": day, "hour": hour, "tiles": tiles, "prices": prices,
            "seeds": seeds, "shed": shed, "money": money, "units": units,
            "inventories": inv, "free": free, "weeds": weeds,
            "plants": plants, "livestock": livestock,
            "empty_coops": empty_coops, "reserved": reserved,
            "planting": planting, "planted": planted, "planned_counts": planned_counts,
            "unlocked": len(farm.get("unlocked_quadrants") or ["NW"])}


def market_orders(plan):
    day, hour, money = plan["day"], plan["hour"], plan["money"]
    shed, prices, seeds = plan["shed"], plan["prices"], plan["seeds"]
    orders = []
    shed_total = stock(shed)
    goose_count = sum(t.get("animal") == "GOOSE" for _, t in plan["livestock"])

    # Sell often enough for liquidity, but avoid excessive supply when prices collapse.
    sales = []
    for item in BASE:
        amount = qty(shed, item)
        if item == "WHEAT" and POLICY["goose_target"] > 0 and goose_count and day < 29:
            amount = max(0, amount - 2 * goose_count - 3)
        if not amount:
            continue
        current = num(prices.get(item, BASE[item]), BASE[item])
        floor = POLICY["sell_floor"] * BASE[item]
        if day >= 28 or shed_total >= 75 or money < 120 or current >= floor:
            n = min(amount, 22 if day < 27 else 95)
            sales.append((current * n, item, n))
    sales.sort(reverse=True)
    for _, item, n in sales[:5]:
        orders.append(["SELL", item, n])
        money += n * num(prices.get(item, BASE[item]), BASE[item])

    # Hired hands reset daily in this environment; maximize useful actions early.
    desired_units = POLICY["desired_units"]
    # Cash-sensitive hiring: cheap labor is useful, but starving seed purchases
    # on the first day makes the opening fail.
    if money < 400:
        desired_units = min(desired_units, 3)
    elif money < 1100:
        desired_units = min(desired_units, 5)
    elif money < 2200:
        desired_units = min(desired_units, 7)
    if hour <= 2 and day <= 28 and money >= 100:
        add = max(0, desired_units - len(plan["units"]))
        add = min(add, max(0, 8 - len(orders)))
        for _ in range(add):
            orders.append(["HIRE"])
        # Conservative budget for increasing daily hire costs (Fibonacci).
        money -= add * 37

    if POLICY["goose_target"] > 0:
        # Feed is purchased on the market, then carried from the shed to coops.
        carried_wheat = sum(qty(inv, "WHEAT") for inv in plan["inventories"])
        existing_wheat = qty(shed, "WHEAT") + carried_wheat
        demand = goose_count * 2 + 5
        if goose_count > 0 and day <= 28 and existing_wheat < demand:
            price_wheat = max(1, num(prices.get("WHEAT", 25), 25))
            purchase = min(35, demand - existing_wheat,
                           max(0, int((money - 130) / price_wheat)))
            if purchase:
                orders.append(["BUY_PRODUCT", "WHEAT", purchase])
                money -= purchase * price_wheat
        goose_staged = qty(shed, "GOOSE") + sum(qty(v, "GOOSE") for v in plan["inventories"])
        ready = len(plan["empty_coops"])
        if day <= POLICY["goose_stop_day"] and ready > goose_staged and money >= 480:
            maximum = min(ready - goose_staged, 2, max(0, int((money - 200) / 300)))
            if maximum > 0:
                orders.append(["BUY_ANIMAL", "GOOSE", maximum])
                money -= maximum * 300

    # Small, controlled seed purchases based on open plots and time remaining.
    needs = {}
    for crop in plan["planting"].values():
        needs[crop] = needs.get(crop, 0) + 1
    if day <= 26:
        if day <= 4:
            crop_order = ("CARROT", "MELON", "STRAWBERRY", "TOMATO", "WHEAT")
        else:
            crop_order = ("MELON", "STRAWBERRY", "CARROT", "TOMATO", "WHEAT")
        for crop in crop_order:
            required = needs.get(crop, 0)
            owned = qty(seeds, crop)
            deficit = max(0, required - owned)
            if deficit <= 0:
                continue
            batch = 5 if POLICY["goose_target"] == 0 else 4
            cost = CROPS[crop][0]
            reserve = (65 if day <= 4 else 180) if POLICY["goose_target"] == 0 else (80 if day <= 4 else 240)
            purchase = min(deficit, batch, max(0, int((money - reserve) / cost)))
            if purchase > 0:
                orders.append(["BUY_SEED", crop, purchase])
                money -= cost * purchase
            if len(orders) >= 10:
                break

    # Buy more land only early enough to recover the cost.
    if len(orders) < 10 and day <= POLICY["land_stop_day"]:
        unlocked = plan["unlocked"]
        land_costs = [1000, 2000, 4000]
        if unlocked < 4:
            free_count = len(plan["free"])
            limit = (5 if POLICY["goose_target"] == 0 else 3)
            ready = free_count <= limit or (POLICY["goose_target"] > 0 and
                                            goose_count >= 5 and free_count <= 9)
            if ready and money > land_costs[unlocked - 1] + 900:
                orders.append(["BUY_LAND"])

    return orders[:10]


def available_work(plan):
    day, hour = plan["day"], plan["hour"]
    jobs = []
    def put(p, action, priority, tag=None):
        jobs.append((p, action, priority, tag))

    for pos, tile in plan["plants"]:
        crop = tile.get("crop")
        age = day - int(num(tile.get("planted_day"), day))
        mature = CROPS.get(crop, (0, 3, 0, 0))[1]
        yield_units = qty(tile, "yield_units")
        if yield_units and (age >= mature or day >= 28):
            put(pos, ["HARVEST"], 125 + min(40, yield_units * 3), "crop")
        if not tile.get("watered_today", False) and day <= 28:
            risk = int(num(tile.get("consecutive_unwatered")))
            bonus = 70 if risk >= 1 else 0
            # Important for crop yield; prioritize plants at risk of dying.
            urgency = 20 if hour >= 16 else 0
            if crop == "MELON":
                put(pos, ["WATER"], 112 + bonus + urgency, "water")
            elif crop in ("STRAWBERRY", "TOMATO"):
                put(pos, ["WATER"], 106 + bonus + urgency, "water")
            else:
                put(pos, ["WATER"], 82 + bonus + urgency, "water")

    for pos, tile in plan["livestock"]:
        animal = tile.get("animal")
        if animal == "GOOSE" and POLICY["goose_target"] > 0:
            if day <= 28 and not tile.get("fed_today", False):
                risk = int(num(tile.get("consecutive_unfed")))
                put(pos, ["FEED"], 190 + 25 * risk + (35 if hour >= 17 else 0), "feed")
            if tile.get("fertilizer_available", False):
                put(pos, ["COLLECT_FERTILIZER"], 155, "fertilizer")
            if qty(tile, "yield_units") >= 2 or (day >= 28 and qty(tile, "yield_units") > 0):
                put(pos, ["HARVEST"], 165, "animal_harvest")
            if day <= 28 and not tile.get("cared_today", False):
                put(pos, ["CARE"], 38, "care")
        elif qty(tile, "yield_units") > 0:
            put(pos, ["HARVEST"], 135, "animal_harvest")

    if POLICY["goose_target"] > 0 and day <= 22:
        for pos in plan["reserved"]:
            if tile_at(plan["tiles"], pos) is None:
                put(pos, ["BUILD_COOP"], 139, "build")
            elif isinstance(tile_at(plan["tiles"], pos), dict):
                put(pos, ["DIG"], 118, "dig")
        for pos in plan["empty_coops"]:
            put(pos, ["PLACE", "GOOSE"], 174, "place")

    # Plant at most as much as the actual seed budget supports.
    for pos, crop in plan["planting"].items():
        put(pos, ["PLANT", crop], 87 if POLICY["goose_target"] == 0 else 75, "plant")

    # Weed clearance is deliberately lower priority than watering/harvest.
    for pos in plan["weeds"]:
        if pos not in plan["reserved"] and day <= 25:
            put(pos, ["DIG"], 41, "dig")

    return jobs


def assign_workers(plan, jobs):
    day, hour = plan["day"], plan["hour"]
    units, invs = plan["units"], plan["inventories"]
    shed, seeds = plan["shed"], plan["seeds"]
    positions = set()
    acts = []
    used_seed = dict((c, qty(seeds, c)) for c in CROPS)
    goose_total = sum(t.get("animal") == "GOOSE" for _, t in plan["livestock"])
    hungry = sum(t.get("animal") == "GOOSE" and not t.get("fed_today", False)
                 for _, t in plan["livestock"])
    carrier = sum(qty(inv, "GOOSE") for inv in invs)
    staged = qty(shed, "GOOSE")
    placed = set()

    # Pick the unit closest to the shed to move purchased geese to their coops.
    goose_fetcher = None
    if POLICY["goose_target"] > 0 and plan["empty_coops"] and staged and carrier == 0:
        goose_fetcher = min(range(len(units)),
                            key=lambda i: distance(units[i], nearest(units[i], SHED)))

    # Limit wheat fetching to workers who can actually feed animals.
    wheat_fetchers = set()
    if POLICY["goose_target"] > 0 and hungry > 0 and qty(shed, "WHEAT") > 0:
        wheat_carried = sum(qty(inv, "WHEAT") for inv in invs)
        if wheat_carried < hungry + 2:
            candidates = sorted(range(len(units)),
                                key=lambda i: distance(units[i], nearest(units[i], SHED)))
            need_workers = min(len(units), max(1, (hungry + 3) // 4))
            for idx in candidates:
                if idx == goose_fetcher or qty(invs[idx], "WHEAT") >= 4:
                    continue
                wheat_fetchers.add(idx)
                if len(wheat_fetchers) >= need_workers:
                    break

    for i, origin in enumerate(units):
        inv = invs[i]
        base_cargo = sum(qty(inv, item) for item in BASE)
        wheat = qty(inv, "WHEAT")
        geese = qty(inv, "GOOSE")
        on_shed = origin in SHED

        if POLICY["goose_target"] > 0 and geese and plan["empty_coops"]:
            # Dedicated transport of purchased animals, rather than dropping them.
            destination = nearest(origin, [p for p in plan["empty_coops"] if p not in placed]
                                  or plan["empty_coops"])
            placed.add(destination)
            acts.append(["PLACE", "GOOSE"] if origin == destination
                        else towards(origin, destination))
            continue

        if i == goose_fetcher:
            target = nearest(origin, SHED)
            acts.append(["PICKUP", "GOOSE", 1] if on_shed
                        else towards(origin, target))
            continue

        # Move harvests and fertilizer to the market shed regularly.
        commodity_cargo = (base_cargo if day >= 29 else
                           base_cargo - (wheat if POLICY["goose_target"] > 0 else 0))
        rush_return = day >= 29 or (day >= 28 and hour >= 12)
        if commodity_cargo >= (5 if POLICY["goose_target"] > 0 else 6) or \
                (rush_return and commodity_cargo > 0):
            destination = nearest(origin, SHED)
            acts.append(["DROP"] if on_shed else towards(origin, destination))
            continue

        if i in wheat_fetchers and wheat < 4:
            destination = nearest(origin, SHED)
            n = min(8, qty(shed, "WHEAT"))
            acts.append(["PICKUP", "WHEAT", n] if on_shed else towards(origin, destination))
            continue

        # All other workers choose the most valuable reachable unclaimed task.
        best_job, best_score = None, -1000000.0
        for p, action, priority, tag in jobs:
            if p in positions:
                continue
            if tag == "feed" and not wheat:
                continue
            if tag == "place" and not geese:
                continue
            if tag == "plant" and used_seed.get(action[1], 0) <= 0:
                continue
            d = distance(origin, p)
            score = priority - POLICY["travel_penalty"] * d
            if p == origin:
                score += 28
            if score > best_score:
                best_score, best_job = score, (p, action, tag)

        if best_job:
            p, action, tag = best_job
            positions.add(p)
            if tag == "plant":
                used_seed[action[1]] -= 1
            acts.append(action if origin == p else towards(origin, p))
        elif commodity_cargo > 0:
            destination = nearest(origin, SHED)
            acts.append(["DROP"] if on_shed else towards(origin, destination))
        else:
            acts.append(["PASS"])

    return acts


def agent(obs):
    """Run an observation-only policy and return the exact game action shape."""
    try:
        player = int(num(obs.get("player")))
        farms = obs.get("farms") or []
        if player < 0 or player >= len(farms):
            return {"farmer": ["PASS"], "hands": [], "market": []}
        farm = farms[player]
        private = obs.get("private") or {}
        plan = farm_plan(obs, farm, private)
        market = market_orders(plan)
        jobs = available_work(plan)
        actions = assign_workers(plan, jobs)
        return {"farmer": actions[0], "hands": actions[1:], "market": market}
    except Exception:
        # Never crash an official match because one observation is unusual.
        try:
            farm = (obs.get("farms") or [])[int(num(obs.get("player")))]
            hands = [["PASS"] for _ in farm.get("hands", [])]
        except Exception:
            hands = []
        return {"farmer": ["PASS"], "hands": hands, "market": []}
