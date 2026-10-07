"""Private animal baseline. It is intentionally absent from the public sandbox catalog."""


def agent(obs):
    me, private = obs["farms"][obs["player"]], obs["private"]
    market = []
    if obs.get("step", 0) == 0:
        market.extend([["BUY_ANIMAL", "GOOSE", 1], ["BUY_PRODUCT", "WHEAT", 12]])
    if private["shed"].get("EGG", 0):
        market.append(["SELL", "EGG", private["shed"]["EGG"]])
    x, y = me["farmer"]
    tile = me["tiles"][y][x]
    inventory = private.get("inventories", [{}])[0]
    if tile is None:
        action = ["BUILD_COOP"]
    elif isinstance(tile, dict) and tile.get("kind") == "COOP" and not tile.get("animal"):
        action = ["PLACE", "GOOSE"] if inventory.get("GOOSE", 0) else ["PICKUP", "GOOSE", 1] if private["shed"].get("GOOSE", 0) else ["PASS"]
    elif isinstance(tile, dict) and tile.get("animal") == "GOOSE":
        action = ["HARVEST"] if tile.get("yield_units", 0) else ["FEED"] if inventory.get("WHEAT", 0) else ["PICKUP", "WHEAT", 3]
    elif sum(inventory.values()) and (x, y) in ((4, 4), (5, 4), (4, 5), (5, 5)):
        action = ["DROP"]
    else:
        action = ["PASS"]
    return {"farmer": action, "hands": [["PASS"] for _ in me.get("hands", [])], "market": market}

