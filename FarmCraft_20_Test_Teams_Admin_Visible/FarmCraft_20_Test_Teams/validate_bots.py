#!/usr/bin/env python3
"""Offline syntax, validator-contract and mock-observation checks for all 20 bots."""
import ast
import csv
import hashlib
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parent
FORBIDDEN_MODULES={"ctypes","http","importlib","multiprocessing","os","pathlib","requests","shutil","socket","subprocess","threading","urllib"}
FORBIDDEN_CALLS={"breakpoint","compile","eval","exec","input","open","__import__"}
UNIT_OPS={"PASS","NORTH","SOUTH","EAST","WEST","PLANT","WATER","HARVEST","DIG","DROP","FEED","CARE","COLLECT_FERTILIZER","BUILD_COOP","PICKUP","PLACE"}
MARKET_OPS={"SELL","BUY_SEED","BUY_ANIMAL","BUY_PRODUCT","BUY_LAND","HIRE"}


def observation(day, hour, player, hands, scenario):
    board=[[None if x<5 and y<5 else "LOCKED" for x in range(10)] for y in range(10)]
    if scenario in ("plants", "mixed"):
        board[1][1]={"kind":"PLANT","crop":"CARROT","planted_day":day-3,"yield_units":3,"watered_today":False}
        board[2][0]={"kind":"PLANT","crop":"MELON","planted_day":day-11,"yield_units":6,"watered_today":False,"consecutive_unwatered":1}
        board[0][1]={"kind":"WEED"}
    if scenario in ("animals", "mixed"):
        board[1][2]={"kind":"COOP","animal":"GOOSE","fed_today":False,"cared_today":False,"yield_units":3,"fertilizer_available":True}
        board[2][2]={"kind":"COOP"}
    farm={"money":420 if day<7 else 3500,"farmer":[4,4],"hands":[[4,4] for _ in range(hands)],
          "tiles":board,"unlocked_quadrants":["NW"]}
    p={"seeds":{"WHEAT":5,"CARROT":5,"TOMATO":3,"STRAWBERRY":4,"MELON":4},
       "shed":{"WHEAT":15,"CARROT":3,"MELON":4,"GOOSE":1,"EGG":7,"FERTILIZER":5},
       "inventories":[{"WHEAT":4,"CARROT":2}]+[{} for _ in range(hands)]}
    market={"prices":{"WHEAT":25,"CARROT":35,"TOMATO":60,"STRAWBERRY":120,"MELON":250,"EGG":50,"WOOL":200,"MILK":160,"FERTILIZER":100},
            "inventory":{"WHEAT":10000,"CARROT":10000,"TOMATO":10000,"STRAWBERRY":10000,"MELON":10000,"EGG":10000,"FERTILIZER":10000}}
    return {"player":player,"step":day*24+hour,"day":day,"hour":hour,"farms":[farm,farm],"private":p,"market":market,"town":{}}


def callable_name(node):
    if isinstance(node,ast.Name):return node.id
    if isinstance(node,ast.Attribute):
        parent=callable_name(node.value)
        return (parent+"." if parent else "")+node.attr
    return ""


def validate(path):
    source=path.read_text(encoding="utf-8")
    assert len(source.encode("utf-8"))<100000,path
    tree=ast.parse(source,str(path))
    assert any(isinstance(node,ast.FunctionDef) and node.name=="agent" and len(node.args.args)==1 for node in tree.body),path
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):
            assert all(alias.name.split('.')[0] not in FORBIDDEN_MODULES for alias in node.names),(path,node.lineno)
        if isinstance(node,ast.ImportFrom):
            assert (node.module or '').split('.')[0] not in FORBIDDEN_MODULES,(path,node.lineno)
        if isinstance(node,ast.Call):
            name=callable_name(node.func)
            assert name not in FORBIDDEN_CALLS and name.split('.')[0] not in FORBIDDEN_MODULES,(path,node.lineno,name)
    spec=importlib.util.spec_from_file_location('test_'+path.parent.name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    n=0
    for day in (0,1,4,8,13,19,25,29):
        for hour in (0,10,18,22):
            for player in (0,1):
                for hands in (0,2,6):
                    for scenario in ("empty","plants","animals","mixed"):
                        obs=observation(day,hour,player,hands,scenario)
                        result=module.agent(obs)
                        assert isinstance(result,dict) and {'farmer','hands','market'} <= result.keys(),(path,result)
                        assert isinstance(result['farmer'],list) and result['farmer'] and result['farmer'][0] in UNIT_OPS,(path,result)
                        assert len(result['hands'])==hands,(path,result)
                        assert all(isinstance(action,list) and action and action[0] in UNIT_OPS for action in result['hands']),(path,result)
                        assert isinstance(result['market'],list) and len(result['market'])<=10,(path,result)
                        assert all(isinstance(action,list) and action and action[0] in MARKET_OPS for action in result['market']),(path,result)
                        n+=1
    return n


if __name__=='__main__':
    with (ROOT/'teams.csv').open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==20
    seen=set(); total=0
    for row in rows:
        path=ROOT/row['bot_file']
        assert path.exists()
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest==row['sha256'] and digest not in seen
        seen.add(digest)
        n=validate(path)
        total+=n
        print(f"PASS {row['team']} {row['bot_name']}: {n} mock states, {path.stat().st_size} bytes")
    print(f"PASS: 20 distinct bots; {total} synthetic action/AST validations. No real game matches executed.")
