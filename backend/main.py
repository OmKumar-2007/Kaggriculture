import os
import sys
from pathlib import Path
import re
import threading
import math
import json
import hashlib
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse

# Fix Windows console charmap / emoji encoding issues
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ============================================================
# PROJECT PATHS
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from py_env import get_kaggle_python
from backend.services.validator import AgentValidationError, inspect_agent_source, validate_agent_source
from backend.services.sandbox import REPLAY_DIR, list_benchmarks
from backend.services.analytics import analyze_replay, replay_frame
from backend.services.storage import store, ActiveJobError
from backend.services.blob_storage import objects
from backend.services.queueing import enqueue, ping_redis, queue_position
from backend.services.scoring import load_scoring_config
from backend.services.capabilities import detect_source_capabilities
from backend.admin import router as admin_router, record_request
from backend.remote_workers import admin_router as remote_admin_router, router as remote_worker_router
from backend.services.participants import router as participant_router, require_team, current_session, limit_operation
from time import perf_counter

PLAYERS_DIR = ROOT / "players"
PLAYERS_DIR.mkdir(exist_ok=True)

EXAMPLES_DIR = ROOT / "NITW_Farm_AI_Challenge_v1" / "examples"
STARTER_DIR = ROOT / "NITW_Farm_AI_Participant_Starter"
CONTESTANT_STARTER = ROOT / "contestant_starter" / "agent.py"
CONTESTANT_GUIDE = ROOT / "docs" / "CONTESTANT_GUIDE.md"
SUBMISSION_HISTORY_DIR = ROOT / "submissions"
SUBMISSION_HISTORY_DIR.mkdir(exist_ok=True)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="FarmCraft Tournament API"
)
app.include_router(admin_router)
app.include_router(remote_admin_router)
app.include_router(remote_worker_router)
app.include_router(participant_router)

@app.middleware("http")
async def collect_request_metrics(request, call_next):
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        record_request(perf_counter() - started, 500)
        raise
    record_request(perf_counter() - started, response.status_code)
    if request.method not in ("GET","HEAD","OPTIONS") and request.url.path.startswith("/api/admin/") and response.status_code >= 400:
        try:store.record_audit("admin_action_failed",request.scope.get("route").name if request.scope.get("route") else None,
                               {"status":response.status_code})
        except Exception:pass
    return response

@app.on_event("startup")
def recover_interrupted_jobs():
    store.recover_stale_jobs(int(os.getenv("STALE_JOB_SECONDS", "300")))
    try:
        from backend.services.queueing import reconcile_queued_jobs
        reconcile_queued_jobs()
    except Exception:
        pass  # The host worker retries reconciliation after Redis recovers.
    migrated=[]
    for player_dir in PLAYERS_DIR.iterdir():
        agent_path=player_dir/"agent.py"
        if not player_dir.is_dir() or not agent_path.is_file() or store.current_submission(player_dir.name):continue
        try:
            source=agent_path.read_text(encoding="utf-8");validate_agent_source(source)
            key=f"submissions/{player_dir.name}/{uuid4().hex}/agent.py"
            objects.put_bytes(key,source.encode("utf-8"),"text/x-python")
            submission=store.create_submission(player_dir.name,key,valid=True)
            store.activate_submission(player_dir.name,submission["id"]);migrated.append(player_dir.name)
        except Exception:
            continue
    state=store.get_tournament_state(create_initial_state())
    if migrated:
        existing={name.lower() for name in state.get("registeredPlayers",[])}
        state["registeredPlayers"]+= [name for name in migrated if name.lower() not in existing]
        state["playersCount"]=len(state["registeredPlayers"]);store.save_tournament_state(state)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_SUBMISSION_SIZE_KB", "256")) * 1024

def _require_agent_filename(filename: str | None) -> None:
    if filename not in ("agent.py", "main.py"):
        raise HTTPException(status_code=400, detail="Upload a Python file named agent.py or main.py.")

def _source_for(submission: dict) -> str:
    try:
        return objects.get_bytes(submission["object_key"]).decode("utf-8")
    except (FileNotFoundError, KeyError):
        # Compatibility with records created before object storage was introduced.
        return Path(submission["file_path"]).read_text(encoding="utf-8")

