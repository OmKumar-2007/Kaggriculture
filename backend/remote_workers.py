"""Scoped, outbound-HTTPS protocol for evaluator laptops."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.admin import require_admin
from backend.services.blob_storage import objects
from backend.services.storage import store
from backend.services.tournament_state import apply_progress, initial_state

admin_router = APIRouter(prefix="/api/admin/remote-workers", tags=["remote evaluators"])
router = APIRouter(prefix="/api/remote-workers", tags=["remote evaluators"])
VERSION = os.getenv("FARMCRAFT_EVALUATOR_VERSION", "2026.10.08")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "evaluation.json"


def _config_hash() -> str:
    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()


def _https(request: Request) -> None:
    if os.getenv("APP_ENV", "development").lower() in ("production", "prod"):
        if request.url.scheme != "https" and request.headers.get("x-forwarded-proto") != "https":
            raise HTTPException(400, "Worker communication requires HTTPS.")


def _worker(request: Request) -> dict:
    _https(request)
    bearer = request.headers.get("authorization", "")
    if not bearer.startswith("Bearer "):
        raise HTTPException(401, "Worker credential required.")
    try:
        worker_id, credential = bearer[7:].split(".", 1)
    except ValueError:
        raise HTTPException(401, "Invalid worker credential.") from None
    worker = store.authenticate_remote_worker(worker_id, credential)
    if not worker:
        raise HTTPException(401, "Worker credential invalid or revoked.")
    return worker


class Registration(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    name: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
    version: str = Field(min_length=1, max_length=40)


class Heartbeat(BaseModel):
    telemetry: dict = Field(default_factory=dict)
    jobId: str | None = None
    attemptId: str | None = None


class Attempt(BaseModel):
    attemptId: str


class Result(Attempt):
    result: dict
    error: str | None = Field(default=None, max_length=8000)
    errorKind: str | None = Field(default=None, max_length=60)


class Progress(Attempt):
    stage: str = Field(max_length=50)
    status: str = Field(max_length=20)
    detail: str = Field(default="", max_length=500)
    current: int | None = None
    total: int | None = None
    tournamentEvent: str | None = None
    tournamentData: dict | None = None


class Capacity(BaseModel):
    capacity: int = Field(ge=1, le=16)
    confirmation: str


class Confirm(BaseModel):
    confirmation: str


@router.get("/version")
def version():
    return {"evaluatorVersion": VERSION, "evaluationConfigSha256": _config_hash()}


@admin_router.post("/registration")
def issue_registration(request: Request, _=Depends(require_admin)):
    _https(request)
    if not store.worker_registration_enabled():
        raise HTTPException(423, "Worker registration is disabled.")
    token = store.issue_worker_registration()
    store.record_audit("worker_registration_issued", metadata={"expiresMinutes": 15})
    return {"token": token, "expiresMinutes": 15, "evaluatorVersion": VERSION}


@admin_router.get("")
def list_workers(_=Depends(require_admin)):
    return {"workers": store.remote_worker_metrics()["items"], "evaluatorVersion": VERSION,
            "registrationEnabled": store.worker_registration_enabled()}


@admin_router.post("/registration/{action}")
def registration_mode(action: str, body: Confirm, _=Depends(require_admin)):
    if action not in ("enable", "disable") or body.confirmation != action.upper():
        raise HTTPException(400, "Invalid confirmation.")
    store.set_worker_registration_enabled(action == "enable")
    store.record_audit("worker_registration_"+action)
    return {"registrationEnabled": action == "enable"}


@admin_router.post("/{worker_id}/revoke")
def revoke(worker_id: str, body: Confirm, _=Depends(require_admin)):
    if body.confirmation != "REVOKE": raise HTTPException(400, "Type REVOKE to confirm.")
    if not store.set_remote_worker_status(worker_id, "revoked"):
        raise HTTPException(404, "Worker not found.")
    store.record_audit("remote_worker_revoked", worker_id)
    return {"revoked": True}


@admin_router.post("/{worker_id}/rotate")
def rotate(worker_id: str, body: Confirm, _=Depends(require_admin)):
    if body.confirmation != "ROTATE": raise HTTPException(400, "Type ROTATE to confirm.")
    credential = store.rotate_remote_worker(worker_id)
    if not credential: raise HTTPException(404, "Active worker not found.")
    store.record_audit("remote_worker_rotated", worker_id)
    return {"workerId": worker_id, "credential": credential}


@admin_router.post("/{worker_id}/{action}")
def mode(worker_id: str, action: str, body: Confirm, _=Depends(require_admin)):
    if action not in ("pause", "resume", "drain"):
        raise HTTPException(404, "Unknown worker action.")
    if body.confirmation != action.upper():
        raise HTTPException(400, f"Type {action.upper()} to confirm.")
    value = {"pause": "paused", "resume": "active", "drain": "draining"}[action]
    if not store.set_remote_worker_status(worker_id, value):
        raise HTTPException(404, "Worker not found.")
    store.record_audit("remote_worker_"+action, worker_id)
    return {"status": value}


@admin_router.put("/{worker_id}/capacity")
def capacity(worker_id: str, body: Capacity, _=Depends(require_admin)):
    if body.confirmation != "SET CAPACITY": raise HTTPException(400, "Type SET CAPACITY to confirm.")
    if not store.set_remote_concurrency(worker_id, body.capacity):
        raise HTTPException(404, "Worker not found.")
    store.record_audit("remote_worker_capacity", worker_id, {"capacity": body.capacity})
    return {"capacity": body.capacity}


@router.post("/register")
def register(body: Registration, request: Request):
    _https(request)
    if not store.worker_registration_enabled():
        raise HTTPException(423, "Worker registration is disabled.")
    if body.version != VERSION:
        raise HTTPException(409, "Evaluator version mismatch. Update the evaluator package.")
    credentials = store.register_remote_worker(body.token, body.name, body.version)
    if not credentials:
        raise HTTPException(409, "Registration token expired, already used, or worker name already active.")
    store.record_audit("remote_worker_registered", credentials["workerId"], {"name": body.name})
    return credentials


@router.post("/heartbeat")
def heartbeat(body: Heartbeat, worker=Depends(_worker)):
    return store.remote_heartbeat(worker["id"], body.telemetry, body.jobId, body.attemptId)


@router.post("/claim")
def claim(worker=Depends(_worker)):
    store.recover_remote_leases()
    job = store.claim_remote_job(worker["id"], worker["version"])
    if not job: return {"job": None}
    job["evaluationConfigSha256"] = _config_hash()
    store.pipeline_event(job["id"], "configuration", "completed",
                         f"Evaluator {VERSION}, config SHA256 {_config_hash()}")
    if job["type"] == "tournament":
        names = store.job_payload(job["id"]).get("participants") or [x["team"] for x in store.leaderboard()]
        sources = []
        for name in names:
            active = next((x for x in store.list_submissions(name) if x["is_active"]), None)
            if active: sources.append({"team": name, "submissionId": active["id"]})
        job["participants"] = sources
        store.freeze_remote_sources(job["id"], sources)
    return {"job": job}


@router.get("/jobs/{job_id}/source/{submission_id}")
def source(job_id: str, submission_id: int, attemptId: str, worker=Depends(_worker)):
    if not store.remote_attempt_valid(job_id, worker["id"], attemptId):
        raise HTTPException(409, "Attempt is no longer owned by this worker.")
    job = store.get_job(job_id)
    allowed = ({job["submissionId"]} if job["type"] != "tournament" else
               {row["submissionId"] for row in store.job_payload(job_id).get("_remoteSources", [])})
    if submission_id not in allowed:
        raise HTTPException(403, "Submission is outside this assignment.")
    submission = store.get_submission(submission_id)
    if not submission: raise HTTPException(404, "Submission not found.")
    payload = objects.get_bytes(submission["object_key"])
    return Response(payload, media_type="text/x-python",
                    headers={"X-Source-SHA256": hashlib.sha256(payload).hexdigest()})


@router.post("/jobs/{job_id}/progress")
def progress(job_id: str, body: Progress, worker=Depends(_worker)):
    if not store.remote_attempt_valid(job_id, worker["id"], body.attemptId):
        raise HTTPException(409, "Attempt is no longer owned by this worker.")
    store.pipeline_event(job_id, body.stage, body.status, body.detail)
    if body.current is not None:
        store.update_job_progress(job_id, body.current, body.total)
    if body.tournamentEvent:
        state = store.get_tournament_state(initial_state())
        store.save_tournament_state(apply_progress(state, body.tournamentEvent, body.tournamentData or {}))
    return {"accepted": True}


@router.put("/jobs/{job_id}/replay/{replay_id}")
async def replay(job_id: str, replay_id: str, attemptId: str, request: Request, worker=Depends(_worker)):
    if not store.remote_attempt_valid(job_id, worker["id"], attemptId):
        raise HTTPException(409, "Attempt is no longer owned by this worker.")
    if len(replay_id) != 32 or any(c not in "0123456789abcdef" for c in replay_id):
        raise HTTPException(400, "Invalid replay ID.")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, "Replay exceeds 8 MiB.")
    payload = bytes(data)
    try: json.loads(payload)
    except (ValueError, UnicodeDecodeError): raise HTTPException(400, "Replay is not valid JSON.") from None
    objects.put_bytes(f"replays/{replay_id}.json", payload, "application/json")
    return {"stored": True}


@router.post("/jobs/{job_id}/result")
def result(job_id: str, body: Result, worker=Depends(_worker)):
    if body.error and (body.errorKind or "").startswith("CONTESTANT"):
        accepted = store.commit_job_result(job_id, body.result, error=body.error,
                                           error_kind=body.errorKind, worker_id=worker["id"],
                                           attempt_id=body.attemptId)
    elif body.error:
        accepted = store.fail_remote_attempt(job_id, worker["id"], body.attemptId,
                                             body.error, body.errorKind or "WORKER_FAILURE")
    else:
        accepted = store.commit_job_result(job_id, body.result, worker_id=worker["id"],
                                           attempt_id=body.attemptId)
    if not accepted: raise HTTPException(409, "Attempt is no longer active or result was already committed.")
    return {"accepted": True}
