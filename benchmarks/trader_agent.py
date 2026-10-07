"""Intentionally modest public market-aware benchmark."""


def agent(obs):
    me = obs["farms"][obs["player"]]
    private = obs["private"]
    prices = obs.get("market", {}).get("prices", {})
    market = []
    for product, amount in private.get("shed", {}).items():
        if amount and prices.get(product, 0) >= 20:
            market.append(["SELL", product, min(amount, 2)])
    if private.get("seeds", {}).get("WHEAT", 0) == 0 and me.get("money", 0) > 200:
        market.append(["BUY_SEED", "WHEAT", 1])
    x, y = me["farmer"]
    tile = me["tiles"][y][x]
    if tile is None and private.get("seeds", {}).get("WHEAT", 0):
        action = ["PLANT", "WHEAT"]
    elif isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("yield_units", 0):
        action = ["HARVEST"]
    elif isinstance(tile, dict) and tile.get("kind") == "PLANT" and not tile.get("watered_today"):
        action = ["WATER"]
    else:
        action = ["PASS"]
    return {"farmer": action, "hands": [["PASS"] for _ in me.get("hands", [])], "market": market}