def _enqueue_persistent_job(job: dict) -> dict:
    try:
        enqueue(job)
    except Exception:
        # The database job is durable; the host worker reconciles it into Redis
        # after the queue transport recovers. Keep the submission visible.
        return {**job, "queuePosition": None, "queueDelayed": True}
    return {**job, "queuePosition": queue_position(job)}

def _require_event_action(action: str):
    config = store.event_config()
    enabled = {"upload": config["uploadsEnabled"], "sandbox": config["sandboxEnabled"],
               "official": config["officialEnabled"], "tournament": config["tournamentEnabled"]}.get(action, True)
    if not enabled:
        raise HTTPException(status_code=423, detail=f"{action.title()} is paused for {config['mode'].lower()} mode.")


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        *[origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()],
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# TOURNAMENT STATE MODEL
# ============================================================

def create_initial_state():
    current_players = []

    return {
        "status": "registration",  # "registration" | "starting" | "round_running" | "next_round" | "final" | "champion" | "error"
        "message": "Registration is open. Waiting for players to join.",
        "playersCount": len(current_players),
        "maxPlayers": store.event_config()["registrationCapacity"],
        "registeredPlayers": current_players,
        "currentRound": 0,
        "totalRoundsEstimate": math.ceil(math.log2(len(current_players))) if len(current_players) > 1 else 0,
        "currentMatches": [],
        "roundsHistory": [],
        "byes": [],
        "eliminatedPlayers": [],
        "allMatches": [],
        "champion": None,
        "finalScore": None,
        "error": None,
        "isLive": False,
    }

tournament_state = store.get_tournament_state(create_initial_state())
state_lock = threading.Lock()


# ============================================================
# LIVE PROGRESS HANDLER
# ============================================================

def handle_tournament_progress(event: str, data: dict):
    """
    Callback triggered by tournament.py during execution.
    Updates tournament_state in real-time.
    """
    with state_lock:
        if event == "ROUND_START":
            round_num = data["round"]
            is_final = data.get("isFinal", False)
            tournament_state["status"] = "final" if is_final else "round_running"
            tournament_state["currentRound"] = round_num
            tournament_state["currentMatches"] = data["matches"]
            tournament_state["message"] = f"Round {round_num} {'(FINAL)' if is_final else 'in progress'} ({len(data['matches'])} matches)"

            if data.get("byePlayer"):
                bye_entry = {"round": round_num, "player": data["byePlayer"]}
                if bye_entry not in tournament_state["byes"]:
                    tournament_state["byes"].append(bye_entry)

        elif event == "MATCH_START":
            m_idx = data["matchIndex"]
            if m_idx < len(tournament_state["currentMatches"]):
                tournament_state["currentMatches"][m_idx]["status"] = "running"
            tournament_state["message"] = f"Round {data['round']}: {data['player1']} vs {data['player2']} playing..."

        elif event == "MATCH_END":
            m_idx = data["matchIndex"]
            if m_idx < len(tournament_state["currentMatches"]):
                tournament_state["currentMatches"][m_idx].update({
                    "status": "completed",
                    "p1Score": data["p1Score"],
                    "p2Score": data["p2Score"],
                    "winner": data["winner"],
                    "loser": data["loser"],
                    "tieReplays": data.get("tieReplays", 0),
                    "seed": data.get("seed"),
                })

            # Record eliminated player
            elim_entry = {
                "player": data["loser"],
                "eliminatedInRound": data["round"],
                "eliminatedBy": data["winner"],
            }
            if not any(e["player"] == data["loser"] for e in tournament_state["eliminatedPlayers"]):
                tournament_state["eliminatedPlayers"].append(elim_entry)

            # Record to allMatches
            tournament_state["allMatches"].append(data)
            tournament_state["message"] = f"Round {data['round']}: {data['winner']} defeated {data['loser']} ({data['p1Score']} - {data['p2Score']})"

        elif event == "ROUND_END":
            round_num = data["round"]
            round_matches = [dict(m) for m in tournament_state["currentMatches"]]
            round_bye = next((b["player"] for b in tournament_state["byes"] if b["round"] == round_num), None)
            
            # Archive round into roundsHistory if not already archived
            if not any(r["round"] == round_num for r in tournament_state["roundsHistory"]):
                tournament_state["roundsHistory"].append({
                    "round": round_num,
                    "matches": round_matches,
                    "byePlayer": round_bye,
                    "advancing": data["advancing"],
                })

            if data.get("remainingCount", 0) > 1:
                tournament_state["status"] = "next_round"
                tournament_state["message"] = f"Round {round_num} completed. Transitioning to Round {round_num + 1}..."

        elif event == "TOURNAMENT_END":
            champion_obj = data["champion"]
            tournament_state["status"] = "champion"
            tournament_state["champion"] = champion_obj
            tournament_state["isLive"] = False

            if data.get("finalMatch"):
                fm = data["finalMatch"]
                tournament_state["finalScore"] = {
                    "player1": fm["player1"],
                    "player2": fm["player2"],
                    "p1Score": fm["p1Score"],
                    "p2Score": fm["p2Score"],
                    "winner": fm["winner"],
                }
            tournament_state["message"] = f"Tournament Complete! Champion: {champion_obj['username']}"

        elif event == "TOURNAMENT_ERROR":
            tournament_state["status"] = "error"
            tournament_state["error"] = data["error"]
            tournament_state["isLive"] = False
            tournament_state["message"] = f"Tournament aborted: {data['error']}"
        store.save_tournament_state(tournament_state)


