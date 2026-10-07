"""RQ entry points. No web request executes a simulation directly."""
from __future__ import annotations
import json,logging,os,socket,tempfile,time,random,hashlib
from pathlib import Path

from backend.services.blob_storage import objects
from backend.services.evaluation import EvaluationError,evaluate_source,evaluation_plan
from backend.services.sandbox import REPLAY_DIR,SandboxError,run_sandbox_source
from backend.services.storage import store
from backend.services.tournament_state import apply_progress,initial_state

log=logging.getLogger("neural_coliseum.jobs")

def _event(name: str,**fields): log.info(json.dumps({"event":name,**fields},default=str))

def _mark_tournament_failed(message: str):
    state=store.get_tournament_state(initial_state())
    state.update({"status":"error","isLive":False,"error":message[:1000],"message":"Tournament job failed. Organizer review is required."})
    store.save_tournament_state(state)

def _source(submission_id: int) -> tuple[dict,str]:
    submission=store.get_submission(submission_id)
    if not submission:raise RuntimeError("Submission no longer exists.")
    return submission,objects.get_bytes(submission["object_key"]).decode("utf-8")

def _fake(job: dict) -> dict:
    if os.getenv("APP_ENV","development").lower() not in ("development","dev","local","staging","test"):
        raise RuntimeError("LOAD_TEST_FAKE_SIMULATION is forbidden in production.")
    rng=random.Random(int(hashlib.sha256(job["id"].encode()).hexdigest()[:8],16))
    low=float(os.getenv("FAKE_SIMULATION_MIN_SECONDS","2"));high=float(os.getenv("FAKE_SIMULATION_MAX_SECONDS","8"))
    time.sleep(rng.uniform(low, max(low,high)))
    if job["type"]=="sandbox":return {"status":"success","winner":"bot","botFinalMoney":4200,"opponentFinalMoney":3900,"runtimeSeconds":0.05,"seed":job["seed"],"opponent":job["opponent"],"error":None,"replayId":None,"analytics":{}}
    if job["type"]=="official":return {"status":"complete","rating":4100,"winRate":62.5,"averageFinalMoney":4100,"averageMoneyDifferential":200,"wins":5,"ties":0,"games":8}
    return {"status":"complete","champion":{"username":"load-test-champion"}}

def _run_sandbox(job: dict) -> dict:
    submission,source=_source(job["submissionId"])
    result=run_sandbox_source(source,job["opponent"],int(job["seed"]),trusted_local=os.getenv("NEURAL_COLISEUM_TRUSTED_LOCAL")=="1")
    replay_id=result.get("replayId")
    if replay_id:
        path=REPLAY_DIR/f"{replay_id}.json"
        if path.is_file():objects.put_bytes(f"replays/{replay_id}.json",path.read_bytes(),"application/json")
    store.record_sandbox(submission["id"],result);return result

def _failure_category(error: Exception, *, contestant: bool=False) -> str:
    message=str(error).lower()
    if contestant:
        if "syntaxerror" in message or "invalid syntax" in message:return "CONTESTANT_SYNTAX_ERROR"
        if "timeout" in message or "exceeded" in message:return "CONTESTANT_TIMEOUT"
        if "invalid action" in message or "illegal action" in message:return "INVALID_ACTION"
        return "CONTESTANT_RUNTIME_ERROR"
    if isinstance(error,TimeoutError) or "timeout" in message or "exceeded" in message:return "INFRASTRUCTURE_TIMEOUT"
    if "database" in message or "postgres" in message:return "DATABASE_FAILURE"
    if "redis" in message or "queue" in message:return "REDIS_FAILURE"
    if "storage" in message or "s3" in message or "object" in message:return "STORAGE_FAILURE"
    if isinstance(error,SandboxError):return "ENGINE_FAILURE"
    return "WORKER_FAILURE"

def _run_official(job: dict) -> dict:
    submission,source=_source(job["submissionId"]);total=len(evaluation_plan())
    result=evaluate_source(source,trusted_local=os.getenv("NEURAL_COLISEUM_TRUSTED_LOCAL")=="1",progress=lambda done,_:store.update_job_progress(job["id"],done,total))
    store.record_evaluation(submission["id"],result);store.activate_submission(submission["username"],submission["id"]);return result

def _run_tournament(job: dict) -> dict:
    from tournament import run_tournament
    payload=store.job_payload(job["id"]); names=payload.get("participants") or [x["team"] for x in store.leaderboard()]
    with tempfile.TemporaryDirectory(prefix="neural-coliseum-tournament-") as root:
        participants=[]
        for name in names:
            active=next((x for x in store.list_submissions(name) if x["is_active"]),None)
            if not active:continue
            path=Path(root)/f"{len(participants)}.py";path.write_bytes(objects.get_bytes(active["object_key"]));participants.append({"username":name,"filePath":str(path)})
        if len(participants)<2:raise RuntimeError("At least two active submissions are required.")
        state=store.get_tournament_state(initial_state(names))
        def progress(event,data):
            nonlocal state
            state=apply_progress(state,event,data);store.save_tournament_state(state)
        return run_tournament(participants,seed=20260929,random_seed=42,on_progress=progress)

def execute_job(job_id: str):
    try:
        from rq import get_current_job
        rq_job=get_current_job()
        worker_id=rq_job.worker_name if rq_job and rq_job.worker_name else socket.gethostname()
    except Exception: worker_id=socket.gethostname()
    job=store.mark_job_running(job_id,worker_id)
    if not job:return None
    store.record_worker(worker_id,status="busy",current_job_id=job_id)
    started=time.perf_counter();_event("job_started",job_id=job_id,type=job["type"],team=job["team"],submission_id=job["submissionId"])
    try:
        result=_fake(job) if os.getenv("LOAD_TEST_FAKE_SIMULATION")=="1" else {"sandbox":_run_sandbox,"official":_run_official,"tournament":_run_tournament}[job["type"]](job)
        if os.getenv("LOAD_TEST_FAKE_SIMULATION")=="1":
            if job["type"]=="sandbox":store.record_sandbox(job["submissionId"],result)
            elif job["type"]=="official":store.record_evaluation(job["submissionId"],result);store.activate_submission(job["team"],job["submissionId"])
        if job["type"]=="sandbox" and result.get("contestantFailure"):
            failure=result["contestantFailure"].get("error") or "Contestant agent failed during the sandbox match."
            category=_failure_category(SandboxError(failure),contestant=True)
            store.fail_job(job_id,failure,category);store.record_worker(worker_id,status="idle");_event("job_failed",job_id=job_id,error_kind=category,runtime_seconds=round(time.perf_counter()-started,3));return result
        store.finish_job(job_id,result);store.record_worker(worker_id,status="idle");_event("job_completed",job_id=job_id,runtime_seconds=round(time.perf_counter()-started,3));return result
    except (SandboxError,EvaluationError) as exc:
        kind=_failure_category(exc);store.fail_job(job_id,str(exc),kind)
        if job["type"]=="tournament":_mark_tournament_failed(str(exc))
        store.record_worker(worker_id,status="idle");_event("job_failed",job_id=job_id,error_kind=kind,runtime_seconds=round(time.perf_counter()-started,3));raise
    except Exception as exc:
        kind=_failure_category(exc);store.fail_job(job_id,str(exc),kind)
        if job["type"]=="tournament":_mark_tournament_failed(str(exc))
        store.record_worker(worker_id,status="idle");_event("job_failed",job_id=job_id,error_kind=kind,runtime_seconds=round(time.perf_counter()-started,3));raise
