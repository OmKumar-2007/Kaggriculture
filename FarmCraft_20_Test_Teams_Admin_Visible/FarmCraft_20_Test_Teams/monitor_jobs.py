#!/usr/bin/env python3
"""Read-only poller for sandbox job IDs created by provision_test_teams.py."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from http.cookiejar import MozillaCookieJar
import json
from pathlib import Path
import time
from urllib.request import HTTPCookieProcessor, build_opener

from provision_test_teams import ROOT, request

DONE={'completed','failed','timeout','cancelled'}

def watch(record,base,runtime,interval,timeout):
    team=record['team']; jobid=record['job_id']
    jar=MozillaCookieJar(str(runtime/'sessions'/f'{team}.cookies.txt'))
    jar.load(ignore_discard=True,ignore_expires=True)
    opener=build_opener(HTTPCookieProcessor(jar))
    t0=time.monotonic();last=''
    while time.monotonic()-t0 < timeout:
        code,payload,latency=request(opener,base,'GET','/jobs/'+jobid)
        if code!=200:
            return {'team':team,'job_id':jobid,'status':f'HTTP_{code}', 'error':str(payload.get('detail',payload))[:300]}
        status=str(payload.get('status','unknown'))
        if status!=last:
            print(team,jobid,status,flush=True);last=status
        if status in DONE:
            data=payload.get('result') or {}
            return {'team':team,'job_id':jobid,'status':status,
                    'bot_score':data.get('botFinalMoney') if isinstance(data,dict) else None,
                    'opponent_score':data.get('opponentFinalMoney') if isinstance(data,dict) else None,
                    'error':payload.get('error',''),'seconds':round(time.monotonic()-t0,1)}
        time.sleep(interval)
    return {'team':team,'job_id':jobid,'status':'client_timeout','error':'Monitoring stopped; server job may continue'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-dir',type=Path,default=ROOT/'runtime')
    p.add_argument('--interval',type=float,default=5)
    p.add_argument('--timeout',type=float,default=3600)
    p.add_argument('--workers',type=int,default=4)
    args=p.parse_args()
    if args.interval<3 or args.timeout<10 or not 1<=args.workers<=5:
        p.error('Use interval >=3s, timeout >=10s and 1-5 monitoring workers')
    data=json.loads((args.runtime_dir/'provision_results.json').read_text())
    base=data['target'];pending=[r for r in data['teams'] if r.get('job_id')]
    if not pending:raise SystemExit('No sandbox jobs in report; run provision_test_teams.py --mode sandbox first')
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(lambda r:watch(r,base,args.runtime_dir,args.interval,args.timeout), pending))
    with (args.runtime_dir/'sandbox_results.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['team','job_id','status','bot_score','opponent_score','seconds','error'],extrasaction='ignore')
        w.writeheader();w.writerows(rows)
    print('Saved',args.runtime_dir/'sandbox_results.csv')
    print('Outcomes:',{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})})

if __name__=='__main__':main()