# ============================================================
# API ENDPOINTS
# ============================================================

@app.get("/")
def home():
    state=store.get_tournament_state(create_initial_state())
    return {
        "message": "FarmCraft Tournament Backend Running",
        "engineReady": bool(get_kaggle_python()),
        "status": state["status"],
    }


@app.head("/")
def health_head():
    return Response(status_code=200)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/ready")
def readiness():
    checks = {}
    for name, probe in (("database", store.ping), ("redis", ping_redis), ("storage", objects.healthcheck)):
        try: checks[name] = bool(probe())
        except Exception: checks[name] = False
    if not all(checks.values()):
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks}

@app.get("/event/status")
def public_event_status():
    config=store.event_config()
    return {key:config[key] for key in ("mode","uploadsEnabled","sandboxEnabled","officialEnabled","tournamentEnabled")}

@app.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    job = store.get_job(job_id)
    if not job: raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("team"):
        require_team(request, job["team"])
    return {**_public_job(job), "queuePosition": queue_position(job)}

def _public_job(job: dict) -> dict:
    contestant_failure=bool(job.get("errorKind") and (job["errorKind"].startswith("CONTESTANT_") or job["errorKind"]=="INVALID_ACTION"))
    terminal_error = job.get("status") in ("failed", "timeout")
    error=(job.get("error") if contestant_failure else "Arena service could not complete this job.") if terminal_error else ("Your evaluation was cancelled by an organizer." if job.get("status")=="cancelled" else None)
    return {key:job.get(key) for key in ("id","type","status","createdAt","startedAt","completedAt","progressCurrent","progressTotal","attempts","result")} | {"error":error,"errorKind":"contestant" if contestant_failure else ("system" if terminal_error else None)}

@app.get("/teams/{username}/jobs")
def team_jobs(username: str, request: Request, limit: int = Query(default=25, ge=1, le=100)):
    require_team(request, username)
    return {"jobs": [_public_job(job) for job in store.list_jobs(_clean_username(username), limit)]}

@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    job = store.get_job(job_id)
    if not job: raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("team"):
        require_team(request, job["team"])
    async def stream():
        previous = None
        while True:
            if job.get("team"):
                try:require_team(request,job["team"])
                except HTTPException:break
            job = store.get_job(job_id)
            payload = json.dumps({**_public_job(job), "queuePosition": queue_position(job)})
            if payload != previous:
                yield f"event: job\ndata: {payload}\n\n"; previous = payload
            if job["status"] in ("completed", "failed", "timeout", "cancelled"): break
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/players")
def get_players():
    state=store.get_tournament_state(create_initial_state())
    players=[{"username":name} for name in sorted(state.get("registeredPlayers",[]),key=str.lower)]
    with state_lock:
        tournament_state.clear();tournament_state.update(state)

    return {
        "count": len(players),
        "maxPlayers": store.event_config()["registrationCapacity"],
        "players": players,
    }


