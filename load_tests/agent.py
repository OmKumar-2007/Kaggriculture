def agent(obs):
    """A deliberately simple workshop baseline.

    Strategy:
    - Buy wheat seeds when necessary.
    - Plant wheat on empty tiles.
    - Water wheat every day.
    - Harvest mature wheat.
    - Sell wheat from the shed.
    - Otherwise pass.

    This is intentionally simple. Participants should beat it.
    """

    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]

    market = []

    if private["seeds"].get("WHEAT", 0) == 0 and me["money"] >= 10:
        market.append(["BUY_SEED", "WHEAT", 1])

    wheat_in_shed = private["shed"].get("WHEAT", 0)
    if wheat_in_shed > 0:
        market.append(["SELL", "WHEAT", wheat_in_shed])

    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]

    if tile is None and private["seeds"].get("WHEAT", 0) > 0:
        return {
            "farmer": ["PLANT", "WHEAT"],
            "hands": [],
            "market": market,
        }

    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        crop = tile.get("crop")
        age = obs["day"] - tile.get("planted_day", obs["day"])

        if crop == "WHEAT" and age >= 2:
            return {
                "farmer": ["HARVEST"],
                "hands": [],
                "market": market,
            }

        if not tile.get("watered_today", False):
            return {
                "farmer": ["WATER"],
                "hands": [],
                "market": market,
            }

    return {
        "farmer": ["PASS"],
        "hands": [],
        "market": market,
    }
