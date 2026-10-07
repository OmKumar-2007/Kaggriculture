"""Kaggriculture agent -- price-driven farm.

Everything here is decided from the live market curve rather than from a
fixed crop preference, because the single most valuable fact about this
environment is that the *town* drains market inventory far faster than one
farm can refill it.

Town shops consume for free, every 4 turns, forever, and up to 8 instances
unlock. Anything nobody produces therefore drifts far above base price --
in test seasons milk reaches ~$370 against a $160 base and strawberry
~$330 against $120. Meanwhile the products everyone farms sit near base.

So the agent:
  * replicates the engine's price function exactly,
  * estimates how many units of each product it will put on the market,
  * prices that future volume at the point on the curve where it will
    actually clear, and
  * greedily allocates the next tile to whichever asset has the best
    profit per tile-day at those realistic prices.

That single mechanism picks cows when milk is scarce, geese when eggs are,
strawberries when the smoothie shops stack up, and wheat whenever feeding
the flock from the market has got too expensive.

Secondary but large: labour is nearly free. HIRE costs fib(n) with the
counter resetting daily, so ~12 hands cost 376 coins and buy ~275 extra
actions for the day.
"""

import math

# --------------------------------------------------------------------------
# Engine constants (mirrored from kaggriculture.py)
# --------------------------------------------------------------------------