@app.get("/starter/download")
def download_starter():
    if not CONTESTANT_STARTER.is_file():
        raise HTTPException(status_code=404, detail="Contestant starter is unavailable.")
    return FileResponse(CONTESTANT_STARTER, media_type="text/x-python", filename="agent.py")


@app.get("/guide", response_class=PlainTextResponse)
def contestant_guide():
    if not CONTESTANT_GUIDE.is_file():
        raise HTTPException(status_code=404, detail="Contestant guide is unavailable.")
    return CONTESTANT_GUIDE.read_text(encoding="utf-8")


@app.post("/validate")
async def validate_agent(agent: UploadFile = File(...)):
    _require_agent_filename(agent.filename)
    try:
        content = await agent.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES: raise HTTPException(status_code=413, detail="Agent file exceeds the configured upload limit.")
        source_text = content.decode("utf-8")
        report = validate_agent_source(source_text)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Agent file must be valid UTF-8 text.")
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return report.to_dict()


@app.get("/sandbox/opponents")
def sandbox_opponents():
    return {"opponents": list_benchmarks()}


@app.post("/sandbox/run")
async def run_sandbox(
    request: Request,
    agent: UploadFile = File(...),
    username: str = Form("guest"),
    opponent: str = Form("starter_crop"),
    seed: int = Form(20260929),
):
    _require_event_action("sandbox")
    session = require_team(request, username)
    username = session["team"]
    limit_operation(session, "sandbox", 6)
    _require_upload_policy(session)
    _require_agent_filename(agent.filename)
    try:
        content = await agent.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES: raise HTTPException(status_code=413, detail="Agent file exceeds the configured upload limit.")
        source_text = content.decode("utf-8")
        report = validate_agent_source(source_text)
        team = username
        object_key = f"submissions/team_{session['teamId']}/{uuid4().hex}/agent.py"
        objects.put_bytes(object_key, source_text.encode("utf-8"), "text/x-python")
        submission = store.create_submission(team, object_key, valid=True)
        job = store.create_job(team, "sandbox", submission_id=submission["id"], opponent=opponent, seed=seed)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Agent file must be valid UTF-8 text.")
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ActiveJobError as exc: raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        if "object_key" in locals():objects.delete_prefix(object_key)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return Response(content=json.dumps({**_enqueue_persistent_job(job), "validationWarnings": report.warnings}), media_type="application/json", status_code=202)


def _clean_username(username: str) -> str:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise HTTPException(status_code=400, detail="Team name can contain only letters, numbers, '_' and '-'.")
    return username

def _require_upload_policy(session: dict) -> None:
    config=store.event_config()
    usage=store.submission_policy(session["teamId"])
    if config["submissionLimit"] and usage["count"]>=config["submissionLimit"]:
        raise HTTPException(429,"This team has reached the upload limit.")
    if config["submissionCooldownSeconds"] and usage["lastAt"]:
        last=datetime.fromisoformat(usage["lastAt"])
        if (datetime.now(timezone.utc)-last).total_seconds()<config["submissionCooldownSeconds"]:
            raise HTTPException(429,"Please wait before uploading another bot.")


@app.get("/botlab/{username}")
def botlab_summary(username: str, request: Request):
    username = _clean_username(username)
    username = require_team(request, username)["team"]
    summary = store.summary(username)
    current = summary.get("currentSubmission")
    capabilities = []
    if current:
        try: capabilities = detect_source_capabilities(_source_for(current))
        except (FileNotFoundError, UnicodeDecodeError): capabilities = []
    for key in ("currentSubmission","activeSubmission"):
        item=summary.get(key)
        if item:item.pop("object_key",None);item.pop("file_path",None)
    public_submissions=store.list_submissions(username)
    for item in public_submissions:item.pop("object_key",None);item.pop("file_path",None)
    summary["jobs"]=[_public_job(job) for job in summary.get("jobs",[])]
    return {**summary, "capabilities": capabilities, "submissions": public_submissions}


