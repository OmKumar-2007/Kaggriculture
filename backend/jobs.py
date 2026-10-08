"""RQ entry points. No web request executes a simulation directly."""
from __future__ import annotations
import json,logging,os,socket,tempfile,time,random,hashlib
from pathlib import Path

from backend.services.blob_storage import objects
from backend.services.evaluation import EvaluationError,ContestantEvaluationError,evaluate_source,evaluation_plan
from backend.services.sandbox import REPLAY_DIR,SandboxError,EvaluationCancelled,ACTIVE_JOB_ID,run_sandbox_source
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
    until=time.monotonic()+rng.uniform(low,max(low,high))
    from backend.services.queueing import redis_connection
    while time.monotonic()<until:
        if redis_connection().exists(f"arena:job:cancel:{job['id']}"):
            raise EvaluationCancelled("Evaluation cancelled by an organizer.")
        time.sleep(min(.25,max(0,until-time.monotonic())))
    if job["type"]=="sandbox":return {"status":"success","winner":"bot","botFinalMoney":4200,"opponentFinalMoney":3900,"runtimeSeconds":0.05,"seed":job["seed"],"opponent":job["opponent"],"error":None,"replayId":None,"analytics":{}}
    if job["type"]=="official":return {"status":"complete","rating":4100,"winRate":62.5,"averageFinalMoney":4100,"averageMoneyDifferential":200,"wins":5,"ties":0,"games":8}
    return {"status":"complete","champion":{"username":"load-test-champion"}}

def _run_sandbox(job: dict) -> dict:
    submission,source=_source(job["submissionId"])
    store.pipeline_event(job["id"],"submission","completed",f"Version {submission['version']} source loaded")
    store.pipeline_event(job["id"],"match","running",f"{job['opponent']} · seed {job['seed']}")
    result=run_sandbox_source(source,job["opponent"],int(job["seed"]),trusted_local=os.getenv("NEURAL_COLISEUM_TRUSTED_LOCAL")=="1")
    store.pipeline_event(job["id"],"match","completed",f"winner {result.get('winner')}")
    replay_id=result.get("replayId")
    if replay_id:
        path=REPLAY_DIR/f"{replay_id}.json"
        if path.is_file():objects.put_bytes(f"replays/{replay_id}.json",path.read_bytes(),"application/json")
    return result

def _failure_category(error: Exception, *, contestant: bool=False) -> str:
    contestant = contestant or isinstance(error, ContestantEvaluationError)
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
    store.pipeline_event(job["id"],"submission","completed",f"Version {submission['version']} source loaded")
    result=evaluate_source(source,trusted_local=os.getenv("NEURAL_COLISEUM_TRUSTED_LOCAL")=="1",
                           progress=lambda done,_:store.update_job_progress(job["id"],done,total),
                           on_stage=lambda stage,status,detail:store.pipeline_event(job["id"],stage,status,detail))
    return result

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
            store.pipeline_event(job["id"],"tournament", "running" if event not in ("TOURNAMENT_COMPLETE","TOURNAMENT_ERROR") else "completed", event)
        result=run_tournament(participants,seed=20260929,random_seed=42,on_progress=progress)
        if result.get("error"):
            raise RuntimeError(f"Tournament aborted: {result['error']}")
        return result

def execute_job(job_id: str):
    try:
        from rq import get_current_job
        rq_job=get_current_job()
        worker_id=rq_job.worker_name.split("~",1)[0] if rq_job and rq_job.worker_name else socket.gethostname()
    except Exception: worker_id=socket.gethostname()
    job=store.mark_job_running(job_id,worker_id)
    if not job:return None
    context_token=ACTIVE_JOB_ID.set(job_id)
    store.record_worker(worker_id,status="busy",current_job_id=job_id)
    started=time.perf_counter();_event("job_started",job_id=job_id,type=job["type"],team=job["team"],submission_id=job["submissionId"])
    try:
        store.pipeline_event(job_id,"execution","running",job["type"])
        result=_fake(job) if os.getenv("LOAD_TEST_FAKE_SIMULATION")=="1" else {"sandbox":_run_sandbox,"official":_run_official,"tournament":_run_tournament}[job["type"]](job)
        if job["type"]=="sandbox" and result.get("contestantFailure"):
            failure=result["contestantFailure"].get("error") or "Contestant agent failed during the sandbox match."
            category=_failure_category(SandboxError(failure),contestant=True)
            committed=store.commit_job_result(job_id,result,error=failure,error_kind=category)
            store.record_worker(worker_id,status="idle")
            _event("job_failed" if committed else "job_result_discarded",job_id=job_id,error_kind=category,runtime_seconds=round(time.perf_counter()-started,3))
            return result if committed else None
        committed=store.commit_job_result(job_id,result)
        store.record_worker(worker_id,status="idle")
        _event("job_completed" if committed else "job_result_discarded",job_id=job_id,runtime_seconds=round(time.perf_counter()-started,3))
        return result if committed else None
    except EvaluationCancelled:
        store.pipeline_event(job_id,"execution","cancelled","Organizer cancellation acknowledged")
        if job["type"]=="tournament":_mark_tournament_failed("Tournament stopped by organizer.")
        store.record_worker(worker_id,status="idle")
        _event("job_cancelled",job_id=job_id,runtime_seconds=round(time.perf_counter()-started,3))
        return None
    except (SandboxError,EvaluationError) as exc:
        kind=_failure_category(exc)
        if not isinstance(exc,ContestantEvaluationError) and store.requeue_running_job(job_id):
            store.record_worker(worker_id,status="idle")
            _event("job_retry_queued",job_id=job_id,error_kind=kind)
            raise
        store.fail_job(job_id,str(exc),kind)
        if job["type"]=="tournament":_mark_tournament_failed(str(exc))
        store.record_worker(worker_id,status="idle");_event("job_failed",job_id=job_id,error_kind=kind,runtime_seconds=round(time.perf_counter()-started,3));raise
    except Exception as exc:
        kind=_failure_category(exc)
        if store.requeue_running_job(job_id):
            store.record_worker(worker_id,status="idle")
            _event("job_retry_queued",job_id=job_id,error_kind=kind)
            raise
        store.fail_job(job_id,str(exc),kind)
        if job["type"]=="tournament":_mark_tournament_failed(str(exc))
        store.record_worker(worker_id,status="idle");_event("job_failed",job_id=job_id,error_kind=kind,runtime_seconds=round(time.perf_counter()-started,3));raise
    finally:
        ACTIVE_JOB_ID.reset(context_token)
