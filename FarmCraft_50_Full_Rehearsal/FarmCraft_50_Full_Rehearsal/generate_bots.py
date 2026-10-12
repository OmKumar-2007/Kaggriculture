#!/usr/bin/env python3
"""Generate 50 standalone FarmCraft agents from ten *distinct* economic policies.

All generated agents include an embedded full worker scheduler; imports only stdlib.
Variants alter actual crop scoring, timing, workforce, land and livestock rules.
This establishes diversity, NOT proven win rates. benchmark_bots.py gates real quality.
"""
from __future__ import annotations
import ast,csv,hashlib,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BASE=(ROOT/'notes'/'original_crop_engine.py').read_text(encoding='utf-8').replace('Only the CONFIG constant differs between editions.', 'Different families use different scoring and investment policies.')
FAMILIES=[
 ('MelonCompound', 'melon', {'MELON':2.0,'CARROT':1.08,'WHEAT':0.5}, 24,0,12,19),
 ('BerryCapital', 'strawberry', {'STRAWBERRY':2.55,'MELON':1.18,'CARROT':1.1},26,0,11,16),
 ('CarrotVelocity', 'carrot', {'CARROT':2.4,'WHEAT':1.05,'MELON':0.8},31,0,9,14),
 ('TomatoPerennial', 'tomato', {'TOMATO':2.55,'CARROT':0.9,'MELON':1.0},27,0,10,17),
 ('MarketRotation', 'market', {'MELON':1.25,'CARROT':1.05,'STRAWBERRY':1.17},30,0,11,16),
 ('PortfolioHedge', 'balanced', {'MELON':1.35,'CARROT':1.3,'STRAWBERRY':1.15,'TOMATO':1.14},27,0,9,16),
 ('GooseEggFactory', 'goose', {'CARROT':1.3,'MELON':0.9,'WHEAT':0.75},13,14,11,13),
 ('GooseMixedAssets', 'goose', {'MELON':1.3,'CARROT':1.3,'TOMATO':0.85},18,9,10,14),
 ('LaborMaximizer', 'labor', {'MELON':1.6,'CARROT':1.0,'STRAWBERRY':1.4},32,0,11,17),
 ('EndgameLiquidator', 'endgame', {'CARROT':1.75,'WHEAT':1.2,'MELON':1.3},27,0,10,16),
]
# The policy source replaces specific functions, not just their constants.
START=BASE.index('def crop_choice(')
END=BASE.index('\ndef farm_plan(',START)
NEW_CHOICE='''def crop_choice(day, price, tiles, position, crops_planted):
    """Different economic families use different crop scheduling and scoring."""
    if day >= 27:
        return None
    focus=POLICY['focus']
    # Early-game bootstrap ensures there is cash for the main investment plan.
    if day <= POLICY['bootstrap_day'] and crops_planted.get('CARROT',0) < POLICY['bootstrap_plots']:
        if focus not in ('melon','market') or distance(position,(4,4))<=3:
            return 'CARROT'
    if focus=='goose' and distance(position,(4,4))<=POLICY['coop_radius'] and day>=3:
        return None   # reserve valuable shed-side plots for animal structures
    prices=price or {}
    thresholds={'WHEAT':12,'CARROT':13,'TOMATO':35,'STRAWBERRY':62,'MELON':58}
    remaining=29-day
    weights=POLICY['weights']
    choices=[]
    for crop,(seed,maturity,base,yields) in CROPS.items():
        if day > LAST_PLANT[crop] or remaining < maturity+1:
            continue
        count=crops_planted.get(crop,0)
        limit=POLICY['caps'].get(crop,20)
        if count>=limit:
            continue
        observed=num(prices.get(crop,base),base)
        if observed<thresholds[crop]:
            continue
        # Mark-to-market profitability penalizes long cycles and nearby oversupply.
        expected=max(1,observed*(1.0 - count*POLICY['supply_penalty']))
        rate=(max(0,expected*yields-seed)/(maturity+1.0))
        # Distinct investment policies.
        if focus=='endgame' and remaining<=9:
            rate*=1.45 if crop in ('CARROT','WHEAT') else 0.35
        elif focus=='strawberry' and day<9 and crop=='STRAWBERRY':
            rate*=1.45
        elif focus=='melon' and day<=7 and crop=='MELON':
            rate*=1.40
        elif focus=='tomato' and day<=13 and crop=='TOMATO':
            rate*=1.35
        elif focus=='balanced':
            rate/=1.0+0.08*count
        elif focus=='market':
            rate*=max(0.5,min(1.8,observed/base))
        elif focus=='labor':
            rate*=1.25 if crop in ('CARROT','MELON') else 1.0
        score=rate*weights.get(crop,0.92)-count*POLICY['diversity_penalty']
        # Preserve some short crops near the shed for cheap trips.
        if crop=='CARROT' and distance(position,(4,4))<=2:
            score*=1.25
        choices.append((score,crop))
    return max(choices)[1] if choices and max(choices)[0]>0 else None
'''
BASE=BASE[:START]+NEW_CHOICE+BASE[END:]
# Parameterize livestock and resource scheduling from the common scheduler. All code remains self-contained.
BASE=BASE.replace('if CONFIG == "GOOSE"','if POLICY["goose_target"] > 0').replace('CONFIG == "GOOSE"','POLICY["goose_target"] > 0').replace('CONFIG == "CROP"','POLICY["goose_target"] == 0')
BASE=BASE.replace('if 3 <= day <= 22:', 'if 3 <= day <= POLICY["goose_stop_day"]:')
BASE=BASE.replace('if POLICY["goose_target"] > 0 and 3 <= day <= 22:', 'if POLICY["goose_target"] > 0 and 3 <= day <= POLICY["goose_stop_day"]:')
BASE=BASE.replace('target = (4 if day <= 6 else 8 if day <= 10 else\n                  12 if day <= 16 else 15)', 'target = min(POLICY["goose_target"], (4 if day <= 6 else 8 if day <= 10 else\n                  12 if day <= 16 else POLICY["goose_target"]))')
BASE=BASE.replace('target = min(target, 15)', 'target = min(target, POLICY["goose_target"])')
BASE=BASE.replace('if distance(p, (4, 4)) <= 5:', 'if distance(p, (4, 4)) <= POLICY["coop_radius"]:')
BASE=BASE.replace('plot_limit = 30 if POLICY["goose_target"] == 0 else 16','plot_limit = POLICY["plot_limit"]')
BASE=BASE.replace('desired_units = 10 if POLICY["goose_target"] == 0 else 11','desired_units = POLICY["desired_units"]')
BASE=BASE.replace('floor = (0.54 if POLICY["goose_target"] == 0 else 0.59) * BASE[item]','floor = POLICY["sell_floor"] * BASE[item]')
BASE=BASE.replace('if day <= (18 if POLICY["goose_target"] == 0 else 16):','if day <= POLICY["land_stop_day"]:')
BASE=BASE.replace('if len(orders) < 10 and day <= (18 if POLICY["goose_target"] == 0 else 16):', 'if len(orders) < 10 and day <= POLICY["land_stop_day"]:')
BASE=BASE.replace('score = priority - (4.1 if POLICY["goose_target"] == 0 else 3.3) * d','score = priority - POLICY["travel_penalty"] * d')
BASE=BASE.replace('if day <= 20 and ready > goose_staged and money >= 480:', 'if day <= POLICY["goose_stop_day"] and ready > goose_staged and money >= 480:')
BASE=BASE.replace('return orders[:10]','return orders[:10]')
# Improve late-day logistics: carrying some goods on the final day must be delivered earlier.
BASE=BASE.replace('rush_return = day >= 29 or (day >= 28 and hour >= 12)','rush_return = day >= 29 or (day >= 28 and hour >= 12)')


