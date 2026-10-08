"""Team credentials and short-lived browser presence, kept out of public metrics."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.services.queueing import redis_connection
from backend.services.storage import store

router = APIRouter(prefix="/api/participants", tags=["participants"])
COOKIE = "farmcraft_participant"
PRESENCE_SET = "arena:participant:sessions"


def hash_access_code(code: str) -> str:
    salt = secrets.token_hex(18)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 310_000).hex()
    return f"pbkdf2_sha256$310000${salt}${digest}"


def verify_access_code(code: str, encoded: str | None) -> bool:
    try:
        kind, iterations, salt, expected = (encoded or "").split("$", 3)
        if kind != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _session_key(token: str) -> str:
    return "arena:participant:session:" + hashlib.sha256(token.encode()).hexdigest()


def _device_label(user_agent: str) -> str:
    # Coarse browser and OS only; no fingerprint or raw user agent is retained.
    browser = next((name for marker, name in (("Edg/", "Edge"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if marker in user_agent), "Browser")
    system = next((name for marker, name in (("Windows", "Windows"), ("Macintosh", "macOS"), ("Android", "Android"), ("iPhone", "iOS"), ("Linux", "Linux")) if marker in user_agent), "Other")
    return f"{browser} / {system}"


class Credentials(BaseModel):
    team: str = Field(min_length=1, max_length=32)


class RecoveryCredentials(BaseModel):
    team: str = Field(min_length=1, max_length=32)
    recoveryCode: str = Field(min_length=12, max_length=128)


class Heartbeat(BaseModel):
    idle: bool = False
    latencyMs: float | None = Field(default=None, ge=0, le=10_000)


class StrategySelection(BaseModel):
    missionId: str


MISSION_IDS = {"core", "crop_economics", "market", "workforce", "capital", "livestock", "trading", "opponent", "optimizer"}


def current_session(request: Request, token: str | None = None) -> dict:
    token = token or request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Team sign-in required.")
    payload = redis_connection().get(_session_key(token))
    if not payload:
        raise HTTPException(401, "Team session expired.")
    session = json.loads(payload)
    identity = store.team_identity(int(session.get("teamId", 0)))
    if not identity:
        raise HTTPException(401, "Team session expired. Ask the organizer for recovery if needed.")
    if identity["blocked"]:
        raise HTTPException(423, "Your team has been blocked by an organizer.")
    if identity["suspendedReason"]:
        raise HTTPException(423, "Your team is temporarily suspended. Contact an organizer.")
    if identity["sessionVersion"] != session.get("sessionVersion"):
        raise HTTPException(401, "Your session has been ended by an organizer. Contact them if you need access.")
    session["team"] = identity["team"]
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not hmac.compare_digest(request.headers.get("x-participant-csrf", ""), session["csrf"]):
            raise HTTPException(403, "Team request token is missing or invalid.")
    return session


def team_sessions(team_id: int) -> list[dict]:
    """Return opaque session references; never reveal bearer tokens."""
    connection = redis_connection()
    rows = []
    for key in connection.scan_iter(match="arena:participant:session:*"):
        payload = connection.get(key)
        if not payload:
            continue
        session = json.loads(payload)
        if session.get("teamId") != team_id:
            continue
        reference = key.decode() if isinstance(key, bytes) else key
        rows.append({"id": reference.rsplit(":", 1)[-1], "device": session.get("device"),
                     "createdAt": datetime.fromtimestamp(session["created"], timezone.utc).isoformat(),
                     "lastSeen": datetime.fromtimestamp(session["seen"], timezone.utc).isoformat(),
                     "idle": session.get("idle", False)})
    return sorted(rows, key=lambda row: row["lastSeen"], reverse=True)


def revoke_session(team_id: int, session_id: str) -> bool:
    if not re.fullmatch(r"[a-f0-9]{64}", session_id):
        return False
    connection = redis_connection()
    key = "arena:participant:session:" + session_id
    payload = connection.get(key)
    if not payload or json.loads(payload).get("teamId") != team_id:
        return False
    with connection.pipeline() as pipe:
        pipe.delete(key)
        pipe.zrem(PRESENCE_SET, key)
        pipe.execute()
    return True


def revoke_all_sessions(team_id: int) -> int:
    sessions = team_sessions(team_id)
    return sum(revoke_session(team_id, row["id"]) for row in sessions)


def require_team(request: Request, team: str) -> dict:
    session = current_session(request)
    identity = store.team_identity_by_name(team)
    if not identity or session["teamId"] != identity["id"]:
        raise HTTPException(403, "This team belongs to another session.")
    return session


def limit_operation(session: dict, operation: str, maximum: int, seconds: int = 60) -> None:
    connection = redis_connection()
    key = f"arena:rate:{operation}:{session['team'].casefold()}"
    with connection.pipeline() as pipe:
        pipe.incr(key)
        pipe.expire(key, seconds, nx=True)
        count, _ = pipe.execute()
    if count > maximum:
        raise HTTPException(429, "Too many requests for this team. Please wait before trying again.")


@router.post("/session")
def sign_in(body: Credentials, request: Request, response: Response):
    team = body.team.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", team):
        raise HTTPException(400, "Team name can contain letters, numbers, '_' and '-'.")
    connection = redis_connection()
    source = request.client.host if request.client else "unknown"
    source_key = "arena:auth:source:" + hashlib.sha256(source.encode()).hexdigest()
    source_count = connection.incr(source_key)
    if source_count == 1:
        connection.expire(source_key, 300)
    if source_count > 300:
        raise HTTPException(429, "Too many sign-in attempts from this connection.")
    throttle = f"arena:auth:fail:{team.casefold()}"
    if int(connection.get(throttle) or 0) >= 8:
        raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")
    try:
        identity = store.register_team(team, int(os.getenv("MAX_PARTICIPANTS", "100")))
    except ValueError as exc:
        failures = connection.incr(throttle)
        if failures == 1:
            connection.expire(throttle, 300)
        raise HTTPException(409, str(exc)) from exc
    connection.delete(throttle)
    return _create_session(identity, request, response)


def _create_session(identity: dict, request: Request, response: Response) -> dict:
    connection = redis_connection()
    token = secrets.token_urlsafe(32)
    now = time.time()
    session = {"team": identity["team"], "teamId": identity["id"], "sessionVersion": identity["sessionVersion"],
               "csrf": secrets.token_urlsafe(24), "device": _device_label(request.headers.get("user-agent", "")),
               "created": now, "seen": now, "idle": False, "latencyMs": None, "reconnections": 0}
    lifetime = int(os.getenv("PARTICIPANT_SESSION_SECONDS", "28800"))
    key = _session_key(token)
    connection.setex(key, lifetime, json.dumps(session))
    connection.zadd(PRESENCE_SET, {key: now})
    public_url = os.getenv("PUBLIC_BASE_URL", "")
    production = os.getenv("APP_ENV", "development").lower() in ("production", "prod")
    response.set_cookie(COOKIE, token, httponly=True, secure=production or public_url.startswith("https://") or request.url.scheme == "https",
                        samesite="none" if production else "lax", max_age=lifetime, path="/")
    return {"team": identity["team"], "teamId": identity["id"], "csrfToken": session["csrf"],
            "heartbeatIntervalSeconds": int(os.getenv("PARTICIPANT_HEARTBEAT_SECONDS", "15"))}


@router.post("/recover")
def recover(body: RecoveryCredentials, request: Request, response: Response):
    team = body.team.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", team):
        raise HTTPException(400, "Invalid team name.")
    connection = redis_connection()
    source = request.client.host if request.client else "unknown"
    throttle = "arena:auth:recovery:" + hashlib.sha256((source + ":" + team.casefold()).encode()).hexdigest()
    count = connection.incr(throttle)
    if count == 1:
        connection.expire(throttle, 300)
    if count > 8:
        raise HTTPException(429, "Too many recovery attempts. Try again in five minutes.")
    identity = store.consume_team_recovery(team, hashlib.sha256(body.recoveryCode.encode()).hexdigest())
    if not identity:
        raise HTTPException(401, "Recovery code is invalid or expired.")
    connection.delete(throttle)
    return _create_session(identity, request, response)


@router.get("/session")
def session_status(request: Request):
    session = current_session(request)
    return {"team": session["team"], "teamId": session["teamId"], "csrfToken": session["csrf"],
            "heartbeatIntervalSeconds": int(os.getenv("PARTICIPANT_HEARTBEAT_SECONDS", "15"))}


@router.get("/strategy")
def selected_strategy(request: Request):
    session = current_session(request)
    return {"teamId": session["teamId"], "missionId": store.team_strategy(session["teamId"])}


@router.put("/strategy")
def select_strategy(body: StrategySelection, request: Request):
    session = current_session(request)
    if body.missionId not in MISSION_IDS:
        raise HTTPException(400, "Unknown strategy.")
    store.set_team_strategy(session["teamId"], body.missionId)
    return {"teamId": session["teamId"], "missionId": body.missionId}


@router.post("/heartbeat")
def heartbeat(body: Heartbeat, request: Request, token: str | None = Cookie(default=None, alias=COOKIE)):
    session = current_session(request, token)
    now = time.time()
    offline_after = int(os.getenv("PARTICIPANT_OFFLINE_SECONDS", "60"))
    if now - session["seen"] > offline_after:
        session["reconnections"] += 1
    session["seen"] = now
    session["idle"] = body.idle
    session["latencyMs"] = round(body.latencyMs, 1) if body.latencyMs is not None else None
    connection = redis_connection()
    key = _session_key(token or "")
    lifetime = int(os.getenv("PARTICIPANT_SESSION_SECONDS", "28800"))
    connection.setex(key, lifetime, json.dumps(session))
    connection.zadd(PRESENCE_SET, {key: now})
    return {"status": "ok", "serverTime": datetime.now(timezone.utc).isoformat()}


@router.post("/logout")
def logout(request: Request, response: Response, token: str | None = Cookie(default=None, alias=COOKIE)):
    current_session(request, token)
    connection = redis_connection()
    connection.delete(_session_key(token or ""))
    response.delete_cookie(COOKIE, path="/")
    return {"status": "signed_out"}


def connected_devices() -> dict:
    now = time.time()
    offline_after = int(os.getenv("PARTICIPANT_OFFLINE_SECONDS", "60"))
    idle_after = int(os.getenv("PARTICIPANT_IDLE_SECONDS", "30"))
    connection = redis_connection()
    connection.zremrangebyscore(PRESENCE_SET, 0, now - 86400)
    records = []
    for key in connection.zrevrange(PRESENCE_SET, 0, 499):
        payload = connection.get(key)
        if not payload:
            connection.zrem(PRESENCE_SET, key)
            continue
        row = json.loads(payload)
        age = now - row["seen"]
        status = "offline" if age > offline_after else "idle" if row["idle"] or age > idle_after else "online"
        records.append({"team": row["team"], "device": row["device"], "status": status,
                        "lastSeen": datetime.fromtimestamp(row["seen"], timezone.utc).isoformat(),
                        "latencyMs": row["latencyMs"], "reconnections": row["reconnections"]})
    latencies = [r["latencyMs"] for r in records if r["latencyMs"] is not None and r["status"] != "offline"]
    return {"sessions": records, "activeSessions": sum(r["status"] != "offline" for r in records),
            "connectedTeams": len({r["team"].casefold() for r in records if r["status"] != "offline"}),
            "recentlyDisconnected": sum(r["status"] == "offline" for r in records),
            "reconnections": sum(r["reconnections"] for r in records),
            "averageLatencyMs": round(sum(latencies) / len(latencies), 1) if latencies else None}
