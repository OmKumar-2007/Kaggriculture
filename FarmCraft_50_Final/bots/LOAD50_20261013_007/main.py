"""FarmCraft load-test agent. Deterministic independent policy, no external dependencies."""
POLICY={'family': 'CarrotVelocity', 'variant': 2, 'priority': ['WHEAT', 'TOMATO', 'MELON', 'STRAWBERRY', 'CARROT'], 'style': 'priority', 'reserve': 220, 'seed_target': 8, 'drop_at': 5, 'liquidate_day': 22, 'stock_trigger': 29, 'sell_ratio': 0.78, 'expansion': False}
SEED_COST={"WHEAT":10,"CARROT":20,"TOMATO":50,"STRAWBERRY":100,"MELON":80}
BASE={"WHEAT":25,"CARROT":35,"TOMATO":60,"STRAWBERRY":120,"MELON":250}
LAST={"WHEAT":25,"CARROT":26,"TOMATO":18,"STRAWBERRY":13,"MELON":19}

def integer(v,default=0):
    try:return int(v)
    except (ValueError,TypeError,OverflowError):return default

def distance(a,b):return abs(a[0]-b[0])+abs(a[1]-b[1])
def move(a,b):
    if a[0]<b[0]:return ["EAST"]
    if a[0]>b[0]:return ["WEST"]
    if a[1]<b[1]:return ["SOUTH"]
    if a[1]>b[1]:return ["NORTH"]
    return ["PASS"]
def position(x):
    try:return (integer(x[0]),integer(x[1]))
    except (TypeError,IndexError,KeyError):return (0,0)

def pick_crop(obs, farm, priv):
    day=integer(obs.get("day"));money=integer(farm.get("money")); seeds=priv.get("seeds") or {}
    prices=(obs.get("market") or {}).get("prices") or {}
    allowed=[k for k in POLICY["priority"] if day<=LAST[k] and (integer(seeds.get(k))>0 or money>=SEED_COST[k]+POLICY["reserve"])]
    if not allowed:return "WHEAT" if day<=LAST["WHEAT"] else None
    style=POLICY["style"]
    if style=="market":
        allowed.sort(key=lambda k:(float(prices.get(k,BASE[k]))/max(1,BASE[k]),-POLICY["priority"].index(k)),reverse=True)
    elif style=="balanced":
        allowed.sort(key=lambda k:(BASE[k] / max(1,SEED_COST[k]) + float(prices.get(k,BASE[k]))/BASE[k],-POLICY["priority"].index(k)),reverse=True)
    elif style=="invest":
        allowed.sort(key=lambda k:(BASE[k],-POLICY["priority"].index(k)),reverse=True)
    return allowed[0]

def active_jobs(farm, day):
    jobs=[]; empty=[]
    for y,row in enumerate(farm.get("tiles") or []):
        for x,tile in enumerate(row):
            p=(x,y)
            if tile is None:empty.append(p);continue
            if not isinstance(tile,dict):continue
            kind=tile.get("kind")
            if kind=="WEED":jobs.append((0,"DIG",p))
            elif kind=="PLANT":
                crop=tile.get("crop","WHEAT")
                if integer(tile.get("yield_units"))>0:jobs.append((1,"HARVEST",p))
                elif crop in ("STRAWBERRY","TOMATO","MELON") and not tile.get("watered_today",False):jobs.append((3,"WATER",p))
            elif kind in ("COOP","PASTURE"):
                if integer(tile.get("yield_units"))>0:jobs.append((2,"HARVEST",p))
                elif tile.get("animal") and not tile.get("fed_today",False):jobs.append((4,"FEED",p))
    jobs.sort(key=lambda z:(z[0],distance((0,0),z[2])))
    return jobs,empty

def _agent(obs):
    farms=obs.get("farms") or []; idx=integer(obs.get("player"))
    if idx<0 or idx>=len(farms):return {"farmer":["PASS"],"hands":[],"market":[]}
    farm=farms[idx];priv=obs.get("private") or {};day=integer(obs.get("day")); money=integer(farm.get("money"))
    workers=[position(farm.get("farmer") or (0,0))]+[position(x) for x in (farm.get("hands") or [])]
    inventories=priv.get("inventories") or []; actions=[None]*len(workers)
    jobs,empty=active_jobs(farm,day);claimed=set()
    for _,action,target in jobs:
        candidates=[(distance(p,target),i) for i,p in enumerate(workers) if actions[i] is None]
        if not candidates or target in claimed:continue
        _,i=min(candidates);actions[i]=[action] if workers[i]==target else move(workers[i],target);claimed.add(target)
    crop=pick_crop(obs,farm,priv)
    if crop and day<=LAST[crop]:
        sorted_empty=sorted(empty,key=lambda p:(distance(p,workers[0]),p[0],p[1]))
        for target in sorted_empty:
            candidates=[(distance(p,target),i) for i,p in enumerate(workers) if actions[i] is None]
            if not candidates:break
            _,i=min(candidates)
            actions[i]=["PLANT",crop] if workers[i]==target else move(workers[i],target)
    tiles=farm.get("tiles") or [];mid=len(tiles)//2
    access=[(max(0,mid-1),max(0,mid-1)),(mid,max(0,mid-1)),(max(0,mid-1),mid),(mid,mid)]
    for i,pos in enumerate(workers):
        if actions[i] is not None:continue
        inv=inventories[i] if i<len(inventories) and isinstance(inventories[i],dict) else {}
        if sum(integer(q) for q in inv.values())>=POLICY["drop_at"]:
            dest=min(access,key=lambda p:distance(p,pos));actions[i]=["DROP"] if pos==dest else move(pos,dest)
        else:actions[i]=["PASS"]
    shed=priv.get("shed") or {}; prices=(obs.get("market") or {}).get("prices") or {};orders=[]
    stock=sum(integer(n) for n in shed.values())
    for item in sorted(BASE,key=lambda k:(float(prices.get(k,BASE[k]))/BASE[k],BASE[k]),reverse=True):
        qty=integer(shed.get(item))
        if qty and (day>=POLICY["liquidate_day"] or stock>=POLICY["stock_trigger"] or float(prices.get(item,BASE[item]))>=BASE[item]*POLICY["sell_ratio"]):
            orders.append(["SELL",item,min(20,qty)])
    if crop and day<LAST[crop] and len(orders)<9:
        seed=integer((priv.get("seeds") or {}).get(crop))
        affordable=(money-POLICY["reserve"])//SEED_COST[crop]
        buy=min(max(0,POLICY["seed_target"]-seed),max(0,affordable))
        if buy:orders.append(["BUY_SEED",crop,buy])
    if POLICY["expansion"] and day<=19 and money>4000 and len(farm.get("unlocked_quadrants") or ["NW"])<4 and len(empty)<4:
        orders.append(["BUY_LAND"])
    return {"farmer":actions[0],"hands":actions[1:],"market":orders[:10]}

def agent(obs):
    try:return _agent(obs)
    except Exception:
        try:
            farm=(obs.get("farms") or [])[integer(obs.get("player"))]
            n=len(farm.get("hands") or [])
        except Exception:n=0
        return {"farmer":["PASS"],"hands":[["PASS"] for _ in range(n)],"market":[]}
