"""
Kaggriculture solution agent -- "Harvest Hedge"  v2
===================================================

Strategy
--------
1. Opening (days 0-3): melons on the far tiles (two full cycles fit in a
   season) + carrots on the shed-ring reserve tiles for bootstrap cash.
2. Goose economy: coops clustered around the shed.  Eggs ride the most
   price-robust curve in the game and every animal drops 1 free fertilizer
   per day.  Feed wheat is bought at the market instead of wasting tiles.
3. Land is bought aggressively as soon as affordable (it is the growth
   engine: each coop tile pays ~$75/day) -- before any goose purchases.
4. Long crops are gated on the projected marginal price (inventory + own
   cumulative and future sales + opponent supply) so we never grow into a
   crash; melons are capped at 26 tiles because the price curve saturates.
5. Selling replicates the engine's exact price curves: sell exactly as many
   units as keep the marginal price above a per-item floor; dump everything
   in the endgame.
6. Labor: farm hands hired to match estimated workload (fib pricing makes
   them nearly free).  When labor is short, CARE / care-feeding degrade to
   opportunistic so mandatory feeds always land.  Per-turn greedy task
   allocation with tile claims; movement is straight-line.

Day 29 note: the game ends mid-day (last processed turn is day 29 hour 22),
so on the final day units deposit into the shed mid-day and everything is
sold every turn.
"""

import math

