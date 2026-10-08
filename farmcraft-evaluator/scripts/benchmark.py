"""Measure actual Docker match throughput on the evaluator laptop."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import psutil

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
sys.path.insert(0, str(PACKAGE / "app"))
sys.path.insert(0, str(ROOT))
from configuration import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", default="1,2,4,6,8")
    parser.add_argument("--games", type=int, default=8)
    args = parser.parse_args()
    if args.games < 1 or args.games > 100: raise SystemExit("--games must be 1..100")
    config = settings()
    for key in ("EVALUATOR_IMAGE", "EVALUATION_TIMEOUT_SECONDS", "EVALUATION_MEMORY_MB",
                "EVALUATION_CPU_LIMIT", "EVALUATION_PIDS_LIMIT"):
        if key in config: os.environ[key] = str(config[key])
    from backend.services.sandbox import _run_docker
    levels = [int(part.strip()) for part in args.levels.split(",")]
    if any(level < 1 or level > 16 for level in levels): raise SystemExit("Concurrency levels must be 1..16")
    source = ROOT / "NITW_Farm_AI_Challenge_v1" / "examples" / "starter_agent.py"
    opponent = ROOT / "NITW_Farm_AI_Challenge_v1" / "examples" / "random_agent.py"
    report = []
    with tempfile.TemporaryDirectory(prefix="farmcraft-benchmark-") as directory:
        root = Path(directory)
        def game(index: int):
            started = time.perf_counter()
            payload = _run_docker(source, opponent, 41021 + index, root / f"replay-{index}.json")
            return time.perf_counter()-started, payload
        for level in levels:
            samples, errors = [], []
            stop = threading.Event()
            cpu, ram = [], []
            def sample():
                while not stop.wait(.5):
                    cpu.append(psutil.cpu_percent(interval=None))
                    ram.append(psutil.virtual_memory().used)
            observer = threading.Thread(target=sample, daemon=True)
            observer.start()
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=level) as pool:
                futures = [pool.submit(game, level*1000 + index) for index in range(args.games)]
                for future in as_completed(futures):
                    try: samples.append(future.result()[0])
                    except Exception as exc: errors.append(f"{type(exc).__name__}: {exc}"[:300])
            elapsed = time.perf_counter()-started
            stop.set(); observer.join(timeout=2)
            ordered = sorted(samples)
            result = {"concurrency": level, "games": args.games, "completed": len(samples),
                      "failures": errors, "wallSeconds": round(elapsed, 2),
                      "meanSeconds": round(statistics.mean(samples), 2) if samples else None,
                      "p95Seconds": round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 2) if ordered else None,
                      "jobsPerMinute": round(len(samples)*60/elapsed, 2),
                      "peakCpuPercent": max(cpu, default=None),
                      "peakHostRamGiB": round(max(ram)/1024**3, 2) if ram else None}
            print(json.dumps(result), flush=True)
            report.append(result)
    output = PACKAGE / "benchmark.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {output}")


if __name__ == "__main__": main()