@app.post("/botlab/upload")
async def botlab_upload(request: Request, username: str = Form(...), agent: UploadFile = File(...)):
    _require_event_action("upload")
    username = _clean_username(username)
    session = require_team(request, username)
    username = session["team"]
    limit_operation(session, "upload", 6)
    _require_upload_policy(session)
    _require_agent_filename(agent.filename)
    try:
        content = await agent.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES: raise HTTPException(status_code=413, detail="Agent file exceeds the configured upload limit.")
        if not content: raise HTTPException(status_code=400, detail="Agent file is empty.")
        source = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Agent file must be valid UTF-8 text.")
    report = inspect_agent_source(source)
    object_key = f"submissions/team_{session['teamId']}/{uuid4().hex}/agent.py"
    objects.put_bytes(object_key, source.encode("utf-8"), "text/x-python")
    try:
        submission = store.create_submission(
            username, object_key, valid=report.valid,
            errors="\n".join(report.errors) if report.errors else None,
        )

    except ValueError as exc:
        objects.delete_prefix(object_key)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"submission": submission, "validation": report.to_dict()}


@app.post("/botlab/{username}/validate")
def botlab_validate(username: str, request: Request):
    username = _clean_username(username)
    username = require_team(request, username)["team"]
    submission = store.current_submission(username)
    if not submission:
        raise HTTPException(status_code=404, detail="Upload a bot version first.")
    source = _source_for(submission)
    return inspect_agent_source(source).to_dict()


@app.post("/botlab/{username}/sandbox")
def botlab_sandbox(username: str, request: Request, opponent: str = Form("starter_crop"), seed: int = Form(20260929)):
    _require_event_action("sandbox")
    username = _clean_username(username)
    session = require_team(request, username)
    username = session["team"]
    limit_operation(session, "sandbox", 6)
    submission = store.current_submission(username)
    if not submission:
        raise HTTPException(status_code=404, detail="Upload a bot version first.")
    if submission["validation_status"] != "valid":
        raise HTTPException(status_code=400, detail=submission["validation_errors"] or "Current version is invalid.")
    try:
        job = store.create_job(username, "sandbox", submission_id=submission["id"], opponent=opponent, seed=seed)
    except ActiveJobError as exc: raise HTTPException(status_code=409, detail=str(exc))
    return Response(content=json.dumps(_enqueue_persistent_job(job)), media_type="application/json", status_code=202)


@app.post("/botlab/{username}/submit")
def botlab_submit(username: str, request: Request):
    _require_event_action("official")
    competition=store.competition()
    if competition["phase"]!="QUALIFICATION_OPEN":
        raise HTTPException(status_code=423,detail="Round 1 qualification is not open.")
    username = _clean_username(username)
    session = require_team(request, username)
    username = session["team"]
    limit_operation(session, "official", max(10,competition["settings"]["officialAttemptLimit"]), 3600)
    submission = store.current_submission(username)
    if not submission:
        raise HTTPException(status_code=404, detail="Upload a bot version first.")
    if submission["validation_status"] != "valid":
        raise HTTPException(status_code=400, detail="Only a valid version can be submitted.")
    attempts=store.official_attempts(username)
    if attempts["remaining"]<1:
        raise HTTPException(status_code=429,detail="No official qualification attempts remain.")
    try:
        frozen=competition["evaluationConfig"]
        total = len(frozen["seeds"]) * len(frozen["opponents"]) * len(frozen.get("sides", [0, 1]))
        source_hash=hashlib.sha256(objects.get_bytes(submission["object_key"])).hexdigest()
        job = store.create_job(username, "official", submission_id=submission["id"], progress_total=total,
            payload={"evaluationConfig":frozen,"referencePool":competition["referencePool"],
                     "submissionSha256":source_hash})
    except ActiveJobError as exc: raise HTTPException(status_code=409, detail=str(exc))
    queued = _enqueue_persistent_job(job)
    return Response(content=json.dumps({**queued, "success": True, "message": f"v{submission['version']} official evaluation queued."}), media_type="application/json", status_code=202)


