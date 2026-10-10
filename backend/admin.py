"""Authenticated organizer Control Room API."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import time
import threading
from collections import deque
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue
from pathlib import Path

from backend.services.queueing import QUEUE_PRIORITY, redis_connection, postgres_queue
from backend.services.storage import store
from backend.services.blob_storage import objects
from backend.services.tournament_state import initial_state
from backend.services.bracket import opening_bracket
from backend.services.scoring import load_scoring_config
from backend.services.participants import connected_devices, hash_access_code, team_sessions, revoke_session, revoke_all_sessions, postgres_sessions
from backend.services.host_telemetry import host_snapshot

router = APIRouter(prefix="/api/admin", tags=["organizer"])
SESSION_COOKIE = "arena_admin"
_latencies: deque[float] = deque(maxlen=2000)
_request_count = 0
_error_count = 0
_local_login_attempts: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def _login_attempts(key: str, *, failed: bool = False, clear: bool = False) -> int:
    """Prefer shared Redis throttling; preserve a process-local guard if Redis is down."""
    if postgres_sessions():
        if clear:
            store.clear_rate_limit(key)
            return 0
        return store.bump_rate_limit(key, 300) if failed else store.rate_limit_count(key)
    try:
        connection = redis_connection()
        if clear:
            connection.delete(key)
            return 0
        if failed:
            count = connection.incr(key)
            if count == 1:
                connection.expire(key, 300)
            return count
        return int(connection.get(key) or 0)
    except Exception:
        with _login_lock:
            recent = [at for at in _local_login_attempts.get(key, []) if time.time() - at < 300]
            if clear:
                _local_login_attempts.pop(key, None)
                return 0
            if failed:
                recent.append(time.time())
            _local_login_attempts[key] = recent
            return len(recent)


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
    registrationsEnabled: bool | None = None
    leaderboardVisible: bool | None = None
    submissionLimit: int | None = Field(default=None, ge=0, le=1000)
    submissionCooldownSeconds: int | None = Field(default=None, ge=0, le=86400)


class ActionPayload(BaseModel):
    confirmation: str
    reason: str = Field(default="Organizer action", max_length=500)

class TeamStatePayload(BaseModel):
    action: str
    reason: str = Field(default="Organizer action", max_length=500)

class WorkerCapacityPayload(BaseModel):
    capacity: int = Field(ge=1, le=8)
    confirmation: str

class AccessPayload(BaseModel):
    accessCode: str = Field(min_length=12, max_length=256)
    confirmation: str

class CompetitionSettingsPayload(BaseModel):
    qualifierCount: int = Field(ge=2,le=1000)
    registrationCapacity: int = Field(ge=2,le=1000)
    officialAttemptLimit: int = Field(ge=1,le=1)
    referenceCount: int = Field(ge=5,le=10)
    qualificationSeedCount: int = Field(ge=1,le=10)
    tieReplayLimit: int = Field(ge=0,le=20)

class ReferenceActionPayload(BaseModel):
    selected: bool | None = None
    enabled: bool | None = None
    archived: bool | None = None


@router.post("/login")
def login(body: LoginPayload, response: Response, request: Request):
    address = request.client.host if request.client else "unknown"
    throttle = "arena:admin:auth:" + hashlib.sha256(address.encode()).hexdigest()
    if _login_attempts(throttle) >= 8:
        raise HTTPException(429, "Too many organizer sign-in attempts. Try again in five minutes.")
    encoded = os.getenv("ADMIN_PASSWORD_HASH", "")
    if not encoded or not _password_matches(body.password, encoded):
        _login_attempts(throttle, failed=True)
        store.record_audit("login_failed", metadata={"source": "control_room"})
        raise HTTPException(401, "Invalid organizer credentials.")
    _login_attempts(throttle, clear=True)
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
    if postgres_queue():
        counts = store.admin_metrics()
        modes = store.remote_queue_modes()
        return {name: {"queued": counts["queues"][name],
                       "running": sum(job["queue"] == name for job in store.list_admin_jobs(status="running", limit=1000)),
                       "oldestWaitSeconds": counts["oldestQueuedSeconds"],
                       "paused": modes.get(name, False), "available": True} for name in QUEUE_PRIORITY}
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
    session_probe = store.ping if postgres_sessions() else lambda: bool(redis_connection().ping())
    session_name = "sessions" if postgres_sessions() else "redis"
    for name, probe in (("postgres", store.ping), (session_name, session_probe), ("storage", __import__("backend.services.blob_storage", fromlist=["objects"]).objects.healthcheck)):
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
    workers = (store.remote_worker_metrics() if postgres_queue() else
               store.worker_metrics(int(os.getenv("WORKER_HEARTBEAT_TIMEOUT", "30"))))
    queues = _queue_status()
    health = _dependency_health()
    try:
        presence = connected_devices()
    except Exception:
        presence = {"activeSessions": 0, "connectedTeams": 0, "recentlyDisconnected": 0,
                    "reconnections": 0, "averageLatencyMs": None}
    try:
        host = host_snapshot() if not postgres_sessions() else {"current": None, "alerts": []}
    except Exception:
        host = {"current": None, "alerts": []}
    statuses = [v for v in health.values()]
    infra_failure=base.get("infrastructureFailureRate",0)
    latest_alerts = {}
    for item in host.get("alerts", []):
        latest_alerts.setdefault(item.get("subsystem"), item)
    active_alerts = [item for item in latest_alerts.values() if item.get("active")]
    samples = sorted(_latencies)
    p95 = samples[min(len(samples)-1, int(len(samples)*.95))] if samples else None
    api_p95_ms=p95*1000 if p95 is not None else 0
    if any(item.get("severity") == "critical" for item in active_alerts) or any(v == "offline" for v in statuses) or any(not q.get("available",True) for q in queues.values()) or workers["offline"] == workers["total"] and (workers["total"] or int(os.getenv("SIMULATION_WORKERS","2"))>0) or infra_failure >= float(os.getenv("FAILURE_RATE_CRITICAL_THRESHOLD","0.30")) or api_p95_ms >= float(os.getenv("API_P95_CRITICAL_MS","5000")):
        system = "CRITICAL"
    elif active_alerts or workers["offline"] or infra_failure >= float(os.getenv("FAILURE_RATE_DEGRADED_THRESHOLD","0.10")) or api_p95_ms >= float(os.getenv("API_P95_DEGRADED_MS","1000")) or any(q["oldestWaitSeconds"] and q["oldestWaitSeconds"] > int(os.getenv("QUEUE_DEGRADED_SECONDS", "300")) for q in queues.values()):
        system = "DEGRADED"
    else:
        system = "HEALTHY"
    total_jobs = sum(base.get(k, 0) for k in ("completed", "failed", "timeout"))
    base.update({"contestants": len(live_contestants), "submissions": sum(c["submissionCount"] for c in live_contestants),
                 "officialTeams": sum(c["officialStatus"] in ("queued", "running", "evaluated") for c in live_contestants),
                 "evaluatedTeams": sum(c["officialStatus"] == "evaluated" for c in live_contestants),
                 "workers": workers, "queues": queues, "queueBackend": "postgres" if postgres_queue() else "redis",
                 "health": health, "systemStatus": system,
                 "host": host["current"], "alerts": host["alerts"][:10], "presence": presence,
                 "failureRate": round((base.get("failed", 0) + base.get("timeout", 0)) / total_jobs, 4) if total_jobs else 0,
                 "api": {"requests": _request_count, "serverErrors": _error_count,
                         "averageLatencyMs": round(sum(samples) * 1000 / len(samples), 2) if samples else None,
                         "p95LatencyMs": round(p95 * 1000, 2) if p95 is not None else None},
                 "event": store.event_config()})
    return base


@router.get("/telemetry")
def telemetry(_=Depends(require_admin)):
    return {"current": None, "history": [], "alerts": []} if postgres_sessions() else host_snapshot()


@router.get("/devices")
def devices(_=Depends(require_admin)):
    presence = connected_devices()
    contestants = {item["team"].casefold(): item for item in store.contestant_metrics()}
    for session in presence["sessions"]:
        team = contestants.get(session["team"].casefold(), {})
        session["submissionCount"] = team.get("submissionCount", 0)
        session["lastActivity"] = team.get("lastActivity")
        session["currentJob"] = next((job["id"] for job in store.list_jobs(session["team"], 5)
                                      if job["status"] in ("running", "queued")), None)
    return presence


@router.get("/jobs")
def jobs(job_type: str | None = None, status: str | None = None, team: str | None = None,
         error_type: str | None = None, created_after: datetime | None = None, created_before: datetime | None = None,
         limit: int = 100, _=Depends(require_admin)):
    rows = [_durations(job) for job in store.list_admin_jobs(job_type=job_type, status=status, team=team, error_type=error_type, created_after=created_after, created_before=created_before, limit=max(1, min(limit, 500)))]
    return {"jobs": _with_latest_stages(rows)}


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, _=Depends(require_admin)):
    job = store.get_job(job_id)
    if not job: raise HTTPException(404, "Job not found.")
    return {**_durations(job), "pipeline": store.pipeline_events(job_id)}

@router.get("/pipeline")
def pipeline(_=Depends(require_admin)):
    jobs = _with_latest_stages([_durations(job) for job in store.list_admin_jobs(limit=500)])
    counts = store.admin_metrics()
    return {"jobs": jobs, "observedAt": datetime.now(timezone.utc).isoformat(), "counts": {key: counts.get(key, 0) for key in
            ("queued", "running", "completed", "failed", "timeout", "cancelled")},
            "submissionsReceived": store.total_submissions(),
            "averageQueueWait": counts.get("averageQueueWait"),
            "averageRuntime": counts.get("averageJobRuntime"),
            "recentErrors": len([job for job in jobs if job["status"] in ("failed", "timeout")])}


def _with_latest_stages(jobs: list[dict]) -> list[dict]:
    latest = store.latest_pipeline_stages([job["id"] for job in jobs])
    for job in jobs:
        stage = latest.get(job["id"], {})
        job["currentStage"] = stage.get("stage", "queue" if job["status"] == "queued" else "untracked")
        job["stageStatus"] = stage.get("status", "waiting" if job["status"] == "queued" else "unknown")
    return jobs

@router.get("/jobs/{job_id}/logs", response_class=PlainTextResponse)
def job_logs(job_id: str, _=Depends(require_admin)):
    job = store.get_job(job_id)
    if not job: raise HTTPException(404, "Job not found.")
    lines = [f"FarmCraft evaluation {job_id}", f"Team: {job['team'] or 'system'}",
             f"Type: {job['type']}", f"Status: {job['status']}"]
    lines += [f"{event['at']}  {event['stage']}  {event['status']}  {event['detail'] or ''}"
              for event in store.pipeline_events(job_id)]
    if job.get("error"):
        lines.append("Error: " + job["error"][:4000].replace("\x00", ""))
    return PlainTextResponse("\n".join(lines)[:16000], headers={"Content-Disposition": f'attachment; filename="evaluation-{job_id}.txt"'})


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation != "RETRY": raise HTTPException(400, "Type RETRY to confirm.")
    job = store.get_job(job_id)
    if not job or job["status"] not in ("failed", "timeout"): raise HTTPException(409, "Only failed or timed-out jobs can be retried.")
    max_retries=int(os.getenv("MAX_INFRASTRUCTURE_RETRIES","2"))
    new_job=store.retry_failed_infrastructure_job(job_id,max_retries)
    if not new_job:raise HTTPException(409,"Only classified infrastructure failures within the retry limit can be retried.")
    try:
        from backend.services.queueing import enqueue
        enqueue(new_job)
    except Exception as exc:
        store.fail_job(new_job["id"], f"Queue transport unavailable: {exc}", "infrastructure")
        raise HTTPException(503, "Queue unavailable.") from exc
    store.record_audit("job_retry", job_id, {"jobId": job_id,"retryCount":new_job["retryCount"]})
    return new_job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="CANCEL": raise HTTPException(400,"Type CANCEL to confirm.")
    outcome=store.request_job_cancel(job_id,body.reason)
    if not outcome:raise HTTPException(404,"Job not found.")
    if outcome["previousStatus"] in ("queued","running"):
        if not postgres_queue():
            connection=redis_connection()
            connection.setex(f"arena:job:cancel:{job_id}",3600,"1")
            if outcome["previousStatus"] == "queued":
                try:
                    from rq.job import Job
                    Job.fetch(job_id,connection=connection).cancel()
                except Exception:
                    pass  # Durable DB state prevents a later worker claim.
        store.record_audit("job_cancel",job_id,{"previous":outcome["previousStatus"],"new":"cancelled","reason":body.reason})
    elif outcome["status"]!="cancelled":
        raise HTTPException(409,"This job has already finished.")
    return {**outcome,"stopPending":outcome["previousStatus"]=="running"}

@router.post("/jobs/{job_id}/reevaluate")
def reevaluate_job(job_id: str, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation != "REEVALUATE": raise HTTPException(400,"Type REEVALUATE to confirm.")
    original=store.get_job(job_id)
    if not original or original["type"] not in ("official","sandbox") or not original.get("submissionId"):
        raise HTTPException(409,"Choose a saved official or sandbox submission.")
    if original["status"] in ("queued","running"):
        raise HTTPException(409,"Wait for the original job to finish.")
    if original["type"]=="official":
        raise HTTPException(409,"Official Round 1 submissions cannot be re-evaluated as a new job. Retry infrastructure failures on the same frozen job.")
    payload=store.job_payload(job_id) if original["type"]=="official" else {}
    new=store.create_job(original["team"],original["type"],submission_id=original["submissionId"],
                         opponent=original.get("opponent"),seed=original.get("seed"),
                         payload={**payload,"reevaluationOf":job_id,"reason":body.reason},progress_total=original.get("progressTotal"))
    from backend.services.queueing import enqueue
    try:enqueue(new)
    except Exception as exc:
        store.fail_job(new["id"],"Queue unavailable.","REDIS_FAILURE")
        raise HTTPException(503,"Queue unavailable.") from exc
    store.record_audit("job_reevaluate",job_id,{"newJobId":new["id"],"reason":body.reason})
    store.pipeline_event(job_id,"reevaluation","completed",f"New job {new['id']}")
    store.pipeline_event(new["id"],"reevaluation","waiting",f"Source job {job_id}")
    return new

@router.post("/jobs/emergency-stop")
def emergency_stop(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation != "STOP ALL EVALUATIONS":
        raise HTTPException(400,"Type STOP ALL EVALUATIONS to confirm.")
    connection=None if postgres_queue() else redis_connection()
    if postgres_queue():
        for name in QUEUE_PRIORITY: store.set_remote_queue_mode(name, True)
    else: connection.sadd("arena:paused_queues",*QUEUE_PRIORITY)
    active=store.list_admin_jobs(status="running",limit=1000)
    stopped=[]
    for job in active:
        outcome=store.request_job_cancel(job["id"],body.reason)
        if outcome and outcome["previousStatus"]=="running":
            if connection: connection.setex(f"arena:job:cancel:{job['id']}",3600,"1")
            stopped.append(job["id"])
    store.record_audit("emergency_stop","all",{"jobs":stopped,"reason":body.reason})
    return {"dispatchPaused":True,"cancellationRequested":stopped}


@router.post("/queues/{queue_name}/{action}")
def queue_control(queue_name: str, action: str, body: ActionPayload, _=Depends(require_admin)):
    if queue_name not in QUEUE_PRIORITY or action not in ("pause", "resume"): raise HTTPException(404, "Unknown queue action.")
    required = "PAUSE" if action == "pause" else "RESUME"
    if body.confirmation != required: raise HTTPException(400, f"Type {required} to confirm.")
    if postgres_queue():
        store.set_remote_queue_mode(queue_name, action == "pause")
    else:
        connection: Redis = redis_connection()
        if action == "pause": connection.sadd("arena:paused_queues", queue_name)
        else: connection.srem("arena:paused_queues", queue_name)
    store.record_audit(f"queue_{action}", queue_name)
    return {"queue": queue_name, "paused": action == "pause"}

@router.put("/workers/capacity")
def worker_capacity(body: WorkerCapacityPayload, _=Depends(require_admin)):
    if postgres_queue():raise HTTPException(409,"Use Remote Workers capacity controls with the PostgreSQL queue.")
    if body.confirmation != "SET CAPACITY":raise HTTPException(400,"Type SET CAPACITY to confirm.")
    available=store.worker_metrics()["total"]
    if body.capacity > available:
        raise HTTPException(409,f"Only {available} worker processes are registered. Restart the host worker to add more.")
    connection=redis_connection()
    previous=connection.get("arena:worker:active_capacity")
    connection.set("arena:worker:active_capacity",body.capacity)
    store.record_audit("worker_capacity","all",{"previous":int(previous) if previous else None,"new":body.capacity})
    return {"capacity":body.capacity,"registered":available}

@router.post("/workers/{worker_id}/{action}")
def worker_action(worker_id: str, action: str, body: ActionPayload, _=Depends(require_admin)):
    if postgres_queue():raise HTTPException(409,"Use Remote Workers controls with the PostgreSQL queue.")
    if action not in ("pause","resume","drain","disable","cancel-jobs"):
        raise HTTPException(404,"Unknown worker action.")
    if body.confirmation != action.upper():
        raise HTTPException(400,f"Type {action.upper()} to confirm.")
    worker=next((row for row in store.worker_metrics()["items"] if row["id"]==worker_id),None)
    if not worker:raise HTTPException(404,"Worker not found.")
    connection=redis_connection()
    previous=connection.hget("arena:worker:modes",worker_id)
    previous=previous.decode() if isinstance(previous,bytes) else previous
    if action=="resume":connection.hdel("arena:worker:modes",worker_id)
    elif action!="cancel-jobs":connection.hset("arena:worker:modes",worker_id,action+"d" if action=="pause" else action+"ing" if action=="drain" else "disabled")
    cancelled=[]
    if action=="cancel-jobs":
        for job in store.list_admin_jobs(status="running",limit=1000):
            if job["worker"] != worker_id:continue
            outcome=store.request_job_cancel(job["id"],body.reason)
            if outcome and outcome["previousStatus"]=="running":
                connection.setex(f"arena:job:cancel:{job['id']}",3600,"1")
                cancelled.append(job["id"])
    store.record_audit("worker_"+action,worker_id,{"previous":previous,"new":action,"jobs":cancelled,"reason":body.reason})
    return {"worker":worker_id,"mode":None if action=="resume" else action,"cancelledJobs":cancelled}


@router.get("/contestants")
def contestants(_=Depends(require_admin)):
    presence = connected_devices()["sessions"]
    by_team = {}
    for session in presence:
        key = session["team"].casefold()
        summary = by_team.setdefault(key, {"sessionCount": 0, "online": False})
        if session["status"] != "offline":
            summary["sessionCount"] += 1
            summary["online"] = True
    return {"contestants": [{**team, **by_team.get(team["team"].casefold(), {"sessionCount": 0, "online": False})}
                            for team in store.contestant_metrics()]}


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
    identity=store.team_identity_by_name(username)
    detail["identity"]=identity
    detail["sessions"]=team_sessions(identity["id"]) if identity else []
    return detail

@router.post("/teams/{team_id}/sessions/{session_id}/revoke")
def revoke_one(team_id: int, session_id: str, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation != "REVOKE": raise HTTPException(400,"Type REVOKE to confirm.")
    identity=store.team_identity(team_id)
    if not identity:raise HTTPException(404,"Team not found.")
    if not revoke_session(team_id,session_id):raise HTTPException(404,"Session not found for this team.")
    store.record_audit("session_revoke",identity["team"],{"sessionId":session_id,"reason":body.reason})
    return {"teamId":team_id,"sessionId":session_id,"revoked":True}

@router.post("/teams/{team_id}/sessions/revoke-all")
def revoke_team(team_id: int, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation != "REVOKE ALL":raise HTTPException(400,"Type REVOKE ALL to confirm.")
    identity=store.team_identity(team_id)
    if not identity:raise HTTPException(404,"Team not found.")
    store.revoke_team_sessions(team_id)
    count=revoke_all_sessions(team_id)
    store.record_audit("team_sessions_revoke",identity["team"],{"count":count,"reason":body.reason})
    return {"teamId":team_id,"revoked":count}

@router.put("/teams/{team_id}/state")
def change_team_state(team_id: int, body: TeamStatePayload, _=Depends(require_admin)):
    if body.action not in ("suspend","unsuspend","block","unblock"):
        raise HTTPException(400,"Unknown team action.")
    if body.action=="suspend" and not body.reason.strip():
        raise HTTPException(400,"A suspension reason is required.")
    changes={"suspend":{"suspended_reason":body.reason.strip()},"unsuspend":{"clear_suspension":True},
             "block":{"blocked":True},"unblock":{"blocked":False}}[body.action]
    result=store.set_team_state(team_id,**changes)
    if not result:raise HTTPException(404,"Team not found.")
    store.record_audit("team_"+body.action,result["team"],
                       {"previous":result["previous"],"new":{"blocked":result["blocked"],"suspendedReason":result["suspendedReason"]},"reason":body.reason})
    return result

@router.get("/teams/{team_id}/sessions")
def list_team_sessions(team_id: int, _=Depends(require_admin)):
    identity=store.team_identity(team_id)
    if not identity:raise HTTPException(404,"Team not found.")
    return {"team":identity["team"],"sessions":team_sessions(team_id)}


@router.post("/contestants/{username}/access")
def set_contestant_access(username: str, body: AccessPayload, _=Depends(require_admin)):
    if body.confirmation != "SET ACCESS":
        raise HTTPException(400, "Type SET ACCESS to confirm.")
    if not store.set_team_access(username, hash_access_code(body.accessCode)):
        raise HTTPException(404, "Contestant not found.")
    store.record_audit("team_access_set", username)
    return {"team": username, "status": "access_updated"}


@router.post("/contestants/{username}/recovery")
def issue_contestant_recovery(username: str, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation != "RESET SESSION":
        raise HTTPException(400, "Type RESET SESSION to confirm.")
    code = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    try:
        identity = store.issue_team_recovery(username, hashlib.sha256(code.encode()).hexdigest(), expires)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not identity:
        raise HTTPException(404, "Contestant not found.")
    store.record_audit("team_recovery_issued", identity["team"])
    return {"team": identity["team"], "recoveryCode": code, "expiresAt": expires.isoformat()}


@router.get("/failures")
def failures(_=Depends(require_admin)):
    return {"failures": store.failure_summary(), "jobs": [job for job in store.list_admin_jobs(limit=500) if job["status"] in ("failed", "timeout")][:200]}


@router.get("/event")
def event_config(_=Depends(require_admin)):
    return store.event_config()


@router.put("/event")
def update_event(body: EventPayload, _=Depends(require_admin)):
    previous=store.event_config()
    try:
        config = store.set_event_config(body.mode, uploads_enabled=body.uploadsEnabled, sandbox_enabled=body.sandboxEnabled,
            official_enabled=body.officialEnabled, tournament_enabled=body.tournamentEnabled,
            registrations_enabled=body.registrationsEnabled, leaderboard_visible=body.leaderboardVisible,
            submission_limit=body.submissionLimit, submission_cooldown_seconds=body.submissionCooldownSeconds)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    store.record_audit("event_mode_change", body.mode, {"previous":previous,"new":config})
    return config


@router.get("/audit")
def audit(_=Depends(require_admin)):
    return {"actions": store.audit_history()}


@router.get("/tournament")
def tournament_status(_=Depends(require_admin)):
    return store.get_tournament_state(initial_state())

@router.get("/tournament/games")
def tournament_games(_=Depends(require_admin)):
    return {"games":store.tournament_games()}


@router.get("/competition")
def competition_status(_=Depends(require_admin)):
    return store.competition()


@router.put("/competition/settings")
def competition_settings(body: CompetitionSettingsPayload, _=Depends(require_admin)):
    try:
        result=store.configure_competition(qualifier_count=body.qualifierCount,
            registration_capacity=body.registrationCapacity,
            official_attempt_limit=body.officialAttemptLimit,
            reference_count=body.referenceCount,tie_replay_limit=body.tieReplayLimit,
            qualification_seed_count=body.qualificationSeedCount)
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    store.record_audit("competition_settings",metadata=body.model_dump())
    return result


@router.get("/reference-bots")
def reference_bots(_=Depends(require_admin)):
    return {"bots":store.reference_bots()}


@router.post("/reference-bots")
async def upload_reference_bot(file: UploadFile=File(...), displayName: str=Form(...),
        description: str=Form(""), category: str=Form(""), familyId: str | None=Form(None),
        _=Depends(require_admin)):
    if file.filename not in ("agent.py","main.py"):
        raise HTTPException(400,"Upload agent.py or main.py; source content is preserved.")
    source=await file.read(100001)
    if len(source)>100000:raise HTTPException(413,"Reference bot exceeds 100 KB.")
    try:
        row=store.add_reference_bot(source,displayName.strip(),description.strip(),category.strip(),familyId)
    except (ValueError,UnicodeError) as exc:raise HTTPException(400,str(exc)) from exc
    store.record_audit("reference_bot_uploaded",str(row["id"]),{"version":row["version"]})
    return row


@router.put("/reference-bots/{bot_id}")
def update_reference_bot(bot_id: int, body: ReferenceActionPayload, _=Depends(require_admin)):
    row=store.set_reference_bot(bot_id,selected=body.selected,enabled=body.enabled,archived=body.archived)
    if not row:raise HTTPException(404,"Reference bot not found.")
    store.record_audit("reference_bot_updated",str(bot_id),body.model_dump(exclude_none=True))
    return row


@router.get("/reference-bots/{bot_id}/download")
def download_reference_bot(bot_id: int, _=Depends(require_admin)):
    source=store.reference_source(bot_id)
    if source is None:raise HTTPException(404,"Reference bot not found.")
    return Response(source,media_type="text/x-python",
                    headers={"Content-Disposition":f'attachment; filename="reference-{bot_id}.py"'})


@router.post("/reference-bots/{bot_id}/test")
def test_reference_bot(bot_id: int, _=Depends(require_admin)):
    if store.reference_source(bot_id) is None:raise HTTPException(404,"Reference bot not found.")
    job=store.create_job(None,"reference_test",payload={"referenceBotId":bot_id})
    try:
        from backend.services.queueing import enqueue
        enqueue(job)
    except Exception as exc:
        store.fail_job(job["id"],str(exc),"REDIS_FAILURE")
        raise HTTPException(503,"Reference test could not be queued.") from exc
    store.record_audit("reference_bot_test_queued",str(bot_id),{"jobId":job["id"]})
    return {"job":job}


@router.post("/competition/start-qualification")
def start_qualification(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="START QUALIFICATION":raise HTTPException(400,"Type START QUALIFICATION to confirm.")
    try:result=store.start_qualification(load_scoring_config())
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    store.record_audit("qualification_started",metadata={"referenceCount":len(result["referencePool"])})
    return result


@router.post("/competition/close-qualification")
def close_qualification(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="CLOSE QUALIFICATION":raise HTTPException(400,"Type CLOSE QUALIFICATION to confirm.")
    try:result=store.close_qualification()
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    store.record_audit("qualification_closed")
    return result


@router.post("/competition/finalize")
def finalize_qualification(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="FINALIZE QUALIFICATION":raise HTTPException(400,"Type FINALIZE QUALIFICATION to confirm.")
    try:result=store.finalize_qualification()
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    store.record_audit("qualification_finalized",metadata={"qualifiers":len(result["qualifiers"])})
    return {"phase":result["phase"],"qualifiers":[{k:v for k,v in row.items() if k!="objectKey"} for row in result["qualifiers"]]}


@router.get("/competition/standings")
def qualification_standings(_=Depends(require_admin)):
    return {"entries":[{k:v for k,v in row.items() if k!="objectKey"} for row in store.qualification_leaderboard()]}


@router.post("/competition/jobs/{job_id}/adjudicate")
def adjudicate_qualification_failure(job_id: str, body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="ADJUDICATE FAILURE" or not body.reason.strip():
        raise HTTPException(400,"Type ADJUDICATE FAILURE and provide a reason.")
    if not store.adjudicate_infrastructure_failure(job_id,body.reason):
        raise HTTPException(409,"Only terminal infrastructure failures from the closing qualification may be adjudicated.")
    store.record_audit("qualification_failure_adjudicated",job_id,{"reason":body.reason})
    return {"jobId":job_id,"status":"adjudicated"}


@router.get("/competition/bracket-preview")
def bracket_preview(_=Depends(require_admin)):
    state=store.competition()
    roster=state["qualifiers"]
    if not roster:
        roster=store.qualification_leaderboard()[:state["settings"]["qualifierCount"]]
    if len(roster)<2:raise HTTPException(409,"At least two eligible teams are required.")
    bracket=opening_bracket(roster)
    bracket["matches"]=[{**row,"teamA":{k:v for k,v in row["teamA"].items() if k!="objectKey"},
                          "teamB":{k:v for k,v in row["teamB"].items() if k!="objectKey"} if row["teamB"] else None,
                          "winner":{k:v for k,v in row["winner"].items() if k!="objectKey"} if row["winner"] else None}
                         for row in bracket["matches"]]
    return bracket


@router.post("/competition/lock-bracket")
def lock_bracket(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="LOCK BRACKET":raise HTTPException(400,"Type LOCK BRACKET to confirm.")
    competition=store.competition()
    if competition["phase"]!="QUALIFICATION_FINALIZED":raise HTTPException(409,"Finalize Round 1 first.")
    roster=competition["qualifiers"]
    preview=opening_bracket(roster)
    state=initial_state([row["team"] for row in roster])
    state.update(status="ready",message="Seeded bracket locked and ready to start.",
                 selectedQualifiers=[row["team"] for row in roster],
                 qualificationSeeds={row["team"]:row["seed"] for row in roster},
                 maxPlayers=competition["settings"]["registrationCapacity"],
                 qualifierCount=len(roster),bracketCapacity=preview["capacity"],
                 openingMatches=[{k:v for k,v in match.items() if k not in ("teamA","teamB","winner")}|
                     {"player1":match["teamA"]["team"],
                      "player2":match["teamB"]["team"] if match["teamB"] else None,
                      "seedA":match["teamA"]["seed"],
                      "seedB":match["teamB"]["seed"] if match["teamB"] else None}
                     for match in preview["matches"]])
    store.save_tournament_state(state)
    store.transition_competition("QUALIFICATION_FINALIZED","TOURNAMENT_READY")
    store.record_audit("bracket_locked",metadata={"qualifiers":len(roster),"byes":preview["byes"]})
    return {"status":"ready","qualifiers":len(roster),"byes":preview["byes"]}


@router.post("/tournament/qualifiers")
def load_qualifiers(body: ActionPayload, _=Depends(require_admin)):
    raise HTTPException(410,"Use Finalize Qualification, then Lock Bracket to freeze seeded qualifiers.")


@router.post("/tournament/start")
def start_tournament(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="START TOURNAMENT":raise HTTPException(400,"Type START TOURNAMENT to confirm.")
    if not store.event_config()["tournamentEnabled"]:raise HTTPException(423,"Enable tournament mode before launching the tournament.")
    competition=store.competition()
    if competition["phase"]!="TOURNAMENT_READY":raise HTTPException(409,"Lock the finalized bracket before starting Round 2.")
    roster=competition["qualifiers"]
    state=store.get_tournament_state(initial_state())
    if state.get("status")!="ready":raise HTTPException(409,"The locked bracket is unavailable.")
    participants=[row["team"] for row in roster]
    state.update({"status":"starting","isLive":True,"message":"Seeded tournament queued.",
                  "playersCount":len(participants),"registeredPlayers":participants,
                  "totalRoundsEstimate":math.ceil(math.log2(len(participants))),
                  "currentRound":0,"currentMatches":[],"roundsHistory":[],"byes":[],
                  "eliminatedPlayers":[],"allMatches":[],"champion":None,"finalScore":None,"error":None})
    if not store.claim_tournament_start(state,initial_state()):
        raise HTTPException(409,"Tournament is already active.")
    job=store.create_job(None,"tournament",payload={"roster":roster,
        "tieReplayLimit":competition["settings"]["tieReplayLimit"]})
    store.transition_competition("TOURNAMENT_READY","TOURNAMENT_RUNNING")
    try:
        from backend.services.queueing import enqueue
        enqueue(job)
    except Exception as exc:
        store.fail_job(job["id"],f"Queue transport unavailable: {exc}","REDIS_FAILURE")
        state.update({"status":"ready","isLive":False,"error":"Tournament queue unavailable.","message":"Bracket remains locked; try starting again when the queue recovers."})
        store.save_tournament_state(state)
        store.transition_competition("TOURNAMENT_RUNNING","TOURNAMENT_READY")
        raise HTTPException(503,"Tournament queue unavailable.") from exc
    store.record_audit("tournament_start",job["id"],{"participants":len(participants)})
    return {"job":job,"status":"queued","participants":participants}


@router.post("/tournament/reset")
def reset_tournament(body: ActionPayload, _=Depends(require_admin)):
    raise HTTPException(409,"Locked competition brackets cannot be reset; create a separate competition instance for another run.")


@router.post("/competition/resume-tournament")
def resume_tournament(body: ActionPayload, _=Depends(require_admin)):
    if body.confirmation!="RESUME TOURNAMENT":raise HTTPException(400,"Type RESUME TOURNAMENT to confirm.")
    competition=store.competition()
    if competition["phase"]!="TOURNAMENT_RUNNING" or not store.claim_tournament_resume():
        raise HTTPException(409,"Only a stopped locked tournament can be resumed.")
    job=store.create_job(None,"tournament",payload={"roster":competition["qualifiers"],
        "tieReplayLimit":competition["settings"]["tieReplayLimit"]})
    try:
        from backend.services.queueing import enqueue
        enqueue(job)
    except Exception as exc:
        store.fail_job(job["id"],str(exc),"REDIS_FAILURE")
        state=store.get_tournament_state(initial_state())
        state.update(status="error",isLive=False,error="Tournament queue unavailable.")
        store.save_tournament_state(state)
        raise HTTPException(503,"Tournament queue unavailable.") from exc
    store.record_audit("tournament_resumed",job["id"],{"completed":len(store.get_tournament_state(initial_state()).get("allMatches",[]))})
    return {"job":job,"status":"queued"}


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