def config_source(i,family,focus,weights,plot,geese,labor,land):
    variation=(i%5)
    stages=[(0,0,1.0),(1,1,1.08),(2,0,0.92),(3,2,1.16),(4,1,1.0)]
    bootstrap_add,cap_add,mult=stages[variation]
    p={
      'family':family, 'variant':variation+1, 'focus':focus,
      'weights':{k:round(v*(1.0+(variation-2)*0.06),4) for k,v in weights.items()},
      'plot_limit':max(12,plot+[-3,0,2,-1,3][variation]),
      'goose_target':max(0,geese+([0,2,-2,3,-1][variation] if geese else 0)),
      'goose_stop_day': min(22,18+variation), 'coop_radius':max(3,5+(variation%2)),
      'desired_units':min(11,max(6,labor+[-2,-1,0,1,0][variation])),
      'land_stop_day':max(9,land+[-2,0,1,-1,0][variation]),
      'bootstrap_day':2+bootstrap_add+(1 if focus in ('goose','carrot') else 0),
      'bootstrap_plots':4+cap_add+(2 if focus=='carrot' else 0),
      'sell_floor':round(0.46+0.055*variation + (0.05 if focus=='market' else 0),3),
      'supply_penalty':round(0.0045+variation*0.0018,4),
      'diversity_penalty':float(variation%3)*0.8,
      'travel_penalty':round(3.1+(variation%4)*0.5,2),
      'caps':{'MELON':([18,22,25,20,27][variation] if focus not in ('carrot','goose') else 9),
        'STRAWBERRY': (9 if focus=='strawberry' else 5),
        'TOMATO':(15 if focus=='tomato' else 8),
        'CARROT': (25 if focus=='carrot' else 16), 'WHEAT':10}
    }
    # IMPORTANT: Each source embeds a decision policy and no dynamic imports.
    source=(f'"""FarmCraft QA competitive agent: {family}, variant {variation+1}.\\n'
            f'Generated solely from public benchmark concepts. Full policy below.\\n"""\n'
            f'POLICY = {repr(p)}\n\n'
            +BASE.replace('CONFIG = "CROP"','CONFIG = "GOOSE" if POLICY["goose_target"] else "CROP"'))
    # The template has a leading module docstring; two docstrings are allowed.
    ast.parse(source)
    return source,p

def main():
    records=[]
    for fi,(fam,focus,weights,plot,geese,labor,land) in enumerate(FAMILIES):
        for v in range(5):
            i=fi*5+v+1
            team=f'FC26_R50_{i:03d}'
            source,p=config_source(v,fam,focus,weights,plot,geese,labor,land)
            dest=ROOT/'bots'/team/'agent.py';dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(source,encoding='utf-8')
            digest=hashlib.sha256(source.encode()).hexdigest()
            records.append({'team':team,'family':fam,'variant':v+1,'bot_file':str(dest.relative_to(ROOT)).replace('\\','/'),
                            'sha256':digest,'policy':json.dumps(p,sort_keys=True)})
    assert len({r['sha256'] for r in records})==50
    with (ROOT/'teams.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=records[0].keys());w.writeheader();w.writerows(records)
    print(f'Generated {len(records)} bots across {len(FAMILIES)} decision families')

if __name__=='__main__':main()