CROPS = {
    "WHEAT":      {"seed": 10,  "first": 2,  "maxday": 4,  "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "first": 2,  "maxday": 3,  "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50,  "first": 8,  "maxday": 8,  "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first": 10, "maxday": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80,  "first": 10, "maxday": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]

MARKET_I0 = 10000
PRICE_FLOOR = 1
HINGE_GAIN = 8.0

MP = {
    "WHEAT":      {"base":  25, "T": 400, "bf": "sqrt",   "bt": 0.80, "af": "log",    "at": 0.20},
    "CARROT":     {"base":  35, "T": 450, "bf": "hinge",  "bt": 1.00, "af": "sqrt",   "at": 0.70},
    "TOMATO":     {"base":  60, "T": 200, "bf": "hinge",  "bt": 0.40, "af": "sqrt",   "at": 0.60},
    "STRAWBERRY": {"base": 120, "T": 100, "bf": "sqrt",   "bt": 0.70, "af": "linear", "at": 1.60},
    "MELON":      {"base": 250, "T": 300, "bf": "log",    "bt": 0.20, "af": "sq",     "at": 3.60},
    "EGG":        {"base":  50, "T": 332, "bf": "hinge",  "bt": 0.40, "af": "log",    "at": 0.20},
    "MILK":       {"base": 160, "T": 122, "bf": "sqrt",   "bt": 0.60, "af": "linear", "at": 1.60},
    "WOOL":       {"base": 200, "T": 105, "bf": "log",    "bt": 0.20, "af": "sq",     "at": 3.20},
    "FERTILIZER": {"base": 100, "T": 200, "bf": "linear", "bt": 0.40, "af": "linear", "at": 0.40},
}

LAND_PRICES = [1000, 2000, 4000]
SHED_CAP = 100
LAST_DAY = 29

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

P = {
    "hire_max_marginal": 240,     # stop hiring once the next hand costs more
    "hire_hard_cap": 15,
    "actions_per_hand": 20.0,
    "travel_cost": 18.0,          # opportunity cost of one action, in coins
    "sell_alpha": 0.90,           # never push a price below alpha * current
    "sell_chunk": 12,
    "feed_days": 0.5,          # tuned: see notes -- a big reserve chokes the shed
    "cash_floor": 260,            # always keep enough to buy emergency feed
    "land_free_tiles": 8,
    "land_cash_mult": 1.5,
    "last_land_day": 21,
    "payback_days": 5,            # asset must have this long to earn out
    "shed_pressure": 22,
}


def _shape(f, x, T):
    x = max(0.0, x)
    if f == "linear":
        return x
    if f == "sq":
        return x * x
    if f == "sqrt":
        return math.sqrt(x)
    if f == "log":
        return math.log(1.0 + x)
    if f == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price_at(item, inventory):
    """Exact replica of the engine's market_price()."""
    p = MP.get(item)
    if p is None:
        return 1
    base, T = p["base"], p["T"]
    if inventory < MARKET_I0:
        amp = p["bt"] * base / _shape(p["bf"], T, T)
        v = base + amp * _shape(p["bf"], MARKET_I0 - inventory, T)
    else:
        amp = p["at"] * base / _shape(p["af"], T, T)
        v = base - amp * _shape(p["af"], inventory - MARKET_I0, T)
    return max(PRICE_FLOOR, int(round(v)))


def clearing_price(item, inv, extra):
    """Average price we expect for `extra` more units, midpoint approximation."""
    if extra <= 0:
        return price_at(item, inv)
    return price_at(item, inv + extra * 0.5)


def sell_qty(item, inv, have, cap, alpha, dump=False):
    """Largest q <= cap that keeps the marginal price above alpha * spot."""
    if have <= 0:
        return 0
    limit = min(have, cap)
    if dump:
        return limit
    spot = price_at(item, inv)
    floor = max(1, int(spot * alpha))
    n, cur = 0, inv
    while n < limit and price_at(item, cur) >= floor:
        n += 1
        cur += 1
    return n


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _i(x, d=0):
    try:
        return int(x)
    except Exception:
        return d


def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def _pos(x):
    try:
        return (int(x[0]), int(x[1]))
    except Exception:
        return (0, 0)


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def step_to(a, b):
    x, y = a
    tx, ty = b
    if x < tx:
        return ["EAST"]
    if x > tx:
        return ["WEST"]
    if y < ty:
        return ["SOUTH"]
    if y > ty:
        return ["NORTH"]
    return ["PASS"]


def fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def shed_tiles(board):
    h = board // 2
    return [(h - 1, h - 1), (h, h - 1), (h - 1, h), (h, h)]


# --------------------------------------------------------------------------
# Farm view
# --------------------------------------------------------------------------

class Farm:
    def __init__(self, obs, farm, priv):
        self.day = _i(obs.get("day"))
        self.hour = _i(obs.get("hour"))
        self.days_left = max(0, LAST_DAY - self.day)
        self.tiles = farm.get("tiles") or []
        self.board = len(self.tiles) or 10
        self.money = _f(farm.get("money"))
        self.shed = dict(priv.get("shed") or {})
        self.seeds = dict(priv.get("seeds") or {})
        self.quads = list(farm.get("unlocked_quadrants") or ["NW"])
        self.hires_today = _i(farm.get("hires_today"))
        self.shed_used = sum(_i(v) for v in self.shed.values())

        self.empty, self.weeds, self.plants, self.animals = [], [], [], []
        self.free_struct = {"COOP": [], "PASTURE": []}
        self.crop_count = {}
        self.animal_count = {}

        for y, row in enumerate(self.tiles):
            for x, t in enumerate(row):
                p = (x, y)
                if t is None:
                    self.empty.append(p)
                elif t == "LOCKED" or not isinstance(t, dict):
                    continue
                elif t.get("kind") == "WEED":
                    self.weeds.append(p)
                elif t.get("kind") == "PLANT":
                    self.plants.append((p, t))
                    c = t.get("crop", "WHEAT")
                    self.crop_count[c] = self.crop_count.get(c, 0) + 1
                elif "animal" in t:
                    self.animals.append((p, t))
                    a = t.get("animal")
                    self.animal_count[a] = self.animal_count.get(a, 0) + 1
                elif t.get("kind") in ("COOP", "PASTURE"):
                    self.free_struct[t["kind"]].append(p)

        self.n_animals = len(self.animals)
        self.open_tiles = len(self.empty) + len(self.free_struct["COOP"]) + len(self.free_struct["PASTURE"])


# --------------------------------------------------------------------------
# Production planning
# --------------------------------------------------------------------------

def pipeline_volume(F):
    """Units of each product our existing assets will still deliver."""
    vol = dict((k, 0.0) for k in PRODUCTS)
    dl = F.days_left
    for _p, t in F.animals:
        a = ANIMALS.get(t.get("animal"))
        if not a:
            continue
        active = max(0, dl)
        rate = (1.0 + a["interval"]) / a["interval"]      # with daily CARE
        vol[a["product"]] += rate * active
        vol["FERTILIZER"] += active
    for _p, t in F.plants:
        c = t.get("crop", "WHEAT")
        cd = CROPS.get(c)
        if not cd:
            continue
        vol[c] += min(cd["max_yield"], 3)
    return vol


def animal_score(F, kind, inv, vol, wheat_price, fert_price):
    """Profit per tile-day for buying one more animal of this kind."""
    a = ANIMALS[kind]
    dl = F.days_left
    active = dl - a["first"]
    if active < P["payback_days"]:
        return -1e9, 0.0
    rate = (1.0 + a["interval"]) / a["interval"]
    units = rate * active
    prod = a["product"]
    price = clearing_price(prod, inv.get(prod, MARKET_I0), vol.get(prod, 0.0) + units)
    revenue = units * price
    # Every surviving animal also makes one fertilizer per day, free.
    fert_units = float(dl)
    fert_price_eff = clearing_price("FERTILIZER", inv.get("FERTILIZER", MARKET_I0),
                                    vol.get("FERTILIZER", 0.0) + fert_units)
    revenue += fert_units * fert_price_eff * 0.8
    feed = dl * wheat_price
    profit = revenue - feed - a["cost"]
    return profit / max(1.0, dl), profit


def crop_score(F, crop, inv, vol, wheat_price):
    """Profit per tile-day for planting one more of this crop."""
    cd = CROPS[crop]
    dl = F.days_left
    if cd["ongoing"]:
        if dl < cd["first"] + 2:
            return -1e9, 0.0
        n = min(cd["max_yield"], 1 + (dl - cd["first"]) // max(1, cd["interval"]))
        units = float(n)
        occupancy = min(dl, cd["first"] + cd["interval"] * n)
    else:
        if dl < cd["first"]:
            return -1e9, 0.0
        full = cd["maxday"]
        if dl >= full:
            units = float(min(cd["max_yield"], 1 + full - (full + 1) // 2 + 1))
            occupancy = full
        else:
            units = float(min(cd["max_yield"], 1 + max(0, dl - (full + 1) // 2 + 1)))
            occupancy = dl
    price = clearing_price(crop, inv.get(crop, MARKET_I0), vol.get(crop, 0.0) + units)
    if crop == "WHEAT" and F.n_animals:
        # Home-grown wheat displaces a market purchase, which is what it is
        # really worth once our own buying has pushed the wheat price up.
        price = max(price, wheat_price * 0.95)
    profit = units * price - cd["seed"]
    return profit / max(1.0, occupancy), profit


def plan(F, inv):
    """Rank every asset we could add next by profit per tile-day."""
    vol = pipeline_volume(F)
    wheat_price = price_at("WHEAT", inv.get("WHEAT", MARKET_I0) - 1)
    fert_price = price_at("FERTILIZER", inv.get("FERTILIZER", MARKET_I0))

    opts = []
    for k in ANIMALS:
        s, profit = animal_score(F, k, inv, vol, wheat_price, fert_price)
        opts.append((s, "ANIMAL", k, profit))
    for c in CROPS:
        s, profit = crop_score(F, c, inv, vol, wheat_price)
        opts.append((s, "CROP", c, profit))
    opts.sort(key=lambda z: -z[0])
    return opts, vol, wheat_price, fert_price


def feed_shortfall(F, inv):
    """How much wheat we should be holding for the flock."""
    return int(math.ceil(F.n_animals * P["feed_days"])) - _i(F.shed.get("WHEAT"))


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------

def build_jobs(F, inv, unit_invs, opts, vol, wheat_price, fert_price):
    jobs = []
    dl = F.days_left
    access = shed_tiles(F.board)

    def spot(item):
        return price_at(item, inv.get(item, MARKET_I0))

    # ---- animals -------------------------------------------------------
    for p, t in F.animals:
        a = ANIMALS.get(t.get("animal"), ANIMALS["GOOSE"])
        pp = spot(a["product"])
        held = _i(t.get("yield_units"))
        unfed = _i(t.get("consecutive_unfed"))
        rate = (1.0 + a["interval"]) / a["interval"]

        if not t.get("fed_today", False):
            if unfed >= 1:
                # Losing the animal forfeits every remaining unit it would make.
                val = 400.0 + rate * dl * pp * 0.8
            else:
                val = pp * 0.8 + 25.0
            val -= wheat_price
            if val > 0:
                jobs.append({"v": val, "p": p, "a": ["FEED"], "need": "WHEAT", "t": "FEED"})

        if held > 0:
            v = held * pp
            if held >= a["max_held"]:
                v += pp * 1.5          # further production is being discarded
            jobs.append({"v": v, "p": p, "a": ["HARVEST"], "need": None, "t": "HARV_A"})

        if t.get("fertilizer_available", False):
            jobs.append({"v": float(fert_price), "p": p, "a": ["COLLECT_FERTILIZER"],
                         "need": None, "t": "FERT"})

        if not t.get("cared_today", False) and dl >= 1:
            if _i(t.get("pending_care_bonus")) + 1 + held <= a["max_held"]:
                jobs.append({"v": pp * 0.85, "p": p, "a": ["CARE"], "need": None, "t": "CARE"})

    # ---- plants --------------------------------------------------------
    for p, t in F.plants:
        c = t.get("crop", "WHEAT")
        cd = CROPS.get(c, CROPS["WHEAT"])
        cp = spot(c)
        if c == "WHEAT" and F.n_animals:
            cp = max(cp, wheat_price * 0.95)
        age = F.day - _i(t.get("planted_day"), F.day)
        held = _i(t.get("yield_units"))
        unwatered = _i(t.get("consecutive_unwatered"))

        if held > 0 and age >= cd["first"]:
            jobs.append({"v": held * cp + 6.0, "p": p, "a": ["HARVEST"],
                         "need": None, "t": "HARV_P"})

        if not t.get("watered_today", False):
            ws = (cd["maxday"] + 1) // 2
            gain = 0.0
            if not cd["ongoing"]:
                if ws <= age <= cd["maxday"] and held < cd["max_yield"]:
                    gain = cp * (2.0 if _i(t.get("fertilized_until_day"), -1) >= F.day else 1.0)
            else:
                gain = cp * 0.45
            if unwatered >= 1:
                remaining = max(0, cd["max_yield"] - held)
                gain += cp * remaining * 0.7 + 15.0
            if gain > 0:
                jobs.append({"v": gain, "p": p, "a": ["WATER"], "need": None, "t": "WATER"})

    # ---- weeds ---------------------------------------------------------
    if dl >= 3:
        for p in F.weeds:
            jobs.append({"v": 55.0, "p": p, "a": ["DIG"], "need": None, "t": "DIG"})

    # ---- shed logistics -------------------------------------------------
    carried = {}
    for iv in unit_invs:
        for k, v in iv.items():
            carried[k] = carried.get(k, 0) + _i(v)

    # Place animals we are already carrying, then fetch more from the shed.
    for kind, a in ANIMALS.items():
        struct = a["structure"]
        free = F.free_struct[struct]
        if not free:
            continue
        in_hand = carried.get(kind, 0)
        in_shed = _i(F.shed.get(kind))
        if in_hand > 0:
            for p in free[:in_hand]:
                jobs.append({"v": 1200.0, "p": p, "a": ["PLACE", kind],
                             "need": kind, "t": "PLACE"})
        if in_shed > 0:
            want = min(in_shed, max(0, len(free) - in_hand))
            for k in range(min(2, want)):
                jobs.append({"v": 1100.0, "p": access[k % 4],
                             "a": ["PICKUP", kind, min(2, want)], "need": None,
                             "t": "GET_ANIMAL"})

    # Build the structure the plan currently wants.
    if dl >= P["payback_days"] + 2:
        best_animal = None
        for s, typ, key, _pr in opts:
            if typ == "ANIMAL":
                best_animal = (s, key)
                break
        if best_animal and best_animal[0] > 0:
            kind = best_animal[1]
            struct = ANIMALS[kind]["structure"]
            pend = _i(F.shed.get(kind)) + carried.get(kind, 0)
            want = pend - len(F.free_struct[struct])
            if want > 0 and F.empty:
                near = sorted(F.empty, key=lambda q: dist(q, (F.board // 2, F.board // 2)))
                for p in near[:want]:
                    jobs.append({"v": 320.0, "p": p, "a": ["BUILD_" + struct],
                                 "need": None, "t": "BUILD"})

    # Fetch wheat for feeding rounds.
    unfed = [t for _p, t in F.animals if not t.get("fed_today", False)]
    crit = sum(1 for t in unfed if _i(t.get("consecutive_unfed")) >= 1)
    deficit = len(unfed) - carried.get("WHEAT", 0)
    shed_wheat = _i(F.shed.get("WHEAT"))
    if shed_wheat > 0 and deficit > 0:
        batch = max(1, min(10, deficit))
        v = 900.0 if crit else 150.0
        for k in range(min(3, (deficit + batch - 1) // batch)):
            jobs.append({"v": v, "p": access[k % 4],
                         "a": ["PICKUP", "WHEAT", min(batch, shed_wheat)],
                         "need": None, "t": "GET_WHEAT"})

    # ---- planting -------------------------------------------------------
    plant_opts = [(s, key) for s, typ, key, _pr in opts if typ == "CROP" and s > 0]
    if plant_opts and F.empty:
        used = set(j["p"] for j in jobs)
        free = [q for q in F.empty if q not in used]
        free.sort(key=lambda q: dist(q, (F.board // 2, F.board // 2)))
        idx = 0
        for s, crop in plant_opts:
            n = _i(F.seeds.get(crop))
            if n <= 0:
                continue
            cd = CROPS[crop]
            v = max(30.0, s * min(cd["maxday"], F.days_left))
            for p in free[idx:idx + n]:
                jobs.append({"v": v, "p": p, "a": ["PLANT", crop], "need": None, "t": "PLANT"})
            idx += n
            if idx >= len(free):
                break

    # ---- fertilize a crop when fertilizer is cheap to sell ---------------
    if carried.get("FERTILIZER", 0) > 0 and fert_price < 55:
        for p, t in F.plants:
            cd = CROPS.get(t.get("crop", "WHEAT"), CROPS["WHEAT"])
            if cd["ongoing"]:
                continue
            age = F.day - _i(t.get("planted_day"), F.day)
            if _i(t.get("fertilized_until_day"), -1) >= F.day:
                continue
            if age < (cd["maxday"] + 1) // 2 - 1 and _i(t.get("yield_units")) < cd["max_yield"]:
                jobs.append({"v": spot(t.get("crop", "WHEAT")) * 1.6, "p": p,
                             "a": ["FERTILIZE"], "need": "FERTILIZER", "t": "FERTILIZE"})

    return jobs


# --------------------------------------------------------------------------
# Assignment
# --------------------------------------------------------------------------

def assign(F, jobs, positions, unit_invs):
    n = len(positions)
    actions = [None] * n
    taken = set()
    pairs = []
    for ui in range(n):
        iv = unit_invs[ui]
        for ji, j in enumerate(jobs):
            need = j["need"]
            if need and _i(iv.get(need)) <= 0:
                continue
            d = dist(positions[ui], j["p"])
            pairs.append((j["v"] / (d + 1.0), -d, ui, ji))
    pairs.sort(reverse=True)
    for eff, _nd, ui, ji in pairs:
        if actions[ui] is not None or ji in taken:
            continue
        j = jobs[ji]
        d = dist(positions[ui], j["p"])
        if j["v"] - d * P["travel_cost"] <= 0:
            continue
        taken.add(ji)
        actions[ui] = list(j["a"]) if d == 0 else step_to(positions[ui], j["p"])
    return actions, taken


def logistics(F, actions, positions, unit_invs, jobs, taken):
    access = shed_tiles(F.board)
    endgame = (F.day >= LAST_DAY and F.hour >= 8)
    for ui, a in enumerate(actions):
        if a is not None:
            continue
        pos = positions[ui]
        iv = unit_invs[ui]
        total = sum(_i(v) for v in iv.values())
        at_shed = pos in access
        tgt = min(access, key=lambda q: dist(pos, q))

        # Unsold stock scores nothing, so late in the day everything goes home.
        if endgame and total > 0:
            actions[ui] = ["DROP"] if at_shed else step_to(pos, tgt)
            continue

        keep_wheat = _i(iv.get("WHEAT")) if F.n_animals else 0
        cargo = total - keep_wheat
        if cargo >= 4 or (cargo > 0 and at_shed):
            actions[ui] = ["DROP"] if at_shed else step_to(pos, tgt)
            continue

        rest = [j for k, j in enumerate(jobs) if k not in taken]
        if rest:
            j = max(rest, key=lambda z: z["v"] / (dist(pos, z["p"]) + 1.0))
            actions[ui] = list(j["a"]) if pos == j["p"] else step_to(pos, j["p"])
        else:
            actions[ui] = ["PASS"] if at_shed else step_to(pos, tgt)
    return actions


# --------------------------------------------------------------------------
# Market
# --------------------------------------------------------------------------

def market(F, inv, opts, vol, wheat_price, n_units, n_jobs):
    orders = []
    money = F.money
    shed_used = F.shed_used
    last = F.day >= LAST_DAY
    pressure = shed_used > SHED_CAP - P["shed_pressure"]

    # ---- hire ------------------------------------------------------------
    if F.hour == 0:
        want = min(P["hire_hard_cap"], int(n_jobs / 4.0) + 1)
        n = F.hires_today
        while n < want and len(orders) < 10:
            c = fib(n)
            if c > P["hire_max_marginal"] or money < c + P["cash_floor"]:
                break
            orders.append(["HIRE"])
            money -= c
            n += 1

    # ---- sell ------------------------------------------------------------
    reserve = {}
    if F.n_animals and not last:
        reserve["WHEAT"] = int(math.ceil(F.n_animals * P["feed_days"]))
    plan_sell = []
    for item in PRODUCTS:
        have = _i(F.shed.get(item)) - _i(reserve.get(item))
        if have <= 0:
            continue
        mi = _i(inv.get(item), MARKET_I0)
        alpha = P["sell_alpha"]
        cap = P["sell_chunk"]
        dump = last
        if pressure:
            alpha, cap = 0.55, have
        if F.days_left <= 1:
            alpha, cap = 0.6, have
        q = sell_qty(item, mi, have, cap, alpha, dump)
        if q > 0:
            plan_sell.append((price_at(item, mi) * q, item, q))
    plan_sell.sort(reverse=True)
    for _v, item, q in plan_sell:
        if len(orders) >= 10:
            break
        orders.append(["SELL", item, q])
        money += price_at(item, _i(inv.get(item), MARKET_I0)) * q * 0.85
        shed_used -= q
    if last:
        return orders[:10]

    # ---- land ------------------------------------------------------------
    n_extra = len(F.quads) - 1
    if (len(orders) < 10 and n_extra < 3 and F.day <= P["last_land_day"]
            and F.open_tiles <= P["land_free_tiles"]):
        cost = LAND_PRICES[n_extra]
        if money > cost * P["land_cash_mult"]:
            orders.append(["BUY_LAND"])
            money -= cost

    # ---- emergency + routine feed ----------------------------------------
    if F.n_animals and len(orders) < 10:
        short = feed_shortfall(F, inv)
        room = SHED_CAP - shed_used
        # Only top up from the market when we cannot grow it fast enough.
        if short > 0 and room > 0:
            wp = max(1, wheat_price)
            budget = money - P["cash_floor"]
            crit = any(_i(t.get("consecutive_unfed")) >= 1 and not t.get("fed_today")
                       for _p, t in F.animals)
            if crit:
                budget = money
            q = min(short, room, int(max(0.0, budget) // wp))
            if q > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", q])
                money -= q * wp
                shed_used += q

    # ---- buy the best asset the plan wants -------------------------------
    if len(orders) < 10:
        for s, typ, key, profit in opts:
            if s <= 0:
                break
            if typ != "ANIMAL":
                continue
            a = ANIMALS[key]
            pend = _i(F.shed.get(key))
            if pend > 0:
                break                      # place what we already own first
            slots = len(F.free_struct[a["structure"]]) + len(F.empty)
            labour = int(n_units * P["actions_per_hand"] / 3.2)
            slots = min(slots, max(0, labour - F.n_animals), 4)
            feed_budget = F.n_animals * max(1, wheat_price) * P["feed_days"]
            spare = money - P["cash_floor"] - feed_budget
            room = SHED_CAP - shed_used
            if slots > 0 and room > 0 and spare > a["cost"]:
                q = min(slots, room, int(spare // a["cost"]))
                if q > 0:
                    orders.append(["BUY_ANIMAL", key, q])
                    money -= q * a["cost"]
                    shed_used += q
            break

    # ---- seeds ------------------------------------------------------------
    if len(orders) < 10:
        free = len(F.empty)
        for s, typ, key, profit in opts:
            if len(orders) >= 10 or free <= 0:
                break
            if typ != "CROP" or s <= 0:
                continue
            cd = CROPS[key]
            have = _i(F.seeds.get(key))
            want = min(free, 10) - have
            if want > 0 and money > cd["seed"] * want + P["cash_floor"]:
                orders.append(["BUY_SEED", key, want])
                money -= cd["seed"] * want
                free -= want
            break

    return orders[:10]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _run(obs):
    farms = obs.get("farms") or []
    me = _i(obs.get("player"))
    if not farms or me >= len(farms):
        return {"farmer": ["PASS"], "hands": [], "market": []}

    farm = farms[me]
    priv = obs.get("private") or {}
    F = Farm(obs, farm, priv)
    inv = dict((obs.get("market") or {}).get("inventory") or {})

    positions = [_pos(farm.get("farmer"))] + [_pos(h) for h in (farm.get("hands") or [])]
    raw = priv.get("inventories") or []
    unit_invs = [dict(raw[i]) if i < len(raw) and isinstance(raw[i], dict) else {}
                 for i in range(len(positions))]

    opts, vol, wheat_price, fert_price = plan(F, inv)
    jobs = build_jobs(F, inv, unit_invs, opts, vol, wheat_price, fert_price)
    orders = market(F, inv, opts, vol, wheat_price, len(positions), len(jobs))
    actions, taken = assign(F, jobs, positions, unit_invs)
    actions = logistics(F, actions, positions, unit_invs, jobs, taken)
    actions = [a if a else ["PASS"] for a in actions]

    n_hands = len(farm.get("hands") or [])
    while len(actions) < n_hands + 1:
        actions.append(["PASS"])
    return {"farmer": actions[0], "hands": actions[1:1 + n_hands], "market": orders[:10]}


def agent(obs):
    try:
        return _run(obs)
    except Exception:
        try:
            me = _i(obs.get("player"))
            n = len((obs.get("farms") or [])[me].get("hands") or [])
        except Exception:
            n = 0
        return {"farmer": ["PASS"], "hands": [["PASS"]] * n, "market": []}