@app.get("/leaderboard")
def leaderboard():
    competition=store.competition()
    config = competition["evaluationConfig"] or load_scoring_config()
    visible=store.event_config()["leaderboardVisible"]
    roster=competition["qualifiers"]
    entries=store.qualification_leaderboard()
    public_entries=[{key:value for key,value in row.items() if key not in ("objectKey","teamId","submissionId","jobId")}
                    for row in entries]
    return {
        "entries": public_entries if visible else [],
        "locked": not visible,
        "qualifierCount":competition["settings"]["qualifierCount"],
        "phase":competition["phase"],
        "qualifiedTeams":[row["team"] for row in roster],
        "evaluationGames": (len(config["seeds"]) * len(config["opponents"]) * len(config.get("sides", [0, 1]))
                            if competition["phase"]!="SETUP" else
                            competition["settings"]["referenceCount"] * competition["settings"]["qualificationSeedCount"] * 2),
        "sideSwapped": set(config.get("sides", [])) == {0, 1},
    }


def _replay_path(replay_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", replay_id):
        raise HTTPException(status_code=400, detail="Invalid replay identifier.")
    path = REPLAY_DIR / f"{replay_id}.json"
    if not path.is_file():
        try:
            payload = objects.get_bytes(f"replays/{replay_id}.json")
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
        except FileNotFoundError:
            pass
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Replay not found.")
    return path


@app.get("/replays/{replay_id}/analytics")
def replay_analytics(replay_id: str):
    return analyze_replay(_replay_path(replay_id))


@app.get("/replays/{replay_id}/frame/{step}")
def get_replay_frame(replay_id: str, step: int):
    return replay_frame(_replay_path(replay_id), step)


@app.post("/register")
async def register_player(
    request: Request,
    username: str = Form(...),
    agent: UploadFile = File(...),
):
    _require_event_action("upload")
    if store.competition()["phase"]!="QUALIFICATION_OPEN":
        raise HTTPException(status_code=423,detail="Round 1 registration is not open.")
    state=store.get_tournament_state(create_initial_state())
    if state["status"] not in ("registration", "finished", "champion", "error"):
        raise HTTPException(status_code=403,detail="Registration is currently closed because a tournament is starting or active.")

    username = username.strip()
    session = require_team(request, username)
    username = session["team"]
    if any(name.casefold() == username.casefold() for name in state.get("registeredPlayers", [])):
        raise HTTPException(status_code=409, detail="This team is already registered. Use Bot Lab to upload a new version.")
    _require_upload_policy(session)
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty.")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise HTTPException(
            status_code=400,
            detail="Username can contain only letters, numbers, '_' and '-'."
        )

    if not agent.filename:
        raise HTTPException(status_code=400, detail="No agent file uploaded.")

    _require_agent_filename(agent.filename)

    # Read and validate agent code
    try:
        content = await agent.read(MAX_UPLOAD_BYTES + 1)
        if len(content)>MAX_UPLOAD_BYTES:raise HTTPException(status_code=413,detail="Agent file exceeds the configured upload limit.")
        if not content:raise HTTPException(status_code=400,detail="Agent file is empty.")
        source_text = content.decode("utf-8")
        validate_agent_source(source_text)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Agent file must be valid UTF-8 encoded text.")
    except AgentValidationError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {e}")

    object_key=f"submissions/team_{session['teamId']}/{uuid4().hex}/agent.py"
    objects.put_bytes(object_key,source_text.encode("utf-8"),"text/x-python")
    try:submission=store.create_submission(username,object_key,valid=True)
    except ValueError as exc:
        objects.delete_prefix(object_key)
        raise HTTPException(status_code=429,detail=str(exc)) from exc
    try:state=store.add_tournament_player(username,create_initial_state(),
        limit=store.event_config()["registrationCapacity"])
    except ValueError as exc:
        if store.discard_unqueued_submission(submission["id"]):
            objects.delete_prefix(object_key)
        raise HTTPException(status_code=409,detail=str(exc)) from exc
    with state_lock:tournament_state.clear();tournament_state.update(state)

    return {
        "success": True,
        "message": f"Player '{username}' registered successfully.",
        "player": {
            "username": username,
            "version": submission["version"],
        },
        "submissionId": submission["id"],
        "job": None,
        "status": "registered",
    }


@app.get("/tournament/status")
def get_tournament_status():
    state=store.get_tournament_state(create_initial_state())
    def redact(value):
        if isinstance(value,dict):return {k:redact(v) for k,v in value.items() if k not in {"seed","filePath","player1File","player2File"}}
        if isinstance(value,list):return [redact(item) for item in value]
        return value
    return redact(state)