# --------------------------------------------------------------------------
# Game constants (mirrored from the engine)
# --------------------------------------------------------------------------
CROPS = {
    "WHEAT":      {"seed": 10,  "myd": 4,  "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "myd": 3,  "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50,  "myd": 8,  "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "myd": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80,  "myd": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}
HARVEST_AGE = {"WHEAT": 4, "CARROT": 3, "MELON": 10, "TOMATO": 11, "STRAWBERRY": 16}
CYCLE_DAYS = {"WHEAT": 5, "CARROT": 4, "MELON": 11, "TOMATO": 12, "STRAWBERRY": 17}
LAST_PLANT = {"WHEAT": 25, "CARROT": 26, "MELON": 19, "TOMATO": 18, "STRAWBERRY": 13}
UNITS_PER_CYCLE = {"WHEAT": 4, "CARROT": 3, "MELON": 6, "TOMATO": 4, "STRAWBERRY": 4}
PRICE_GATE = {"MELON": 60, "STRAWBERRY": 70, "TOMATO": 38, "WHEAT": 13, "CARROT": 13}
MELON_TILE_CAP = 26

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]

PRICE_PARAMS = {
    "WHEAT":      {"base":  25, "I0": 10000, "T": 400, "below_func": "sqrt",  "below_target": 0.80, "above_func": "log",   "above_target": 0.20},
    "CARROT":     {"base":  35, "I0": 10000, "T": 450, "below_func": "hinge", "below_target": 1.00, "above_func": "sqrt",  "above_target": 0.70},
    "TOMATO":     {"base":  60, "I0": 10000, "T": 200, "below_func": "hinge", "below_target": 0.40, "above_func": "sqrt",  "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "below_func": "sqrt",  "below_target": 0.70, "above_func": "linear","above_target": 1.60},
    "MELON":      {"base": 250, "I0": 10000, "T": 300, "below_func": "log",   "below_target": 0.20, "above_func": "sq",    "above_target": 3.60},
    "EGG":        {"base":  50, "I0": 10000, "T": 332, "below_func": "hinge", "below_target": 0.40, "above_func": "log",   "above_target": 0.20},
    "MILK":       {"base": 160, "I0": 10000, "T": 122, "below_func": "sqrt",  "below_target": 0.60, "above_func": "linear","above_target": 1.60},
    "WOOL":       {"base": 200, "I0": 10000, "T": 105, "below_func": "log",   "below_target": 0.20, "above_func": "sq",    "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": 10000, "T": 200, "below_func": "linear","below_target": 0.40, "above_func": "linear","above_target": 0.40},
}
HINGE_GAIN = 8.0

THRESH = {
    "WHEAT": 14, "CARROT": 15, "TOMATO": 34, "STRAWBERRY": 55, "MELON": 62,
    "EGG": 30, "MILK": 85, "WOOL": 110, "FERTILIZER": 34,
}

BOARD = 10
HALF = BOARD // 2
SHED_TILES = ((HALF - 1, HALF - 1), (HALF, HALF - 1), (HALF - 1, HALF), (HALF, HALF))
SHED_SET = set(SHED_TILES)


# --------------------------------------------------------------------------
# Price model (exact replica of the engine's curves)
# --------------------------------------------------------------------------
def _shape(func, x, T=None):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "log10":
        return math.log10(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def market_price(item, inventory):
    p = PRICE_PARAMS.get(item)
    if p is None:
        return 1
    base, I0, T = p["base"], p["I0"], p["T"]
    if inventory < I0:
        f = p["below_func"]
        amp = p["below_target"] * base / _shape(f, T, T)
        price = base + amp * _shape(f, I0 - inventory, T)
    else:
        f = p["above_func"]
        amp = p["above_target"] * base / _shape(f, T, T)
        price = base - amp * _shape(f, inventory - I0, T)
    return max(1, int(round(price)))


# --------------------------------------------------------------------------
# Board geometry
# --------------------------------------------------------------------------
def _quadrant(x, y):
    return ("N" if y < HALF else "S") + ("W" if x < HALF else "E")


def _quad_tiles(q):
    return [(x, y) for y in range(BOARD) for x in range(BOARD) if _quadrant(x, y) == q]


_COOP_RESERVE = (
    sorted(_quad_tiles("NW"), key=lambda t: abs(t[0] - 4) + abs(t[1] - 4))[:14]
    + sorted(_quad_tiles("NE"), key=lambda t: abs(t[0] - 5) + abs(t[1] - 4))[:11]
    + sorted(_quad_tiles("SW"), key=lambda t: abs(t[0] - 4) + abs(t[1] - 5))[:11]
)
_COOP_SET_ALL = set(_COOP_RESERVE)


def _g(d, key, default):
    try:
        if isinstance(d, dict):
            return d.get(key, default)
        return getattr(d, key, default)
    except Exception:
        return default


def _is_weed(t):
    return isinstance(t, dict) and t.get("kind") == "WEED"


def _is_emptyish(t):
    return t is None or _is_weed(t)


def _mature(crop, age, yu):
    a = HARVEST_AGE.get(crop, 3)
    if crop in ("TOMATO", "STRAWBERRY"):
        return age >= a or yu >= 4
    return age >= a


def _shed_value(obs, player):
    """Rough liquidation value of the shed (used only for cash-flow tests)."""
    private = obs["private"]
    shed = _g(private, "shed", {}) or {}
    market = obs["market"]
    prices = _g(market, "prices", {}) or {}
    total = 0
    for item, n in shed.items():
        if isinstance(n, int) and n > 0 and item != "GOOSE":
            total += n * prices.get(item, 0)
    return total


def _goose_base_target(day):
    sched = [(0, 0), (4, 5), (5, 8), (6, 11), (7, 13), (8, 15), (9, 17),
             (10, 19), (11, 20), (12, 21), (14, 22), (16, 23), (18, 24)]
    val = 0
    for d, v in sched:
        if day >= d:
            val = v
        else:
            break
    return val


# --------------------------------------------------------------------------
# Per-player persistent state
# --------------------------------------------------------------------------
_PLAYERS = {}


def _state_for(player, day, hour):
    st = _PLAYERS.get(player)
    if st is None or (day, hour) <= st.get("last_dh", (-1, -1)):
        st = {"last_dh": (-1, -1), "day": -1, "claims": {}, "cum_sold": {},
              "crop_day": -1, "crop_order": [], "short_crop": None}
        _PLAYERS[player] = st
    st["last_dh"] = (day, hour)
    if st["day"] != day:
        st["day"] = day
        st["claims"] = {}
    return st


# --------------------------------------------------------------------------
# Crop choice -- frozen once per day to avoid mid-day flip-flopping
# --------------------------------------------------------------------------
def _freeze_crops(obs, player, day, st):
    if st["crop_day"] == day:
        return
    st["crop_day"] = day
    st["crop_order"] = []
    st["short_crop"] = None

    me = obs["farms"][player]
    farms = obs["farms"]
    opp = farms[1 - player] if len(farms) > 1 else None
    market = obs["market"]
    money = me["money"]
    prices = _g(market, "prices", {}) or {}
    mkinv = _g(market, "inventory", {}) or {}
    tiles = me["tiles"]
    cum = st["cum_sold"]

    # our own future supply still standing in the field
    own_future = {"MELON": 0, "STRAWBERRY": 0, "TOMATO": 0, "WHEAT": 0, "CARROT": 0}
    for row in tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                c = t.get("crop")
                if c in own_future:
                    own_future[c] += UNITS_PER_CYCLE[c]
    opp_future = {"MELON": 0, "STRAWBERRY": 0}
    if opp is not None:
        for row in (_g(opp, "tiles", []) or []):
            for t in row:
                if isinstance(t, dict) and t.get("kind") == "PLANT":
                    c = t.get("crop")
                    if c in opp_future:
                        opp_future[c] += UNITS_PER_CYCLE[c]

    force_carrot = day <= 5 and (money + 0.8 * _shed_value(obs, player)) < 1200
    scored = []
    if not force_carrot:
        for crop in CROPS:
            if day > LAST_PLANT[crop]:
                continue
            proj = (mkinv.get(crop, 10000) + cum.get(crop, 0)
                    + own_future.get(crop, 0) + opp_future.get(crop, 0))
            p = market_price(crop, proj + UNITS_PER_CYCLE[crop])
            if p < PRICE_GATE[crop]:
                continue
            score = (UNITS_PER_CYCLE[crop] * p - CROPS[crop]["seed"]) / CYCLE_DAYS[crop]
            if crop == "WHEAT":
                score += 2
            scored.append((score, crop))
        scored.sort(reverse=True)
    else:
        p = market_price("CARROT", mkinv.get("CARROT", 10000) + cum.get("CARROT", 0) + 3)
        if p >= PRICE_GATE["CARROT"]:
            scored = [(0.0, "CARROT")]
    st["crop_order"] = [c for _s, c in scored[:2]]

    # short crop for reserve tiles (only when they are not needed for coops)
    if day <= LAST_PLANT["CARROT"]:
        p = market_price("CARROT", mkinv.get("CARROT", 10000) + cum.get("CARROT", 0)
                         + own_future.get("CARROT", 0) + 3)
        if p >= PRICE_GATE["CARROT"]:
            st["short_crop"] = "CARROT"
        else:
            pw = market_price("WHEAT", mkinv.get("WHEAT", 10000) + cum.get("WHEAT", 0) + 4)
            if pw >= PRICE_GATE["WHEAT"]:
                st["short_crop"] = "WHEAT"


# --------------------------------------------------------------------------
# Daily plan (recomputed every turn -- pure function of the observation,
# except the frozen crop choice)
# --------------------------------------------------------------------------
def _build_plan(obs, player, day, st):
    me = obs["farms"][player]
    tiles = me["tiles"]
    money = me["money"]
    unlocked = set(me["unlocked_quadrants"])
    market = obs["market"]
    prices = _g(market, "prices", {}) or {}

    geese = 0
    coops_empty = 0
    empty_free = []
    reserve_free = []
    melon_existing = 0
    for y in range(BOARD):
        for x in range(BOARD):
            t = tiles[y][x]
            if _quadrant(x, y) not in unlocked:
                continue
            if _is_emptyish(t):
                if (x, y) in _COOP_SET_ALL:
                    reserve_free.append((x, y))
                else:
                    empty_free.append((x, y))
            elif isinstance(t, dict):
                if "animal" in t and t.get("animal") == "GOOSE":
                    geese += 1
                elif t.get("kind") == "COOP":
                    coops_empty += 1
                elif t.get("kind") == "PLANT" and t.get("crop") == "MELON":
                    melon_existing += 1

    # ---- goose target -----------------------------------------------------
    egg_p = prices.get("EGG", 50)
    fert_p = prices.get("FERTILIZER", 100)
    base_t = _goose_base_target(day)
    per_day_value = 1.5 * egg_p + fert_p
    mult = 1.0 if per_day_value >= 110 else max(0.25, per_day_value / 110.0)
    gtarget = int(base_t * mult)
    gtarget = min(gtarget, geese + coops_empty + len(reserve_free))
    if day > 22:
        gtarget = geese

    # geese parked in the shed / carried by units waiting for a coop
    invs = _g(obs["private"], "inventories", []) or []
    shed = _g(obs["private"], "shed", {}) or {}
    geese_waiting = shed.get("GOOSE", 0) + sum(
        (inv.get("GOOSE", 0) if isinstance(inv, dict) else 0) for inv in invs)

    # ---- coop build set ---------------------------------------------------
    want_coops = max(0, min(6, gtarget - geese))
    build_needed = max(0, want_coops - coops_empty)
    coop_set = set(reserve_free[:build_needed])

    # ---- labor model ------------------------------------------------------
    # Costs are per-day action+move estimates.  Geese are the best value per
    # action ($19) so they are never cut; crop planting is capped by whatever
    # labor is left, and CARE degrades first when the day is tight.
    goose_buys = min(4, max(0, gtarget - geese))
    mand = 8.0 + geese * 5.0 + goose_buys * 4.5 + len(coop_set) * 2.0
    standing_water = 0
    standing_harvest = 0
    for y in range(BOARD):
        for x in range(BOARD):
            t = tiles[y][x]
            if not isinstance(t, dict):
                continue
            if "animal" in t:
                continue
            if t.get("kind") == "PLANT":
                crop = t.get("crop")
                cd = CROPS.get(crop)
                if cd is None:
                    continue
                age = day - t.get("planted_day", day)
                needs_water = t.get("consecutive_unwatered", 0) >= 1
                if not needs_water and not cd["ongoing"]:
                    ws = (cd["myd"] + 1) // 2
                    if ws <= age <= cd["myd"]:
                        needs_water = True
                if needs_water:
                    mand += 2.6
                    standing_water += 1
                yu = t.get("yield_units", 0)
                if yu > 0 and (_mature(crop, age, yu) or day >= 28):
                    mand += 2.2
                    standing_harvest += 1

    # melon window detection: while any melon is in its bonus window its
    # daily watering is worth ~$200/action -- new plantings must not collide
    window_active = False
    for y in range(BOARD):
        for x in range(BOARD):
            t = tiles[y][x]
            if isinstance(t, dict) and t.get("kind") == "PLANT" \
                    and t.get("crop") == "MELON":
                age = day - t.get("planted_day", day)
                if 6 <= age <= 12:
                    window_active = True
                    break
        if window_active:
            break

    NEW_TILE_COST = 6.0 if window_active else (4.5 if day >= 20 else 3.0)
    PAD = 1.15
    UNIT_CAP = 19.0             # measured: ~35% of turns are movement
    # melons are the best value per action in the game and their replant
    # window closes on day 19, so they may borrow labor (triage digs low-value
    # crops to compensate); wheat/carrot get no such slack
    LONG_SLACK = {"MELON": 45, "TOMATO": 15, "STRAWBERRY": 15}

    n_candidates = len(empty_free) + max(0, len(reserve_free) - len(coop_set))
    total_all = (mand + n_candidates * NEW_TILE_COST) * PAD
    units_all = int(math.ceil(total_all / UNIT_CAP))
    over_capacity = False
    budget = 11 * UNIT_CAP / PAD
    spare_raw = budget - mand
    if units_all <= 11 or n_candidates == 0:
        max_new = n_candidates
        hands_now = max(0, min(10, units_all - 1))
    else:
        max_new = max(0, int(spare_raw // NEW_TILE_COST))
        hands_now = 10
        if spare_raw < 0:
            over_capacity = True
    units_avail = 1 + hands_now
    spare = units_avail * UNIT_CAP - (mand + min(max_new, n_candidates) * NEW_TILE_COST) * PAD

    # partial care: as many geese as the remaining labor can genuinely service
    care_count = max(0, min(geese, int(spare // 2.0))) if day < 29 else 0

    # triage: when over capacity, dig up the farthest low-value crops to free
    # their watering labor (they would die of neglect otherwise)
    triage_dig = set()
    if over_capacity:
        sacrificial = []
        for y in range(BOARD):
            for x in range(BOARD):
                t = tiles[y][x]
                if isinstance(t, dict) and t.get("kind") == "PLANT" \
                        and t.get("crop") in ("WHEAT", "CARROT") \
                        and t.get("yield_units", 0) < 2:
                    sacrificial.append((abs(x - 4) + abs(y - 4), x, y))
        sacrificial.sort(reverse=True)
        deficit = (mand * PAD) - units_avail * UNIT_CAP
        n_dig = int(deficit // 3.0) + 1
        triage_dig = set((x, y) for _d, x, y in sacrificial[:n_dig])

    # ---- crop tiles (labor-capped, nearest-to-shed first) ------------------
    empty_free_sorted = sorted(empty_free, key=lambda t: abs(t[0] - 4) + abs(t[1] - 4))
    crop_tiles = {}
    order = st["crop_order"]
    n_new = 0
    if order:
        primary = order[0]
        cap = None
        budget_primary = max_new
        if primary == "MELON":
            cap = max(0, MELON_TILE_CAP - melon_existing)
            budget_primary = max(max_new, int((spare_raw + LONG_SLACK["MELON"]) // 3.0))
        elif primary in LONG_SLACK:
            budget_primary = max(max_new, int((spare_raw + LONG_SLACK[primary]) // 3.0))
        n_primary = 0
        for (x, y) in empty_free_sorted:
            if n_new >= budget_primary:
                break
            if cap is None or n_primary < cap:
                crop_tiles[(x, y)] = primary
                n_primary += 1
            elif len(order) > 1:
                crop_tiles[(x, y)] = order[1]
            else:
                continue
            n_new += 1
    # reserve tiles not needed for coops get the short crop (cheap, near shed)
    if st["short_crop"]:
        for (x, y) in reserve_free:
            if (x, y) in coop_set or n_new >= max_new:
                continue
            crop_tiles[(x, y)] = st["short_crop"]
            n_new += 1

    seed_need = {}
    for c in crop_tiles.values():
        seed_need[c] = seed_need.get(c, 0) + 1

    # tiles allowed to run the feed+care bundle (closest coops first)
    goose_tiles = []
    for y in range(BOARD):
        for x in range(BOARD):
            t = tiles[y][x]
            if isinstance(t, dict) and t.get("animal") == "GOOSE":
                goose_tiles.append((abs(x - 4) + abs(y - 4), x, y))
    goose_tiles.sort()
    care_tiles = set((x, y) for _d, x, y in goose_tiles[:care_count])
    # ---- land -------------------------------------------------------------
    # After ~day 14 new quadrants cannot pay for themselves (no crop fits),
    # so land purchases are strictly an early/mid-game move.
    land, land_cost = None, 0
    if "NE" not in unlocked and 3 <= day <= 8 and money >= 1300:
        land, land_cost = "NE", 1000
    elif "SW" not in unlocked and 7 <= day <= 13 and money >= 3000:
        land, land_cost = "SW", 2000

    return {
        "geese": geese,
        "goose_target": gtarget,
        "coops_empty": coops_empty,
        "geese_waiting": geese_waiting,
        "coop_set": coop_set,
        "crop_tiles": crop_tiles,
        "seed_need": seed_need,
        "land": land,
        "land_cost": land_cost,
        "hands_now": hands_now,
        "care_tiles": care_tiles,
        "triage_dig": triage_dig,
        "care_val": 30 if care_count > 0 else 6,
        "feed2_val": 34 if care_count > 0 else 4,
    }


# --------------------------------------------------------------------------
# Work discovery
# --------------------------------------------------------------------------
# watering value by crop: when labor is short, melons survive first
_WATER_VAL = {
    "MELON": (96, 86), "STRAWBERRY": (88, 78), "TOMATO": (88, 78),
    "WHEAT": (74, 64), "CARROT": (74, 64),
}


def _tile_works(tile, x, y, day, plan, hour=0):
    """All work items available on a tile, sorted by value (desc)."""
    works = []
    if tile is None:
        if (x, y) in plan["coop_set"]:
            works.append(("BUILD", 52 + (18 if plan["geese_waiting"] else 0)))
        c = plan["crop_tiles"].get((x, y))
        if c:
            # late-day plantings often cannot be watered the same day and die
            works.append(("PLANT", 40 if hour <= 18 else 15))
        return works
    if tile == "LOCKED" or not isinstance(tile, dict):
        return works
    k = tile.get("kind")
    if k == "WEED":
        if (x, y) in plan["coop_set"]:
            works.append(("DIG", 50))
        if (x, y) in plan["crop_tiles"]:
            works.append(("DIG", 46))
        return works
    if "animal" in tile:
        in_care = (x, y) in plan["care_tiles"]
        if not tile.get("fed_today", False) and day < 29:
            if tile.get("consecutive_unfed", 0) >= 1:
                works.append(("FEED", 100))
            elif in_care:
                # care-mode geese are fed daily (banks the CARE bonus and
                # keeps them a missed day away from escaping)
                works.append(("FEED2", 34))
        if tile.get("fertilizer_available", False):
            works.append(("COLLECT", 62))
        yu = tile.get("yield_units", 0)
        if yu >= 3 or (day >= 28 and yu >= 1):
            works.append(("HARVESTA", 74))
        if in_care and not tile.get("cared_today", False) and day < 29:
            works.append(("CARE", plan["care_val"]))
        works.sort(key=lambda w: -w[1])
        return works
    if k == "COOP":
        works.append(("PLACE", 96))
        return works
    if k == "PLANT":
        crop = tile.get("crop")
        cd = CROPS.get(crop)
        if cd is None:
            return works
        age = day - tile.get("planted_day", day)
        wv_m, wv_w = _WATER_VAL.get(crop, (74, 64))
        if not tile.get("watered_today", False):
            if tile.get("consecutive_unwatered", 1) >= 1:
                works.append(("WATERM", wv_m))
            elif not cd["ongoing"]:
                ws = (cd["myd"] + 1) // 2
                if ws <= age <= cd["myd"]:
                    works.append(("WATERW", wv_w))
        yu = tile.get("yield_units", 0)
        if yu > 0 and (_mature(crop, age, yu) or day >= 28):
            works.append(("HARVESTP", 78))
        if cd["ongoing"] and age >= HARVEST_AGE.get(crop, 99) and yu <= 0:
            works.append(("DIGP", 24))
        elif (x, y) in plan.get("triage_dig", ()):
            works.append(("DIGP", 55))
        works.sort(key=lambda w: -w[1])
        return works
    return works


# --------------------------------------------------------------------------
# Market layer
# --------------------------------------------------------------------------
def _market_orders(obs, player, day, hour, plan, st):
    me = obs["farms"][player]
    private = obs["private"]
    money = me["money"]
    shed = _g(private, "shed", {}) or {}
    seeds = _g(private, "seeds", {}) or {}
    invs = _g(private, "inventories", []) or []
    market = obs["market"]
    prices = _g(market, "prices", {}) or {}
    mkinv = _g(market, "inventory", {}) or {}
    orders = []

    geese = plan["geese"]
    carried_wheat = 0
    carried_goose = 0
    for inv in invs:
        if isinstance(inv, dict):
            carried_wheat += inv.get("WHEAT", 0)
            carried_goose += inv.get("GOOSE", 0)
    shed_load = sum(v for v in shed.values() if isinstance(v, int))

    # ---- sells (cash first) ----------------------------------------------
    sells = []
    for item in PRODUCTS:
        n = shed.get(item, 0)
        if not isinstance(n, int) or n <= 0:
            continue
        if item == "WHEAT" and geese > 0 and day <= 28:
            n = max(0, n - (geese * 2 + 2))
            if n <= 0:
                continue
        thr = THRESH.get(item, 10)
        if day >= 29 or money < 250:
            thr = 1
        elif shed_load >= 93:
            thr = 2
        elif shed_load >= 84:
            thr = max(2, thr // 2)
        base_inv = mkinv.get(item, 10000)
        cnt = 0
        if thr <= 2:
            cnt = min(n, 95)
        else:
            while cnt < n and cnt < 95 and market_price(item, base_inv + cnt) >= thr:
                cnt += 1
        if cnt > 0:
            sells.append((cnt * prices.get(item, 1), item, cnt))
    sells.sort(key=lambda s: -s[0])
    for _val, item, cnt in sells[:5]:
        orders.append(["SELL", item, cnt])
        st["cum_sold"][item] = st["cum_sold"].get(item, 0) + cnt
        money += _val

    # ---- hires (cheap and existential -- never starved by other buys) ------
    if hour <= 2:
        need = plan["hands_now"] - len(me.get("hands", []) or [])
        for _ in range(max(0, min(need, 4))):
            if money >= 5:
                orders.append(["HIRE"])
                money -= 10

    # ---- feed wheat (existential -- feeds today's geese) ------------------
    if day <= 28:
        have = shed.get("WHEAT", 0) + carried_wheat
        need = geese + 4
        if have < need:
            pw = prices.get("WHEAT", 25) + 2
            buy = min(need - have, 50, max(0, int(money // pw)))
            if buy > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", buy])
                money -= buy * pw

    # ---- geese first: the fertilizer/egg engine self-funds everything else --
    if day <= 22 and hour <= 12:
        want = plan["goose_target"] - geese - shed.get("GOOSE", 0) - carried_goose
        # coops standing + coops being built today both house new geese
        want = min(want, 4, plan["coops_empty"] + len(plan["coop_set"]) + 2)
        wheat_p = prices.get("WHEAT", 25)
        feed_reserve = max(200, int(geese * wheat_p * 1.2))
        # scale down to what we can actually afford -- one goose beats none
        while want > 0 and money < 300 * want + feed_reserve:
            want -= 1
        if want > 0:
            orders.append(["BUY_ANIMAL", "GOOSE", want])
            money -= 300 * want

    # ---- land (growth engine, but never at the cost of the goose ramp) ----
    if plan["land"] and money >= plan["land_cost"] + 1200:
        orders.append(["BUY_LAND"])
        money -= plan["land_cost"]

    # ---- seeds (bought in affordable chunks so cash never craters) --------
    if day <= 26:
        for crop in sorted(plan["seed_need"], key=lambda c: -plan["seed_need"][c]):
            ntiles = plan["seed_need"][crop]
            have = seeds.get(crop, 0)
            if ntiles > have:
                cost = CROPS[crop]["seed"]
                buy = min(ntiles - have, max(0, (int(money) - 200) // cost))
                if buy > 0:
                    orders.append(["BUY_SEED", crop, buy])
                    money -= buy * cost

    return orders[:10]


# --------------------------------------------------------------------------
# Unit layer
# --------------------------------------------------------------------------
def _step_toward(x, y, tx, ty):
    if tx > x:
        return ["EAST"]
    if tx < x:
        return ["WEST"]
    if ty > y:
        return ["SOUTH"]
    if ty < y:
        return ["NORTH"]
    return ["PASS"]


def _nearest_shed(x, y):
    best, bd = SHED_TILES[0], 99
    for (sx, sy) in SHED_TILES:
        d = abs(sx - x) + abs(sy - y)
        if d < bd:
            best, bd = (sx, sy), d
    return best


def _unit_actions(obs, player, day, hour, plan, st):
    me = obs["farms"][player]
    private = obs["private"]
    tiles = me["tiles"]
    shed = _g(private, "shed", {}) or {}
    seeds = _g(private, "seeds", {}) or {}
    invs = _g(private, "inventories", []) or []
    hands = me.get("hands", []) or []

    units = [(0, me["farmer"][0], me["farmer"][1])]
    for i, p in enumerate(hands):
        units.append((i + 1, p[0], p[1]))

    # ---- work map ---------------------------------------------------------
    work = {}          # (x, y) -> list of (typ, val), sorted by val desc
    empty_coops = []
    for y in range(BOARD):
        for x in range(BOARD):
            t = tiles[y][x]
            if isinstance(t, dict) and t.get("kind") == "COOP" and "animal" not in t:
                empty_coops.append((x, y))
            w = _tile_works(t, x, y, day, plan, hour)
            if w:
                work[(x, y)] = w

    claims = st["claims"]

    def _has_work(tile_key, types):
        ws = work.get(tile_key)
        if not ws:
            return False
        return any(t in types for t, _v in ws)

    feed_work = [k for k in work if _has_work(k, ("FEED", "FEED2"))]
    feed_mandatory = [k for k in work if _has_work(k, ("FEED",))]

    # ---- fetcher designation ---------------------------------------------
    # Prefer units that are not mid-errand to an urgent tile, so a unit that
    # is already walking toward a dying plant is not recalled to the shed.
    wheat_carried = 0
    goose_carriers = []
    for idx, x, y in units:
        inv = invs[idx] if idx < len(invs) and isinstance(invs[idx], dict) else {}
        wheat_carried += inv.get("WHEAT", 0)
        if inv.get("GOOSE", 0) > 0:
            goose_carriers.append(idx)

    pos_of = {u[0]: (u[1], u[2]) for u in units}

    def _fetcher_sort_key(u):
        idx, x, y = u
        busy = 0
        # penalize units whose current target is urgent work
        for (tx, ty), c in claims.items():
            if c == idx and (tx, ty) in work:
                ws = work[(tx, ty)]
                if ws and ws[0][0] in ("FEED", "WATERM"):
                    busy = 1
        return (busy, abs(x - 4) + abs(y - 4))

    fetchers = {}
    if feed_mandatory and wheat_carried < len(feed_mandatory) + 2 \
            and shed.get("WHEAT", 0) > 0:
        cands = sorted(units, key=_fetcher_sort_key)
        take = max(1, min(3, (len(feed_mandatory) + 11) // 12))
        for u in cands[:take]:
            fetchers[u[0]] = "WHEAT"
    if shed.get("GOOSE", 0) > 0 and empty_coops and not goose_carriers:
        cands = sorted(units, key=_fetcher_sort_key)
        for u in cands:
            if u[0] not in fetchers:
                fetchers[u[0]] = "GOOSE"
                break

    plant_budget = {c: seeds.get(c, 0) for c in CROPS}

    out = []
    for idx, x, y in units:
        inv = invs[idx] if idx < len(invs) and isinstance(invs[idx], dict) else {}
        inv_total = sum(v for v in inv.values() if isinstance(v, int))

        # final day: deposit everything so it can be sold before the whistle
        if day >= 29 and inv_total >= 4:
            if (x, y) in SHED_SET:
                out.append(["DROP"])
                continue
            sx, sy = _nearest_shed(x, y)
            out.append(_step_toward(x, y, sx, sy))
            continue

        # ---- load wheat before anything else when standing on the shed -----
        # (units spawn here every morning; every unit must be able to FEED,
        # otherwise the mandatory feeds bottleneck on a handful of carriers)
        if (x, y) in SHED_SET and feed_mandatory and inv.get("WHEAT", 0) < 6 \
                and shed.get("WHEAT", 0) > 0 and idx not in fetchers:
            out.append(["PICKUP", "WHEAT", min(shed.get("WHEAT", 0), 10)])
            continue

        # ---- on-tile action: first executable work on this tile ------------
        done = False
        for typ, val in work.get((x, y), []):
            act = None
            if typ in ("FEED", "FEED2"):
                if day < 29 and inv.get("WHEAT", 0) > 0:
                    act = ["FEED"]
            elif typ == "CARE":
                act = ["CARE"]
            elif typ == "COLLECT":
                act = ["COLLECT_FERTILIZER"]
            elif typ in ("HARVESTA", "HARVESTP"):
                act = ["HARVEST"]
            elif typ in ("WATERM", "WATERW"):
                act = ["WATER"]
            elif typ == "PLACE":
                if inv.get("GOOSE", 0) > 0:
                    act = ["PLACE", "GOOSE"]
            elif typ == "BUILD":
                act = ["BUILD_COOP"]
            elif typ in ("DIG", "DIGP"):
                act = ["DIG"]
            elif typ == "PLANT":
                crop = plan["crop_tiles"].get((x, y))
                if crop and plant_budget.get(crop, 0) > 0:
                    plant_budget[crop] -= 1
                    act = ["PLANT", crop]
            if act is not None:
                out.append(act)
                done = True
                break
        if done:
            continue

        # ---- strict fetcher routing ----------------------------------------
        if idx in fetchers:
            item = fetchers[idx]
            if (x, y) in SHED_SET:
                if item == "WHEAT":
                    n = min(shed.get("WHEAT", 0), 20)
                    out.append(["PICKUP", "WHEAT", n])
                else:
                    n = min(shed.get("GOOSE", 0), 5)
                    out.append(["PICKUP", "GOOSE", n])
                continue
            sx, sy = _nearest_shed(x, y)
            out.append(_step_toward(x, y, sx, sy))
            continue

        # ---- pick a target: best executable work on any unclaimed tile ------
        best, bscore = None, -1e18
        for (tx, ty), ws in work.items():
            tval, ttyp = None, None
            for typ, val in ws:
                if typ in ("FEED", "FEED2"):
                    if day >= 29 or inv.get("WHEAT", 0) <= 0:
                        continue
                    # care-feeding only justifies a trip when not degraded
                    if typ == "FEED2" and val <= 6:
                        continue
                if typ == "PLACE" and inv.get("GOOSE", 0) <= 0:
                    continue
                if typ == "PLANT" and plant_budget.get(
                        plan["crop_tiles"].get((tx, ty), ""), 0) <= 0:
                    continue
                tval, ttyp = val, typ
                break
            if ttyp is None:
                continue
            c = claims.get((tx, ty))
            if c is not None and c != idx:
                # allow stealing a claim when we are much closer than the owner
                owner = pos_of.get(c)
                if owner is None:
                    claims.pop((tx, ty), None)
                else:
                    od = abs(owner[0] - tx) + abs(owner[1] - ty)
                    md = abs(x - tx) + abs(y - ty)
                    if od > md + 3:
                        claims.pop((tx, ty), None)
                    else:
                        continue
            d = abs(tx - x) + abs(ty - y)
            urg = 0
            if ttyp == "FEED":
                if hour >= 19:
                    urg = 80
                elif hour >= 14:
                    urg = 35
                elif hour >= 12:
                    urg = 20
            if ttyp == "WATERM":
                if hour >= 19:
                    urg = 70
                elif hour >= 16:
                    urg = 45
                elif hour >= 12:
                    urg = 20
            if ttyp == "WATERW":
                if hour >= 12:
                    urg = 25
            s = tval + urg - 3.2 * d
            if s > bscore:
                bscore, best = s, (tx, ty)
        if best is None:
            out.append(["PASS"])
            continue
        claims[best] = idx
        out.append(_step_toward(x, y, best[0], best[1]))

    return out


# --------------------------------------------------------------------------
# Entry point (must remain the last callable for the file-agent loader)
# --------------------------------------------------------------------------
def agent(obs):
    try:
        day = _g(obs, "day", 0)
        hour = _g(obs, "hour", 0)
        if not isinstance(day, int) or not isinstance(hour, int):
            day, hour = 0, 0
        player = _g(obs, "player", 0)
        farms = _g(obs, "farms", []) or []
        if not farms or player >= len(farms):
            return {"farmer": ["PASS"], "hands": [], "market": []}

        st = _state_for(player, day, hour)
        _freeze_crops(obs, player, day, st)
        plan = _build_plan(obs, player, day, st)
        orders = _market_orders(obs, player, day, hour, plan, st)
        acts = _unit_actions(obs, player, day, hour, plan, st)
        if not acts:
            acts = [["PASS"]]
        return {
            "farmer": acts[0],
            "hands": acts[1:],
            "market": orders,
        }
    except Exception:
        return {"farmer": ["PASS"], "hands": [], "market": []}
