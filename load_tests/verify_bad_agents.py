"""Exercise intentionally bad bots through the isolated Docker match runner.

Run only on a local workstation with the evaluator image built. The outer
match timeout is configurable with MATCH_TIMEOUT_SECONDS.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from bad_agents import AGENTS
from backend.services.sandbox import SandboxError, run_sandbox_source

def main():
    outcomes={}
    for name,source in AGENTS.items():
        try:
            result=run_sandbox_source(source,"starter_crop",20261007,trusted_local=False)
            failure=result.get("contestantFailure")
            expected_bad=name!="valid"
            outcomes[name]={"ok":(bool(failure) if expected_bad else not failure),"status":result.get("status"),"contestantFailure":failure}
        except SandboxError as exc:
            outcomes[name]={"ok":name!="valid","status":"failed","error":str(exc)}
    print(json.dumps(outcomes,indent=2))
    failed=[name for name,outcome in outcomes.items() if not outcome["ok"]]
    if failed:raise SystemExit(f"Fixture failures: {', '.join(failed)}")

if __name__=="__main__":main()
