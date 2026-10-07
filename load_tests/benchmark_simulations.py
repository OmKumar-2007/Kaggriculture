"""Benchmark real games at bounded concurrency; writes JSON evidence."""
from __future__ import annotations
import argparse,concurrent.futures,json,statistics,time
from pathlib import Path
import sys,math
import psutil
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.services.sandbox import run_sandbox_source

SOURCE=(ROOT/"contestant_starter"/"agent.py").read_text(encoding="utf-8")
def one(index):
    started=time.perf_counter()
    try:run_sandbox_source(SOURCE,"starter_crop",20261000+index,trusted_local=True);return {"seconds":time.perf_counter()-started,"ok":True}
    except Exception as exc:return {"seconds":time.perf_counter()-started,"ok":False,"error":str(exc)}
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--levels",default="1,2,4,8");parser.add_argument("--games",type=int,default=8);parser.add_argument("--output",default="load_tests/real_benchmark.json");args=parser.parse_args();report={"machine":{"cpuLogical":psutil.cpu_count(),"memoryGb":round(psutil.virtual_memory().total/2**30,2)},"levels":[]}
    for level in [int(x) for x in args.levels.split(",")]:
        cpu=[];before=psutil.Process().memory_info().rss;started=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=level) as pool:
            futures=[pool.submit(one,i) for i in range(args.games)]
            while any(not f.done() for f in futures):cpu.append(psutil.cpu_percent(interval=.2))
            rows=[f.result() for f in futures]
        times=sorted(x["seconds"] for x in rows);wall=time.perf_counter()-started;p95_index=max(0,math.ceil(len(times)*.95)-1)
        report["levels"].append({"concurrency":level,"games":len(rows),"wallSeconds":round(wall,3),"averageSeconds":round(statistics.mean(times),3),"p95Seconds":round(times[p95_index],3),"gamesPerSecond":round(len(rows)/wall,3) if wall else 0,"peakObservedCpuPercent":max(cpu or [0]),"memoryDeltaMb":round((psutil.Process().memory_info().rss-before)/2**20,2),"failures":sum(not x["ok"] for x in rows)})
    Path(args.output).write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
