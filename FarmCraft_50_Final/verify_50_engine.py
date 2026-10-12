"""Run one real local Kaggriculture game per supplied bot before live upload."""

import concurrent.futures
import hashlib
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
OPPONENT = REPO / "NITW_Farm_AI_Challenge_v1/examples/starter_agent.py"
SEED = 20261013


def verify(row):
    name = row["team"]
    source = ROOT / "bots" / name / "main.py"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != row["sha256"]:
        raise RuntimeError(f"{name}: manifest hash mismatch")
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(REPO / "run_match.py"), "--agent1", str(source),
         "--agent2", str(OPPONENT), "--seed", str(SEED)],
        cwd=REPO, text=True, capture_output=True, timeout=120, check=False,
    )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload = {"error": result.stderr[-300:] or "No JSON result"}
    return {
        "team": name,
        "family": row["family"],
        "sha256": digest,
        "seconds": round(time.monotonic() - start, 3),
        "exitCode": result.returncode,
        "result": payload,
        "passed": result.returncode == 0 and payload.get("p1Status") == "DONE"
        and payload.get("p2Status") == "DONE" and "error" not in payload,
    }


def main():
    rows = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if len(rows) != 50 or len({x["team"] for x in rows}) != 50:
        raise RuntimeError("Expected 50 distinct manifest teams")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(verify, rows))
    output = ROOT / "private-evidence"
    output.mkdir(exist_ok=True)
    (output / "engine-smoke.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    passed = sum(x["passed"] for x in results)
    print(f"Real engine smoke: {passed}/50 passed; details in private-evidence/engine-smoke.json")
    for item in results:
        if not item["passed"]:
            print(item["team"], item["result"])
    return 0 if passed == 50 else 1


if __name__ == "__main__":
    raise SystemExit(main())
