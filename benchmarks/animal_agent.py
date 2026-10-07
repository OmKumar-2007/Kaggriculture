"""Intentionally modest public goose benchmark."""


def agent(obs):
    me = obs["farms"][obs["player"]]
    private = obs["private"]
    market = []
    if obs.get("step", 0) == 0:
        market.extend([["BUY_ANIMAL", "GOOSE", 1], ["BUY_PRODUCT", "WHEAT", 12]])
    eggs = private["shed"].get("EGG", 0)
    if eggs:
        market.append(["SELL", "EGG", eggs])

    x, y = me["farmer"]
    tile = me["tiles"][y][x]
    inventory = private.get("inventories", [{}])[0]
    if tile is None:
        action = ["BUILD_COOP"]
    elif isinstance(tile, dict) and tile.get("kind") == "COOP" and not tile.get("animal"):
        if inventory.get("GOOSE", 0):
            action = ["PLACE", "GOOSE"]
        elif private["shed"].get("GOOSE", 0):
            action = ["PICKUP", "GOOSE", 1]
        else:
            action = ["PASS"]
    elif isinstance(tile, dict) and tile.get("animal") == "GOOSE":
        if tile.get("yield_units", 0):
            action = ["HARVEST"]
        elif not tile.get("fed_today", False):
            if inventory.get("WHEAT", 0):
                action = ["FEED"]
            elif private["shed"].get("WHEAT", 0):
                action = ["PICKUP", "WHEAT", 3]
            else:
                action = ["PASS"]
        else:
            action = ["CARE"]
    elif sum(inventory.values()) and (x, y) in ((4, 4), (5, 4), (4, 5), (5, 5)):
        action = ["DROP"]
    else:
        action = ["PASS"]
    return {"farmer": action, "hands": [["PASS"] for _ in me.get("hands", [])], "market": market}
