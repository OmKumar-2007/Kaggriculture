"""Private crop baseline. It is intentionally absent from the public sandbox catalog."""

CROPS = ("WHEAT", "CARROT")


def agent(obs):
    me, private = obs["farms"][obs["player"]], obs["private"]
    crop = CROPS[obs["day"] % 2]
    market = []
    if private["seeds"].get(crop, 0) == 0:
        market.append(["BUY_SEED", crop, 1])
    for product in CROPS:
        if private["shed"].get(product, 0):
            market.append(["SELL", product, private["shed"][product]])
    x, y = me["farmer"]
    tile = me["tiles"][y][x]
    inventory = private.get("inventories", [{}])[0]
    if sum(inventory.values()) and (x, y) in ((4, 4), (5, 4), (4, 5), (5, 5)):
        action = ["DROP"]
    elif tile is None and private["seeds"].get(crop, 0):
        action = ["PLANT", crop]
    elif isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("yield_units", 0):
        action = ["HARVEST"]
    elif isinstance(tile, dict) and tile.get("kind") == "PLANT" and not tile.get("watered_today", False):
        action = ["WATER"]
    else:
        action = ["WEST"] if x > 0 and obs["hour"] % 2 == 0 else ["NORTH"] if y > 0 else ["EAST"]
    return {"farmer": action, "hands": [["PASS"] for _ in me.get("hands", [])], "market": market}

