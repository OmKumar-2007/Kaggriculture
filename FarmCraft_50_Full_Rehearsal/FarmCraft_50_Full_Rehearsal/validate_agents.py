#!/usr/bin/env python3
"""Static and synthetic smoke checks, NOT a substitute for full Kaggriculture matches."""
from __future__ import annotations
import ast,csv,hashlib,importlib.util,json,random,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FORBIDDEN={'ctypes','http','importlib','multiprocessing','os','pathlib','requests','shutil','socket','subprocess','threading','urllib'}
FORBIDDEN_CALLS={'breakpoint','compile','eval','exec','input','open','__import__'}

def fixture(day=2,hour=5,hands=1):
    farm={'farmer':[4,4],'hands':[[5,4]]*hands,'tiles':[[None for _ in range(10)] for _ in range(10)],
          'money':2500,'unlocked_quadrants':['NW','NE','SW','SE']}
    farm['tiles'][2][2]={'kind':'PLANT','crop':'CARROT','yield_units':4,'watered_today':True,'planted_day':0}
    farm['tiles'][3][3]={'kind':'PLANT','crop':'MELON','yield_units':0,'watered_today':False,'planted_day':1}
    farm['tiles'][4][2]={'kind':'COOP','animal':'GOOSE','fed_today':False,'cared_today':False,'fertilizer_available':True,'yield_units':2}
    farm['tiles'][5][6]='LOCKED';farm['tiles'][1][4]={'kind':'WEED'}
    return {'player':0,'farms':[farm,{**farm,'farmer':[6,6]}], 'private':{'seeds':{a:5 for a in ('WHEAT','CARROT','MELON','STRAWBERRY','TOMATO')},
        'shed':{'WHEAT':20,'EGG':9,'MELON':3},'inventories':[{'WHEAT':5}]+[{} for _ in range(hands)]},
        'market':{'prices':{'WHEAT':25,'CARROT':35,'MELON':250,'STRAWBERRY':120,'TOMATO':60,'EGG':50,'MILK':160,'WOOL':200,'FERTILIZER':100}},
        'day':day,'hour':hour,'step':day*24+hour}

def main():
    with (ROOT/'teams.csv').open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    errors=[];samples=0;valid=0
    for row in rows:
        team=row['team'];path=ROOT/row['bot_file']
        try:
            src=path.read_text(encoding='utf-8')
            assert len(src.encode('utf-8'))<=100_000,'100KB source limit'
            assert hashlib.sha256(src.encode()).hexdigest()==row['sha256'],'SHA mismatch'
            tree=ast.parse(src)
            assert any(isinstance(n,ast.FunctionDef) and n.name=='agent' and len(n.args.args)==1 for n in tree.body)
            for n in ast.walk(tree):
                if isinstance(n,ast.Import):assert all(x.name.split('.')[0] not in FORBIDDEN for x in n.names),'forbidden import'
                if isinstance(n,ast.ImportFrom):assert (n.module or '').split('.')[0] not in FORBIDDEN,'forbidden import'
                if isinstance(n,ast.Call) and isinstance(n.func,ast.Name):assert n.func.id not in FORBIDDEN_CALLS,'forbidden call'
            spec=importlib.util.spec_from_file_location('qaagent_'+team,str(path));mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            for day in (0,1,4,8,12,18,23,28,29):
                for hour in (0,12,22):
                    for hands in (0,2):
                        obs=fixture(day,hour,hands)
                        act=mod.agent(obs);samples+=1
                        assert isinstance(act,dict) and {'farmer','hands','market'}<=act.keys()
                        assert isinstance(act['farmer'],list) and len(act['farmer'])>=1
                        assert isinstance(act['hands'],list) and len(act['hands'])==hands
                        assert all(isinstance(x,list) and x for x in act['hands'])
                        assert isinstance(act['market'],list) and len(act['market'])<=10
            valid+=1
        except Exception as exc:errors.append({'team':team,'error':str(exc)[:300]})
    payload={'count':len(rows),'valid':valid,'syntheticObservations':samples,'errors':errors,
             'note':'Synthetic tests do not measure actual 720-step performance. Run benchmark_bots.py.'}
    (ROOT/'runtime').mkdir(exist_ok=True)
    (ROOT/'runtime'/'static_validation.json').write_text(json.dumps(payload,indent=2))
    print('Static validated:',valid,'/',len(rows),'synthetic observations:',samples)
    for e in errors[:10]:print('ERROR',e)
    return 0 if valid==50 else 2
if __name__=='__main__':sys.exit(main())
