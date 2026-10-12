#!/usr/bin/env python3
"""Run REAL Kaggriculture 720-step public-benchmark games for 50 generated bots.

Runs run_match.py in your configured Kaggriculture Python environment. No fake
scores; requires dependencies installed. Defaults to 2 seeds x both sides x50.
Use --limit 2 for a quick preflight, then the full command for actual scores.
"""
import argparse,csv,hashlib,json,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',required=True,type=Path)
    p.add_argument('--python',default=sys.executable,help='Python interpreter with kaggle_environments installed')
    p.add_argument('--benchmark',choices=('starter_crop','balanced','trader','animal'),default='starter_crop')
    p.add_argument('--seeds',default='20260929,20261011')
    p.add_argument('--limit',type=int,default=50)
    p.add_argument('--timeout',type=int,default=180)
    p.add_argument('--min-win-rate',type=float,default=.50)
    a=p.parse_args()
    source={
      'starter_crop':'NITW_Farm_AI_Challenge_v1/examples/starter_agent.py',
      'balanced':'benchmarks/balanced_agent.py','trader':'benchmarks/trader_agent.py','animal':'benchmarks/animal_agent.py',
    }
    run=a.repo_root/'run_match.py';opponent=a.repo_root/source[a.benchmark]
    if not run.is_file() or not opponent.is_file():p.error('run_match.py / benchmark agent missing: --repo-root must be Kaggriculture checkout')
    with (ROOT/'teams.csv').open(encoding='utf-8',newline='') as f:teams=list(csv.DictReader(f))[:a.limit]
    if not teams or a.limit>50:p.error('limit must be 1..50')
    seeds=[int(x.strip()) for x in a.seeds.split(',')]
    if not seeds or a.timeout<15:p.error('need seeds and >=15s timeout')
    results=[]
    for i,r in enumerate(teams,1):
        my_agent=ROOT/r['bot_file'];win=0;money=[];opmoney=[];errors=[];duration=0
        source_hash=hashlib.sha256(my_agent.read_bytes()).hexdigest()
        if source_hash!=r['sha256']:raise RuntimeError(f'Source hash mismatch for {r["team"]}; regenerate manifest and revalidate')
        for seed in seeds:
            for side in (0,1):
                paths=[my_agent,opponent] if side==0 else [opponent,my_agent]
                cmd=[a.python,str(run),'--agent1',str(paths[0]),'--agent2',str(paths[1]),'--seed',str(seed)]
                started=time.monotonic()
                try:
                    proc=subprocess.run(cmd,cwd=a.repo_root,capture_output=True,text=True,timeout=a.timeout,check=False)
                    duration+=time.monotonic()-started
                    payload=json.loads(proc.stdout.strip().splitlines()[-1])
                    if proc.returncode or payload.get('error') or payload.get('failure'):
                        raise RuntimeError((payload.get('failure') or payload.get('error') or proc.stderr[:180]))
                    mine=float(payload['p1Score'] if side==0 else payload['p2Score'])
                    other=float(payload['p2Score'] if side==0 else payload['p1Score'])
                    money.append(mine);opmoney.append(other)
                    win+=1.0 if mine>other else 0.5 if mine==other else 0.0
                except Exception as exc:errors.append(f'{seed}/side{side}: {str(exc)[:140]}')
        games=len(seeds)*2; wr=win/games
        passed=len(money)==games and not errors and wr>=a.min_win_rate
        results.append({'team':r['team'],'family':r['family'],'sourceSha256':source_hash,'opponent':a.benchmark,'games':games,
            'winRate':round(wr,3),'meanMoney':round(statistics.mean(money),1) if money else None,
            'meanOpponentMoney':round(statistics.mean(opmoney),1) if opmoney else None,
            'seconds':round(duration,1),'passed':passed,'errors':errors})
        print(f"[{i:02d}/{len(teams)}] {r['team']} {r['family']}: win rate {wr:.0%}, mean ${results[-1]['meanMoney']} quality={'PASS' if passed else 'FAIL'}",flush=True)
        (ROOT/'runtime').mkdir(exist_ok=True)
        (ROOT/'runtime'/'benchmark_results.json').write_text(json.dumps({'benchmark':a.benchmark,'minWinRate':a.min_win_rate,'results':results},indent=2))
    total=sum(x['passed'] for x in results)
    print(f'Real game benchmark passed: {total}/{len(results)}; results saved runtime/benchmark_results.json')
    if total<len(results):sys.exit(2)
if __name__=='__main__':main()
