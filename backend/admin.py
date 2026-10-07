"""Authenticated organizer Control Room API."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue
from pathlib import Path

from backend.services.queueing import QUEUE_PRIORITY, redis_connection
from backend.services.storage import store
from backend.services.blob_storage import objects
from backend.services.tournament_state import initial_state

router = APIRouter(prefix="/api/admin", tags=["organizer"])
SESSION_COOKIE = "arena_admin"
_latencies: deque[float] = deque(maxlen=2000)
_request_count = 0
_error_count = 0


def record_request(seconds: float, status_code: int):
    global _request_count, _error_count
    _request_count += 1
    _error_count += status_code >= 500
    _latencies.append(seconds)


def _password_matches(password: str, encoded: str) -> bool:
    try:
        kind, rounds, salt, expected = encoded.split("$", 3)
        if kind != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _sign(payload: str) -> str:
    secret = os.getenv("ADMIN_SESSION_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(503, "Organizer authentication is not configured.")
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def require_admin(request: Request, arena_admin: str | None = Cookie(default=None)):
    if not arena_admin:
        raise HTTPException(401, "Organizer login required.")
    try:
        payload, signature = arena_admin.rsplit(".", 1)
        secret = os.getenv("ADMIN_SESSION_SECRET", "")
        if len(secret) < 32 or not hmac.compare_digest(signature, hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()):
            raise ValueError
        issued_text,csrf_token=payload.split(".",1)
        issued = int(issued_text)
        if issued > int(time.time()) or time.time() - issued > int(os.getenv("ADMIN_SESSION_SECONDS", "28800")):
            raise ValueError
        if request.method not in ("GET","HEAD","OPTIONS") and not hmac.compare_digest(request.headers.get("x-admin-csrf", ""),csrf_token):
            raise HTTPException(403,"Organizer request token is missing or invalid.")
    except (ValueError, AttributeError):
        raise HTTPException(401, "Organizer session expired.")
    return csrf_token


class LoginPayload(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class EventPayload(BaseModel):
    mode: str
    uploadsEnabled: bool | None = None
    sandboxEnabled: bool | None = None
    officialEnabled: bool | None = None
    tournamentEnabled: bool | None = None


class ActionPayload(BaseModel):
    confirmation: str


@router.post("/login")
def login(body: LoginPayload, response: Response):
    encoded = os.getenv("ADMIN_PASSWORD_HASH", "")
    if not encoded or not _password_matches(body.password, encoded):
        store.record_audit("login_failed", metadata={"source": "control_room"})
        raise HTTPException(401, "Invalid organizer credentials.")
    csrf_token=secrets.token_urlsafe(24)
    response.set_cookie(SESSION_COOKIE, _sign(f"{int(time.time())}.{csrf_token}"), httponly=True,
                        secure=os.getenv("APP_ENV", "development").lower() in ("production", "prod"),
                        samesite="none" if os.getenv("APP_ENV", "development").lower() in ("production", "prod") else "lax",
                        max_age=int(os.getenv("ADMIN_SESSION_SECONDS", "28800")), path="/")
    store.record_audit("login", metadata={"source": "control_room"})
    return {"authenticated": True,"csrfToken":csrf_token}


@router.get("/session")
def session_status(csrf_token=Depends(require_admin)):
    return {"authenticated": True,"csrfToken":csrf_token}


@router.post("/logout")
def logout(response: Response, _=Depends(require_admin)):
    response.delete_cookie(SESSION_COOKIE, path="/")
    store.record_audit("logout")
    return {"authenticated": False}


def _queue_status():
    queues = {}
    try:
        connection = redis_connection()
        paused = connection.smembers("arena:paused_queues")
    except Exception:
        return {name:{"queued":0,"running":0,"oldestWaitSeconds":None,"paused":False,"available":False} for name in QUEUE_PRIORITY}
    for name in QUEUE_PRIORITY:
        queue = Queue(name, connection=connection)
        waiting = queue.get_job_ids()
        queues[name] = {"queued": len(waiting), "running": 0, "oldestWaitSeconds": None,"available":True,
                        "paused": name.encode() in paused or name in paused}
        if waiting:
            job = store.get_job(waiting[0])
            if job and job.get("createdAt"):
                created = datetime.fromisoformat(job["createdAt"])
                if created.tzinfo is None: created = created.replace(tzinfo=timezone.utc)
                queues[name]["oldestWaitSeconds"] = max(0, int((datetime.now(timezone.utc) - created).total_seconds()))
    for job in store.list_admin_jobs(status="running", limit=1000):
        queues.setdefault(job["queue"], {"queued": 0, "running": 0, "oldestWaitSeconds": None, "paused": False})["running"] += 1
    return queues


def _durations(job: dict) -> dict:
    try:
        created=datetime.fromisoformat(job["createdAt"])
        started=datetime.fromisoformat(job["startedAt"]) if job.get("startedAt") else None
        completed=datetime.fromisoformat(job["completedAt"]) if job.get("completedAt") else None
        created=created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created.astimezone(timezone.utc)
        started=(started.replace(tzinfo=timezone.utc) if started and started.tzinfo is None else started.astimezone(timezone.utc) if started else None)
        completed=(completed.replace(tzinfo=timezone.utc) if completed and completed.tzinfo is None else completed.astimezone(timezone.utc) if completed else None)
        now=datetime.now(timezone.utc)
        return {**job,"queueWaitSeconds":max(0,round(((started or now)-created).total_seconds(),2)),
                "runtimeSeconds":round(((completed or now)-started).total_seconds(),2) if started else None}
    except (ValueError,TypeError,KeyError):return job


def _dependency_health():
    checks = {}
    for name, probe in (("postgres", store.ping), ("redis", lambda: bool(redis_connection().ping())), ("storage", __import__("backend.services.blob_storage", fromlist=["objects"]).objects.healthcheck)):
        try:
            probe(); checks[name] = "healthy"
        except Exception:
            checks[name] = "offline"
    return checks


@router.get("/metrics")
def metrics(_=Depends(require_admin)):
    base = store.admin_metrics()
    contestants = store.contestant_metrics()
    live_contestants = [row for row in contestants if not row.get("isRehearsal")]
    workers = store.worker_metrics(int(os.getenv("WORKER_HEARTBEAT_TIMEOUT", "30")))
    queues = _queue_status()
    health = _dependency_health()
    statuses = [v for v in health.values()]
    infra_failure=base.get("infrastructureFailureRate",0)
    samples = sorted(_latencies)
    p95 = samples[min(len(samples)-1, int(len(samples)*.95))] if samples else None
    api_p95_ms=p95*1000 if p95 is not None else 0
    if any(v == "offline" for v in statuses) or any(not q.get("available",True) for q in queues.values()) or workers["offline"] == workers["total"] and (workers["total"] or int(os.getenv("SIMULATION_WORKERS","2"))>0) or infra_failure >= float(os.getenv("FAILURE_RATE_CRITICAL_THRESHOLD","0.30")) or api_p95_ms >= float(os.getenv("API_P95_CRITICAL_MS","5000")):
        system = "CRITICAL"
    elif workers["offline"] or infra_failure >= float(os.getenv("FAILURE_RATE_DEGRADED_THRESHOLD","0.10")) or api_p95_ms >= float(os.getenv("API_P95_DEGRADED_MS","1000")) or any(q["oldestWaitSeconds"] and q["oldestWaitSeconds"] > int(os.getenv("QUEUE_DEGRADED_SECONDS", "300")) for q in queues.values()):
        system = "DEGRADED"
    else:
        system = "HEALTHY"
    total_jobs = sum(base.get(k, 0) for k in ("completed", "failed"))
    base.update({"contestants": len(live_contestants), "submissions": sum(c["submissionCount"] for c in live_contestants),
                 "officialTeams": sum(c["officialStatus"] in ("queued", "running", "evaluated") for c in live_contestants),
                 "evaluatedTeams": sum(c["officialStatus"] == "evaluated" for c in live_contestants),
                 "workers": workers, "queues": queues, "health": health, "systemStatus": system,
                 "failureRate": round(base.get("failed", 0) / total_jobs, 4) if total_jobs else 0,
                 "api": {"requests": _request_count, "serverErrors": _error_count,
                         "averageLatencyMs": round(sum(samples) * 1000 / len(samples), 2) if samples else None,
                         "p95LatencyMs": round(p95 * 1000, 2) if p95 is not None else None},
                 "event": store.event_config()})
    return base


@router.get("/jobs")
def jobs(job_type: str | None = None, status: str | None = None, team: str | None = None,
         error_type: str | None = None, created_after: datetime | None = None, created_before: datetime | None = None,
         limit: int = 100, _=Depends(require_admin)):
    return {"jobs": [_durations(job) for job in store.list_admin_jobs(job_type=job_type, status=status, team=team, error_type=error_type, created_after=created_after, created_before=created_before, limit=max(1, min(limit, 500)))]}


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, _=Depends(require_admin)):
    job = store.get_job(job_id)
    if not job: raise HTTPException(404, "Job not found.")
    return _durations(job)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation != "RETRY": raise HTTPException(400, "Type RETRY to confirm.")
    job = store.get_job(job_id)
    if not job or job["status"] != "failed": raise HTTPException(409, "Only failed jobs can be retried.")
    infrastructure={"ENGINE_FAILURE","WORKER_FAILURE","DATABASE_FAILURE","REDIS_FAILURE","STORAGE_FAILURE","INFRASTRUCTURE_TIMEOUT","infrastructure"}
    if job.get("errorKind") not in infrastructure: raise HTTPException(409, "Only classified infrastructure failures can be retried.")
    payload=store.job_payload(job_id);retry_count=int(payload.get("_adminRetryCount",0));max_retries=int(os.getenv("MAX_INFRASTRUCTURE_RETRIES","2"))
    if retry_count>=max_retries:raise HTTPException(409,"Configured infrastructure retry limit has been reached.")
    payload["_adminRetryCount"]=retry_count+1
    new_job = store.create_job(job["team"], job["type"], submission_id=job.get("submissionId"), opponent=job.get("opponent"), seed=job.get("seed"), payload=payload, max_attempts=max_retries)
    try:
        from backend.services.queueing import enqueue
        enqueue(new_job)
    except Exception as exc:
        store.fail_job(new_job["id"], f"Queue transport unavailable: {exc}", "infrastructure")
        raise HTTPException(503, "Queue unavailable.") from exc
    store.record_audit("job_retry", job_id, {"newJobId": new_job["id"],"retryCount":retry_count+1})
    return new_job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="CANCEL": raise HTTPException(400,"Type CANCEL to confirm.")
    job=store.get_job(job_id)
    if not job or job["status"]!="queued":raise HTTPException(409,"Only queued jobs can be cancelled safely.")
    try:
        from rq.job import Job
        queued=Job.fetch(job_id,connection=redis_connection())
        queued.cancel()
    except Exception as exc:
        raise HTTPException(503,"Could not remove this job from the queue.") from exc
    if not store.cancel_job(job_id):raise HTTPException(409,"Job has already started.")
    store.record_audit("job_cancel",job_id)
    return {"id":job_id,"status":"cancelled"}


@router.post("/queues/{queue_name}/{action}")
def queue_control(queue_name: str, action: str, body: ActionPayload, _=Depends(require_admin)):
    if queue_name not in QUEUE_PRIORITY or action not in ("pause", "resume"): raise HTTPException(404, "Unknown queue action.")
    required = "PAUSE" if action == "pause" else "RESUME"
    if body.confirmation != required: raise HTTPException(400, f"Type {required} to confirm.")
    connection: Redis = redis_connection()
    if action == "pause": connection.sadd("arena:paused_queues", queue_name)
    else: connection.srem("arena:paused_queues", queue_name)
    store.record_audit(f"queue_{action}", queue_name)
    return {"queue": queue_name, "paused": action == "pause"}


@router.get("/contestants")
def contestants(_=Depends(require_admin)):
    return {"contestants": store.contestant_metrics()}


@router.get("/contestants/{username}")
def contestant(username: str, _=Depends(require_admin)):
    detail = store.contestant_detail(username)
    if not detail: raise HTTPException(404, "Contestant not found.")
    # Deliberately omit source and object storage keys.
    for submission in detail["submissions"]:
        submission.pop("object_key", None); submission.pop("file_path", None)
    for key in ("currentSubmission","activeSubmission"):
        item=detail.get("summary",{}).get(key)
        if item:item.pop("object_key",None);item.pop("file_path",None)
    return detail


@router.get("/failures")
def failures(_=Depends(require_admin)):
    return {"failures": store.failure_summary(), "jobs": store.list_admin_jobs(status="failed", limit=200)}


@router.get("/event")
def event_config(_=Depends(require_admin)):
    return store.event_config()


@router.put("/event")
def update_event(body: EventPayload, _=Depends(require_admin)):
    config = store.set_event_config(body.mode, uploads_enabled=body.uploadsEnabled, sandbox_enabled=body.sandboxEnabled, official_enabled=body.officialEnabled, tournament_enabled=body.tournamentEnabled)
    store.record_audit("event_mode_change", body.mode, config)
    return config


@router.get("/audit")
def audit(_=Depends(require_admin)):
    return {"actions": store.audit_history()}


@router.get("/tournament")
def tournament_status(_=Depends(require_admin)):
    return store.get_tournament_state(initial_state())


@router.post("/tournament/qualifiers")
def load_qualifiers(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="LOAD QUALIFIERS":raise HTTPException(400,"Type LOAD QUALIFIERS to confirm.")
    state=store.get_tournament_state(initial_state())
    if state.get("status") in ("starting","round_running","next_round","final"):raise HTTPException(409,"Tournament is active.")
    from backend.services.scoring import load_scoring_config
    limit=int(load_scoring_config().get("qualifier_count",16))
    qualifiers=[entry["team"] for entry in store.leaderboard()[:limit]]
    if len(qualifiers)<2:raise HTTPException(409,"At least two evaluated teams are required to load qualifiers.")
    state["selectedQualifiers"]=qualifiers;state["registeredPlayers"]=qualifiers;state["playersCount"]=len(qualifiers)
    state["message"]=f"Top {len(qualifiers)} evaluated teams loaded as tournament qualifiers."
    store.save_tournament_state(state);store.record_audit("tournament_qualifiers_loaded",str(len(qualifiers)),{"teams":qualifiers})
    return {"qualifiers":qualifiers}


@router.post("/tournament/start")
def start_tournament(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="START TOURNAMENT":raise HTTPException(400,"Type START TOURNAMENT to confirm.")
    if not store.event_config()["tournamentEnabled"]:raise HTTPException(423,"Enable tournament mode before launching the tournament.")
    state=store.get_tournament_state(initial_state())
    if state.get("status") in ("starting","round_running","next_round","final"):raise HTTPException(409,"Tournament is already active.")
    participants=state.get("selectedQualifiers") or state.get("registeredPlayers") or [row["team"] for row in store.leaderboard()]
    if len(participants)<2:raise HTTPException(409,"At least two teams are required.")
    missing=[name for name in participants if not any(sub.get("is_active") for sub in store.list_submissions(name))]
    if missing:raise HTTPException(409,f"Teams without active versions: {', '.join(missing[:10])}")
    state.update({"status":"starting","isLive":True,"message":"Tournament queued.","playersCount":len(participants),"registeredPlayers":participants,"totalRoundsEstimate":math.ceil(math.log2(len(participants))),"currentRound":0,"currentMatches":[],"roundsHistory":[],"byes":[],"eliminatedPlayers":[],"allMatches":[],"champion":None,"finalScore":None,"error":None})
    store.save_tournament_state(state)
    job=store.create_job(None,"tournament",payload={"participants":participants})
    try:
        from backend.services.queueing import enqueue
        enqueue(job)
    except Exception as exc:
        store.fail_job(job["id"],f"Queue transport unavailable: {exc}","REDIS_FAILURE")
        state.update({"status":"error","isLive":False,"error":"Tournament queue unavailable.","message":"Tournament could not be queued."})
        store.save_tournament_state(state)
        raise HTTPException(503,"Tournament queue unavailable.") from exc
    store.record_audit("tournament_start",job["id"],{"participants":len(participants)})
    return {"job":job,"status":"queued","participants":participants}


@router.post("/tournament/reset")
def reset_tournament(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="RESET TOURNAMENT":raise HTTPException(400,"Type RESET TOURNAMENT to confirm.")
    state=store.get_tournament_state(initial_state())
    if state.get("status") in ("starting","round_running","next_round","final"):raise HTTPException(409,"Cannot reset an active tournament.")
    store.save_tournament_state(initial_state())
    store.record_audit("tournament_reset")
    return {"status":"registration","message":"Tournament state reset."}


@router.post("/rehearsal/seed")
def seed_rehearsal(body: dict, _=Depends(require_admin)):
    count=int(body.get("count",100))
    if count<2 or count>100: raise HTTPException(400,"Rehearsal size must be between 2 and 100 teams.")
    source=(Path(__file__).resolve().parents[1]/"contestant_starter"/"agent.py").read_bytes()
    created=[]
    try:
        for index in range(1,count+1):
            name=f"rehearsal_{index:03d}"
            key=f"rehearsal/{name}/agent.py"
            objects.put_bytes(key,source,"text/x-python")
            created.append(store.create_submission(name,key,valid=True,rehearsal=True))
    except Exception:
        raise HTTPException(500,"Rehearsal population failed; use reset before retrying.")
    store.record_audit("rehearsal_seed",str(count),{"teams":count})
    return {"created":len(created),"teamPrefix":"rehearsal_","isolatedFromLeaderboard":True}


@router.post("/rehearsal/reset")
def reset_rehearsal(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="RESET REHEARSAL": raise HTTPException(400,"Type RESET REHEARSAL to confirm.")
    if store.rehearsal_jobs(): raise HTTPException(409,"Wait for rehearsal jobs to finish before resetting rehearsal data.")
    count=store.reset_rehearsal_data()
    objects.delete_prefix("rehearsal/")
    store.record_audit("rehearsal_reset",metadata={"teamsRemoved":count})
    return {"removedTeams":count}


@router.post("/rehearsal/queue")
def queue_rehearsal(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="QUEUE REHEARSAL":raise HTTPException(400,"Type QUEUE REHEARSAL to confirm.")
    if os.getenv("APP_ENV","development").lower() not in ("development","dev","local","staging","test") or os.getenv("LOAD_TEST_FAKE_SIMULATION")!="1":
        raise HTTPException(409,"Rehearsal job surge requires fake simulation in a non-production environment.")
    from backend.services.queueing import enqueue
    teams=[row["team"] for row in store.contestant_metrics() if row.get("isRehearsal")]
    queued=0
    for team in teams:
        submissions=store.list_submissions(team)
        if not submissions:continue
        job=store.create_job(team,"sandbox",submission_id=submissions[0]["id"],opponent="starter_crop",seed=20261007)
        try:enqueue(job);queued+=1
        except Exception as exc:store.fail_job(job["id"],str(exc),"REDIS_FAILURE")
    store.record_audit("rehearsal_queue",str(queued),{"jobsQueued":queued,"fakeSimulation":True})
    return {"queued":queued,"totalTeams":len(teams),"fakeSimulation":True}
