"""Transactional persistence for the arena.

PostgreSQL is the production database. SQLite remains a limited fallback for
unit tests and zero-config boot; Docker Compose supplies PostgreSQL normally.
"""
from __future__ import annotations

import json
import hmac
import hashlib
import secrets
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, case, create_engine, func, select, update, text, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "neural_coliseum.db"
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "timeout", "cancelled")

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    is_rehearsal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    access_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    recovery_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recovery_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    submissions: Mapped[list["Submission"]] = relationship(back_populates="team", cascade="all, delete-orphan")

class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("team_id", "version", name="uq_submission_team_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    validation_status: Mapped[str] = mapped_column(String(20))
    validation_errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    sandbox_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    official_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    runtime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    team: Mapped[Team] = relationship(back_populates="submissions")


class TeamStrategy(Base):
    __tablename__ = "team_strategies"
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class SandboxRun(Base):
    __tablename__ = "sandbox_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    opponent: Mapped[str] = mapped_column(String(80)); seed: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30)); winner: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bot_money: Mapped[float | None] = mapped_column(Float, nullable=True); opponent_money: Mapped[float | None] = mapped_column(Float, nullable=True)
    runtime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True); replay_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    status: Mapped[str] = mapped_column(String(30)); rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True); average_final_money: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_money_differential: Mapped[float | None] = mapped_column(Float, nullable=True)
    wins: Mapped[int | None] = mapped_column(Integer, nullable=True); ties: Mapped[int | None] = mapped_column(Integer, nullable=True)
    games: Mapped[int | None] = mapped_column(Integer, nullable=True); error: Mapped[str | None] = mapped_column(Text, nullable=True)

class SimulationJob(Base):
    __tablename__ = "simulation_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(30), index=True); queue_name: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True)
    opponent: Mapped[str | None] = mapped_column(String(80), nullable=True); seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}"); result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True); error_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    progress_current: Mapped[int | None] = mapped_column(Integer, nullable=True); progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True); attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("simulation_jobs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class TournamentSnapshot(Base):
    __tablename__ = "tournament_state"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    state_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class WorkerRecord(Base):
    __tablename__ = "workers"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    current_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    jobs_completed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class RemoteWorker(Base):
    __tablename__ = "remote_workers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="active")
    max_concurrency: Mapped[int] = mapped_column(Integer, default=2)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telemetry_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class WorkerRegistration(Base):
    __tablename__ = "worker_registrations"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class RemoteQueueMode(Base):
    __tablename__ = "remote_queue_modes"
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)

class RemoteControl(Base):
    __tablename__ = "remote_control"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class EventConfig(Base):
    __tablename__ = "event_config"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(String(30), default="DEVELOPMENT")
    uploads_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sandbox_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    official_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tournament_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    registrations_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    leaderboard_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    submission_limit: Mapped[int] = mapped_column(Integer, default=0)
    submission_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class AdminAudit(Base):
    __tablename__ = "admin_audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

class ActiveJobError(RuntimeError):
    pass

def _database_url(source: str | Path | None) -> str:
    if isinstance(source, Path): return f"sqlite:///{source.as_posix()}"
    configured = str(source or os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB.as_posix()}")
    if configured.startswith("postgres://"):
        return configured.replace("postgres://", "postgresql+psycopg://", 1)
    if configured.startswith("postgresql://"):
        return configured.replace("postgresql://", "postgresql+psycopg://", 1)
    return configured

def _iso(value: datetime | None) -> str | None:
    if value is None: return None
    if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")

def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes for timezone-aware columns; treat them as UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

class PlatformStore:
    def __init__(self, source: str | Path | None = None):
        self.database_url = _database_url(source)
        if self.database_url.startswith("sqlite:///"): Path(self.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine_options = {"pool_pre_ping": True, "connect_args": {"check_same_thread": False} if self.database_url.startswith("sqlite") else {}}
        if self.database_url.startswith("sqlite"): engine_options["poolclass"] = NullPool
        else: engine_options.update({"pool_size": 3, "max_overflow": 2, "pool_timeout": 10, "pool_recycle": 300})
        self.engine = create_engine(self.database_url, **engine_options)
        self._version_lock = threading.Lock()
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        if self.engine.dialect.name == "sqlite":
            with self.engine.begin() as connection:
                columns = {row[1] for row in connection.execute(text("PRAGMA table_info(submissions)"))}
                if columns and "object_key" not in columns:
                    connection.execute(text("ALTER TABLE submissions ADD COLUMN object_key TEXT"))
                    if "file_path" in columns: connection.execute(text("UPDATE submissions SET object_key = file_path WHERE object_key IS NULL"))
                team_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(teams)"))}
                if team_columns and "is_rehearsal" not in team_columns:
                    connection.execute(text("ALTER TABLE teams ADD COLUMN is_rehearsal BOOLEAN DEFAULT 0 NOT NULL"))
        # Existing event databases predate participant credentials. This additive
        # migration works for both SQLite and PostgreSQL without changing scores.
        with self.engine.begin() as connection:
            columns = {column["name"] for column in __import__("sqlalchemy").inspect(connection).get_columns("teams")}
            if "access_hash" not in columns:
                connection.execute(text("ALTER TABLE teams ADD COLUMN access_hash VARCHAR(255)"))
            if "session_version" not in columns:
                connection.execute(text("ALTER TABLE teams ADD COLUMN session_version INTEGER DEFAULT 0 NOT NULL"))
            if "recovery_hash" not in columns:
                connection.execute(text("ALTER TABLE teams ADD COLUMN recovery_hash VARCHAR(64)"))
            if "recovery_expires_at" not in columns:
                connection.execute(text("ALTER TABLE teams ADD COLUMN recovery_expires_at TIMESTAMP"))
            if "suspended_reason" not in columns:
                connection.execute(text("ALTER TABLE teams ADD COLUMN suspended_reason TEXT"))
            if "blocked" not in columns:
                connection.execute(text("ALTER TABLE teams ADD COLUMN blocked BOOLEAN DEFAULT FALSE NOT NULL"))
            event_columns = {column["name"] for column in __import__("sqlalchemy").inspect(connection).get_columns("event_config")}
            for name, definition in (("registrations_enabled", "BOOLEAN DEFAULT TRUE NOT NULL"),
                                     ("leaderboard_visible", "BOOLEAN DEFAULT TRUE NOT NULL"),
                                     ("submission_limit", "INTEGER DEFAULT 0 NOT NULL"),
                                     ("submission_cooldown_seconds", "INTEGER DEFAULT 0 NOT NULL")):
                if name not in event_columns:
                    connection.execute(text(f"ALTER TABLE event_config ADD COLUMN {name} {definition}"))
            duplicates = connection.execute(text("SELECT lower(username), count(*) FROM teams GROUP BY lower(username) HAVING count(*) > 1")).all()
            if not duplicates:
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_teams_username_ci ON teams (lower(username))"))
            job_columns = {column["name"] for column in __import__("sqlalchemy").inspect(connection).get_columns("simulation_jobs")}
            if "attempt_id" not in job_columns:
                connection.execute(text("ALTER TABLE simulation_jobs ADD COLUMN attempt_id VARCHAR(36)"))
            if "lease_expires_at" not in job_columns:
                connection.execute(text("ALTER TABLE simulation_jobs ADD COLUMN lease_expires_at TIMESTAMP"))
            worker_columns = {column["name"] for column in __import__("sqlalchemy").inspect(connection).get_columns("remote_workers")}
            if "max_concurrency" not in worker_columns:
                connection.execute(text("ALTER TABLE remote_workers ADD COLUMN max_concurrency INTEGER DEFAULT 2 NOT NULL"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_remote_workers_name_ci ON remote_workers (lower(name))"))
        self.reconcile_legacy_tournament_errors()

    def reconcile_legacy_tournament_errors(self) -> int:
        """Correct old tournament jobs that committed an error payload as success."""
        corrected = 0
        with self.session() as db:
            candidates = db.scalars(select(SimulationJob).where(
                SimulationJob.type == "tournament", SimulationJob.status == "completed",
                SimulationJob.result_json.is_not(None))).all()
            for job in candidates:
                try:
                    result = json.loads(job.result_json)
                except (TypeError, ValueError):
                    continue
                if not isinstance(result, dict) or not result.get("error"):
                    continue
                message = str(result["error"])[:8000]
                changed = db.execute(update(SimulationJob).where(
                    SimulationJob.id == job.id, SimulationJob.status == "completed").values(
                    status="failed", error=message, error_kind="TOURNAMENT_ERROR"))
                if changed.rowcount:
                    db.add(PipelineEvent(job_id=job.id, stage="result", status="failed",
                                         detail="Historical tournament error reconciled"))
                    corrected += 1
        return corrected

    @contextmanager
    def session(self):
        db = self.Session()
        try:
            yield db; db.commit()
        except Exception:
            db.rollback(); raise
        finally: db.close()

    def ping(self) -> bool:
        with self.session() as db: db.execute(select(1))
        return True

    def register_team_access(self, username: str, access_hash: str, limit: int = 100) -> bool:
        """Create a participant identity; existing teams need organizer migration."""
        with self._version_lock, self.session() as db:
            existing = db.scalar(select(Team).where(func.lower(Team.username) == username.lower()))
            if existing:
                return False
            count = int(db.scalar(select(func.count()).select_from(Team).where(Team.is_rehearsal.is_(False))) or 0)
            if count >= limit:
                raise ValueError("The participant limit has been reached.")
            db.add(Team(username=username, access_hash=access_hash, is_rehearsal=False))
            return True

    def team_access_hash(self, username: str) -> str | None:
        with self.session() as db:
            return db.scalar(select(Team.access_hash).where(func.lower(Team.username) == username.lower(), Team.is_rehearsal.is_(False)))

    def team_exists(self, username: str) -> bool:
        with self.session() as db:
            return db.scalar(select(Team.id).where(func.lower(Team.username) == username.lower())) is not None

    def team_identity(self, team_id: int) -> dict | None:
        with self.session() as db:
            team = db.get(Team, team_id)
            if not team or team.is_rehearsal:
                return None
            return {"id": team.id, "team": team.username, "sessionVersion": team.session_version or 0,
                    "createdAt": _iso(team.created_at), "suspendedReason": team.suspended_reason, "blocked": bool(team.blocked)}

    def team_identity_by_name(self, username: str) -> dict | None:
        with self.session() as db:
            teams = db.scalars(select(Team).where(func.lower(Team.username) == username.casefold(), Team.is_rehearsal.is_(False))).all()
            if len(teams) > 1:
                raise ValueError("This legacy team name is ambiguous; contact the organizer.")
            if not teams:
                return None
            team = teams[0]
            return {"id": team.id, "team": team.username, "sessionVersion": team.session_version or 0,
                    "createdAt": _iso(team.created_at), "suspendedReason": team.suspended_reason, "blocked": bool(team.blocked)}

    def register_team(self, username: str, limit: int = 100) -> dict:
        """Atomically claim a case-insensitive team name and return its stable ID."""
        try:
            with self._version_lock, self.session() as db:
                if self.engine.dialect.name == "postgresql":
                    db.execute(text("SELECT pg_advisory_xact_lock(78426135)"))
                cfg=db.get(EventConfig,1)
                if cfg and not cfg.registrations_enabled:
                    raise ValueError("New team registration is closed. Contact the organizer.")
                if db.scalar(select(Team.id).where(func.lower(Team.username) == username.casefold())):
                    raise ValueError("This team name is already registered. Ask the organizer for a one-time recovery code.")
                count = int(db.scalar(select(func.count()).select_from(Team).where(Team.is_rehearsal.is_(False))) or 0)
                if count >= limit:
                    raise ValueError("The participant limit has been reached.")
                team = Team(username=username, is_rehearsal=False, session_version=0)
                db.add(team)
                db.flush()
                return {"id": team.id, "team": team.username, "sessionVersion": 0, "createdAt": _iso(team.created_at)}
        except IntegrityError as exc:
            raise ValueError("This team name is already registered. Ask the organizer for a one-time recovery code.") from exc

    def issue_team_recovery(self, username: str, code_hash: str, expires_at: datetime) -> dict | None:
        with self.session() as db:
            teams = db.scalars(select(Team).where(func.lower(Team.username) == username.casefold(), Team.is_rehearsal.is_(False)).with_for_update()).all()
            if len(teams) > 1:
                raise ValueError("Multiple legacy teams share this name. Resolve the collision before recovery.")
            if not teams:
                return None
            team = teams[0]
            if team.blocked:
                raise ValueError("This team is blocked. Contact the organizer.")
            team.recovery_hash = code_hash
            team.recovery_expires_at = expires_at
            team.session_version = (team.session_version or 0) + 1
            return {"id": team.id, "team": team.username}

    def consume_team_recovery(self, username: str, code_hash: str) -> dict | None:
        with self.session() as db:
            teams = db.scalars(select(Team).where(func.lower(Team.username) == username.casefold(), Team.is_rehearsal.is_(False)).with_for_update()).all()
            if len(teams) != 1:
                return None
            team = teams[0]
            if team.blocked:
                return None
            if not team or not team.recovery_hash or not team.recovery_expires_at:
                return None
            if _as_utc(team.recovery_expires_at) < utc_now() or not hmac.compare_digest(team.recovery_hash, code_hash):
                return None
            team.recovery_hash = None
            team.recovery_expires_at = None
            team.session_version = (team.session_version or 0) + 1
            return {"id": team.id, "team": team.username, "sessionVersion": team.session_version,
                    "createdAt": _iso(team.created_at)}

    def set_team_state(self, team_id: int, *, blocked: bool | None = None,
                       suspended_reason: str | None = None, clear_suspension: bool = False) -> dict | None:
        with self.session() as db:
            team = db.get(Team, team_id)
            if not team or team.is_rehearsal:
                return None
            previous = {"blocked": bool(team.blocked), "suspendedReason": team.suspended_reason}
            if blocked is not None:
                team.blocked = blocked
            if clear_suspension:
                team.suspended_reason = None
            elif suspended_reason is not None:
                team.suspended_reason = suspended_reason[:500]
            if blocked or suspended_reason is not None:
                team.session_version = (team.session_version or 0) + 1
            return {"team": team.username, "teamId": team.id, "previous": previous,
                    "blocked": bool(team.blocked), "suspendedReason": team.suspended_reason}

    def revoke_team_sessions(self, team_id: int) -> bool:
        with self.session() as db:
            team = db.get(Team, team_id)
            if not team or team.is_rehearsal:
                return False
            team.session_version = (team.session_version or 0) + 1
            return True

    def team_strategy(self, team_id: int) -> str | None:
        with self.session() as db:
            row = db.get(TeamStrategy, team_id)
            return row.mission_id if row else None

    def set_team_strategy(self, team_id: int, mission_id: str) -> None:
        with self.session() as db:
            row = db.get(TeamStrategy, team_id)
            if row:
                row.mission_id = mission_id
            else:
                db.add(TeamStrategy(team_id=team_id, mission_id=mission_id))

    def set_team_access(self, username: str, access_hash: str) -> bool:
        with self.session() as db:
            team = db.scalar(select(Team).where(func.lower(Team.username) == username.lower(), Team.is_rehearsal.is_(False)))
            if not team:
                return False
            team.access_hash = access_hash
            return True

    def _team(self, db, username: str, *, lock: bool = False, rehearsal: bool = False) -> Team:
        stmt = select(Team).where(func.lower(Team.username) == username.lower())
        if lock and self.engine.dialect.name == "postgresql": stmt = stmt.with_for_update()
        team = db.scalar(stmt)
        if team:
            if rehearsal: team.is_rehearsal=True
            return team
        team = Team(username=username,is_rehearsal=rehearsal); db.add(team)
        try: db.flush()
        except IntegrityError:
            db.rollback(); team = db.scalar(select(Team).where(func.lower(Team.username) == username.lower()))
            if not team: raise
        return team

    @staticmethod
    def _submission_dict(item: Submission, username: str | None = None) -> dict:
        return {"id": item.id, "team_id": item.team_id, "username": username, "version": item.version,
                "object_key": item.object_key, "file_path": item.file_path, "created_at": _iso(item.created_at),
                "validation_status": item.validation_status, "validation_errors": item.validation_errors,
                "sandbox_score": item.sandbox_score, "official_score": item.official_score,
                "runtime_seconds": item.runtime_seconds, "is_active": bool(item.is_active)}

    def create_submission(self, username: str, object_key: str | Path, *, valid: bool, errors: str | None = None, rehearsal: bool = False) -> dict:
        with self._version_lock:
            return self._create_submission_locked(username, object_key, valid=valid, errors=errors, rehearsal=rehearsal)

    def _create_submission_locked(self, username: str, object_key: str | Path, *, valid: bool, errors: str | None = None, rehearsal: bool = False) -> dict:
        for attempt in range(3):
            try:
                with self.session() as db:
                    team = self._team(db, username, lock=True, rehearsal=rehearsal)
                    version = int(db.scalar(select(func.coalesce(func.max(Submission.version), 0)).where(Submission.team_id == team.id))) + 1
                    if not rehearsal:
                        cfg=db.get(EventConfig,1)
                        if cfg and cfg.submission_limit and version > cfg.submission_limit:
                            raise ValueError("This team has reached the upload limit.")
                        if cfg and cfg.submission_cooldown_seconds and version > 1:
                            latest=db.scalar(select(Submission.created_at).where(Submission.team_id==team.id)
                                             .order_by(Submission.created_at.desc()).limit(1))
                            if latest and (utc_now()-_as_utc(latest)).total_seconds()<cfg.submission_cooldown_seconds:
                                raise ValueError("Please wait before uploading another bot.")
                    item = Submission(team_id=team.id, version=version, object_key=str(object_key), file_path=str(object_key), validation_status="valid" if valid else "invalid", validation_errors=errors)
                    db.add(item); db.flush(); return self._submission_dict(item, team.username)
            except IntegrityError:
                if attempt == 2: raise
        raise RuntimeError("Could not allocate a submission version.")

    def get_submission(self, submission_id: int) -> dict | None:
        with self.session() as db:
            row = db.execute(select(Submission, Team.username).join(Team).where(Submission.id == submission_id)).first()
            return self._submission_dict(row[0], row[1]) if row else None

    def discard_unqueued_submission(self, submission_id: int) -> bool:
        """Roll back a just-created version when tournament roster admission loses a race."""
        with self.session() as db:
            item = db.get(Submission, submission_id)
            if not item or item.is_active:
                return False
            if db.scalar(select(SimulationJob.id).where(SimulationJob.submission_id == submission_id).limit(1)):
                return False
            db.delete(item)
            return True

    def list_submissions(self, username: str) -> list[dict]:
        with self.session() as db:
            rows = db.execute(select(Submission, Team.username).join(Team).where(func.lower(Team.username) == username.lower()).order_by(Submission.version.desc())).all()
            return [self._submission_dict(item, name) for item, name in rows]

    def current_submission(self, username: str) -> dict | None:
        items = self.list_submissions(username); return items[0] if items else None

    def activate_submission(self, username: str, submission_id: int) -> dict | None:
        with self.session() as db:
            row = db.execute(select(Submission, Team).join(Team).where(Submission.id == submission_id, func.lower(Team.username) == username.lower(), Submission.validation_status == "valid")).first()
            if not row: return None
            item, team = row; db.execute(update(Submission).where(Submission.team_id == team.id).values(is_active=False)); item.is_active = True; db.flush()
            return self._submission_dict(item, team.username)

    def record_sandbox(self, submission_id: int, result: dict) -> dict:
        with self.session() as db:
            db.add(SandboxRun(submission_id=submission_id, opponent=result["opponent"], seed=result["seed"], status=result["status"], winner=result.get("winner"), bot_money=result.get("botFinalMoney"), opponent_money=result.get("opponentFinalMoney"), runtime_seconds=result.get("runtimeSeconds"), replay_id=result.get("replayId"), error=result.get("error")))
            item = db.get(Submission, submission_id)
            if item: item.sandbox_score = result.get("botFinalMoney"); item.runtime_seconds = result.get("runtimeSeconds")
        return self.get_submission(submission_id)

    def last_sandbox(self, submission_id: int) -> dict | None:
        with self.session() as db:
            item = db.scalar(select(SandboxRun).where(SandboxRun.submission_id == submission_id).order_by(SandboxRun.id.desc()).limit(1))
            if not item: return None
            return {c.name: (_iso(getattr(item, c.name)) if isinstance(getattr(item, c.name), datetime) else getattr(item, c.name)) for c in SandboxRun.__table__.columns}

    def record_evaluation(self, submission_id: int, result: dict) -> dict:
        with self.session() as db:
            db.add(Evaluation(submission_id=submission_id, status=result.get("status", "complete"), rating=result.get("rating"), win_rate=result.get("winRate"), average_final_money=result.get("averageFinalMoney"), average_money_differential=result.get("averageMoneyDifferential"), wins=result.get("wins"), ties=result.get("ties"), games=result.get("games"), error=result.get("error")))
            item = db.get(Submission, submission_id)
            if item: item.official_score = result.get("rating")
        return self.get_submission(submission_id)

    def leaderboard(self) -> list[dict]:
        with self.session() as db:
            latest = select(Evaluation.submission_id.label("sid"), func.max(Evaluation.id).label("eid")).group_by(Evaluation.submission_id).subquery()
            rows = db.execute(select(Submission, Team, Evaluation).join(Team).join(latest, latest.c.sid == Submission.id).join(Evaluation, Evaluation.id == latest.c.eid).where(Submission.is_active.is_(True), Submission.official_score.is_not(None), Team.is_rehearsal.is_(False)).order_by(Submission.official_score.desc(), Team.username.asc())).all(); entries=[]
            for rank, (submission, team, ev) in enumerate(rows, 1):
                entries.append({"rank": rank, "team": team.username, "version": submission.version, "rating": submission.official_score, "win_rate": ev.win_rate if ev else 0, "average_final_money": ev.average_final_money if ev else 0, "games": ev.games if ev else 0, "created_at": _iso(ev.created_at) if ev else None})
            return entries

    def leaderboard_entry(self, username: str) -> dict | None:
        with self.session() as db:
            row = db.execute(select(Submission, Team, Evaluation).join(Team).join(Evaluation, Evaluation.submission_id == Submission.id).where(func.lower(Team.username) == username.lower(), Team.is_rehearsal.is_(False), Submission.is_active.is_(True), Submission.official_score.is_not(None)).order_by(Evaluation.id.desc()).limit(1)).first()
            if not row:return None
            submission,team,ev=row
            rank=1+int(db.scalar(select(func.count()).select_from(Submission).join(Team).where(Team.is_rehearsal.is_(False),Submission.is_active.is_(True),Submission.official_score>submission.official_score)) or 0)
            return {"rank":rank,"team":team.username,"version":submission.version,"rating":submission.official_score,"win_rate":ev.win_rate,"average_final_money":ev.average_final_money,"games":ev.games,"created_at":_iso(ev.created_at)}

    def sandbox_count(self, username: str) -> int:
        with self.session() as db: return int(db.scalar(select(func.count(SandboxRun.id)).join(Submission).join(Team).where(func.lower(Team.username) == username.lower())) or 0)

    def summary(self, username: str) -> dict:
        submissions=self.list_submissions(username); current=submissions[0] if submissions else None; active=next((x for x in submissions if x["is_active"]),None)
        scored=[x["sandbox_score"] for x in submissions if x["sandbox_score"] is not None]; entry=self.leaderboard_entry(username)
        return {"team":username,"currentSubmission":current,"activeSubmission":active,"currentVersion":f"v{current['version']}" if current else None,"validationStatus":current["validation_status"] if current else "not_uploaded","lastTest":self.last_sandbox(current["id"]) if current else None,"bestScore":max(scored) if scored else None,"submissionCount":len(submissions),"sandboxRunCount":self.sandbox_count(username),"leaderboardRank":entry["rank"] if entry else None,"winRate":entry["win_rate"] if entry else None,"jobs":self.list_jobs(username,10)}

    def create_job(self, username: str | None, job_type: str, *, submission_id: int | None=None, opponent: str | None=None, seed: int | None=None, payload: dict | None=None, progress_total: int | None=None, max_attempts: int | None=None) -> dict:
        if max_attempts is None:
            max_attempts = max(1, int(os.getenv("MAX_INFRASTRUCTURE_RETRIES", "2")) + 1)
        queue_name={"tournament":"tournament","official":"official"}.get(job_type,"sandbox")
        with self.session() as db:
            team=self._team(db,username,lock=True) if username else None
            if team and job_type in ("sandbox","official"):
                default_limit="1"
                limit=int(os.getenv(f"MAX_ACTIVE_{job_type.upper()}_PER_TEAM",default_limit))
                existing=int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.team_id==team.id,SimulationJob.type==job_type,SimulationJob.status.in_(ACTIVE_STATUSES))) or 0)
                if existing>=limit: raise ActiveJobError(f"You already have the maximum active {job_type} jobs.")
            job=SimulationJob(id=str(uuid4()),team_id=team.id if team else None,type=job_type,queue_name=queue_name,status="queued",submission_id=submission_id,opponent=opponent,seed=seed,payload_json=json.dumps(payload or {}),progress_current=0 if progress_total else None,progress_total=progress_total,max_attempts=max_attempts)
            db.add(job);db.flush()
            db.add(PipelineEvent(job_id=job.id, stage="queue", status="waiting", detail="Job saved and awaiting dispatch"))
            return self._job_dict(job,team.username if team else None)

    def pipeline_event(self, job_id: str, stage: str, status: str, detail: str | None = None) -> None:
        with self.session() as db:
            if db.get(SimulationJob, job_id):
                db.add(PipelineEvent(job_id=job_id, stage=stage[:50], status=status[:20],
                                     detail=detail[:500] if detail else None))

    def pipeline_events(self, job_id: str) -> list[dict]:
        with self.session() as db:
            rows = db.scalars(select(PipelineEvent).where(PipelineEvent.job_id == job_id)
                              .order_by(PipelineEvent.id)).all()
            return [{"id": row.id, "stage": row.stage, "status": row.status,
                     "detail": row.detail, "at": _iso(row.created_at)} for row in rows]

    def latest_pipeline_stages(self, job_ids: list[str]) -> dict[str, dict]:
        if not job_ids:
            return {}
        with self.session() as db:
            newest = (select(func.max(PipelineEvent.id).label("id"))
                      .where(PipelineEvent.job_id.in_(job_ids))
                      .group_by(PipelineEvent.job_id).subquery())
            rows = db.scalars(select(PipelineEvent).join(newest, PipelineEvent.id == newest.c.id)).all()
            return {row.job_id: {"stage": row.stage, "status": row.status,
                                 "detail": row.detail, "at": _iso(row.created_at)} for row in rows}

    def total_submissions(self) -> int:
        with self.session() as db:
            return int(db.scalar(select(func.count()).select_from(Submission)) or 0)

    @staticmethod
    def _job_dict(job: SimulationJob, username: str | None=None) -> dict:
        payload=json.loads(job.payload_json or "{}")
        return {"id":job.id,"team":username,"type":job.type,"queue":job.queue_name,"status":job.status,"createdAt":_iso(job.created_at),"startedAt":_iso(job.started_at),"completedAt":_iso(job.completed_at),"submissionId":job.submission_id,"opponent":job.opponent,"seed":job.seed,"result":json.loads(job.result_json) if job.result_json else None,"error":job.error,"errorKind":job.error_kind,"progressCurrent":job.progress_current,"progressTotal":job.progress_total,"worker":job.worker_id,"attempts":job.attempts,"retryCount":int(payload.get("_adminRetryCount",0))}

    def get_job(self, job_id: str) -> dict | None:
        with self.session() as db:
            row=db.execute(select(SimulationJob,Team.username).outerjoin(Team).where(SimulationJob.id==job_id)).first();return self._job_dict(row[0],row[1]) if row else None

    def job_payload(self, job_id: str) -> dict:
        with self.session() as db:
            job=db.get(SimulationJob,job_id);return json.loads(job.payload_json) if job else {}

    def freeze_remote_sources(self, job_id: str, sources: list[dict]) -> None:
        with self.session() as db:
            job = db.get(SimulationJob, job_id)
            if job and job.status == "running" and job.type == "tournament":
                payload = json.loads(job.payload_json or "{}")
                payload["_remoteSources"] = sources
                job.payload_json = json.dumps(payload)

    @staticmethod
    def _credential_hash(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    def issue_worker_registration(self, minutes: int = 15) -> str:
        token = secrets.token_urlsafe(32)
        with self.session() as db:
            db.add(WorkerRegistration(token_hash=self._credential_hash(token),
                                      expires_at=utc_now()+timedelta(minutes=minutes)))
        return token

    def register_remote_worker(self, token: str, name: str, version: str) -> dict | None:
        now = utc_now()
        secret = secrets.token_urlsafe(48)
        with self.session() as db:
            query = select(WorkerRegistration).where(WorkerRegistration.token_hash == self._credential_hash(token))
            if self.engine.dialect.name == "postgresql": query = query.with_for_update()
            registration = db.scalar(query)
            if not registration or registration.used_at or _as_utc(registration.expires_at) <= now:
                return None
            existing = db.scalar(select(RemoteWorker).where(func.lower(RemoteWorker.name) == name.lower()))
            if existing and existing.status != "revoked":
                return None
            if existing:
                existing.credential_hash = self._credential_hash(secret)
                existing.status = "active"
                existing.version = version
                existing.last_heartbeat = now
                worker_id = existing.id
            else:
                worker_id = str(uuid4())
                db.add(RemoteWorker(id=worker_id, name=name, version=version,
                                    credential_hash=self._credential_hash(secret), last_heartbeat=now))
            registration.used_at = now
            return {"workerId": worker_id, "credential": secret}

    def authenticate_remote_worker(self, worker_id: str, credential: str) -> dict | None:
        with self.session() as db:
            worker = db.get(RemoteWorker, worker_id)
            if not worker or worker.status == "revoked" or not hmac.compare_digest(
                worker.credential_hash, self._credential_hash(credential)):
                return None
            return {"id": worker.id, "name": worker.name, "version": worker.version,
                    "status": worker.status}

    def rotate_remote_worker(self, worker_id: str) -> str | None:
        secret = secrets.token_urlsafe(48)
        with self.session() as db:
            worker = db.get(RemoteWorker, worker_id)
            if not worker or worker.status == "revoked": return None
            worker.credential_hash = self._credential_hash(secret)
        return secret

    def set_remote_worker_status(self, worker_id: str, status: str) -> bool:
        with self.session() as db:
            worker = db.get(RemoteWorker, worker_id)
            if not worker or (worker.status == "revoked" and status != "revoked"): return False
            worker.status = status
            return True

    def remote_workers(self) -> list[dict]:
        with self.session() as db:
            rows = db.scalars(select(RemoteWorker).order_by(RemoteWorker.created_at.desc())).all()
            now = utc_now()
            return [{"id": w.id, "name": w.name, "version": w.version,
                     "status": "offline" if w.status == "active" and (not w.last_heartbeat or
                         (now-_as_utc(w.last_heartbeat)).total_seconds() > 60) else w.status,
                     "lastHeartbeat": _iso(w.last_heartbeat), "maxConcurrency": w.max_concurrency,
                     "telemetry": json.loads(w.telemetry_json or "{}")}
                    for w in rows]

    def remote_worker_metrics(self) -> dict:
        items = self.remote_workers()
        with self.session() as db:
            for item in items:
                counts = dict(db.execute(select(SimulationJob.status, func.count()).where(
                    SimulationJob.worker_id == item["id"]).group_by(SimulationJob.status)).all())
                current = db.scalar(select(SimulationJob.id).where(
                    SimulationJob.worker_id == item["id"], SimulationJob.status == "running").limit(1))
                finished = db.execute(select(SimulationJob.started_at, SimulationJob.completed_at).where(
                    SimulationJob.worker_id == item["id"], SimulationJob.status == "completed",
                    SimulationJob.started_at.is_not(None), SimulationJob.completed_at.is_not(None))
                    .order_by(SimulationJob.completed_at.desc()).limit(100)).all()
                durations = [(_as_utc(end)-_as_utc(start)).total_seconds() for start, end in finished]
                item.update({"currentJobId": current, "jobsCompleted": counts.get("completed", 0),
                             "jobsFailed": counts.get("failed", 0) + counts.get("timeout", 0),
                             "averageEvaluationSeconds": round(sum(durations)/len(durations), 1) if durations else None})
                if item["status"] == "active": item["status"] = "busy" if current else "idle"
        return {"total": len(items), "busy": sum(x["status"] == "busy" for x in items),
                "idle": sum(x["status"] == "idle" for x in items),
                "offline": sum(x["status"] == "offline" for x in items), "items": items}

    def set_remote_concurrency(self, worker_id: str, count: int) -> bool:
        with self.session() as db:
            worker = db.get(RemoteWorker, worker_id)
            if not worker: return False
            worker.max_concurrency = count
            return True

    def remote_queue_modes(self) -> dict[str, bool]:
        with self.session() as db:
            return {row.name: row.paused for row in db.scalars(select(RemoteQueueMode)).all()}

    def worker_registration_enabled(self) -> bool:
        with self.session() as db:
            row = db.get(RemoteControl, 1)
            return bool(row.registration_enabled) if row else os.getenv("WORKER_REGISTRATION_ENABLED", "1") == "1"

    def set_worker_registration_enabled(self, enabled: bool) -> None:
        with self.session() as db:
            row = db.get(RemoteControl, 1)
            if row: row.registration_enabled = enabled
            else: db.add(RemoteControl(id=1, registration_enabled=enabled))

    def set_remote_queue_mode(self, name: str, paused: bool) -> None:
        with self.session() as db:
            row = db.get(RemoteQueueMode, name)
            if row: row.paused = paused
            else: db.add(RemoteQueueMode(name=name, paused=paused))

    def remote_heartbeat(self, worker_id: str, telemetry: dict, job_id: str | None = None,
                         attempt_id: str | None = None, lease_seconds: int = 90) -> dict:
        with self.session() as db:
            worker = db.get(RemoteWorker, worker_id)
            if not worker or worker.status == "revoked": return {"valid": False, "cancel": True}
            worker.last_heartbeat = utc_now()
            worker.telemetry_json = json.dumps(telemetry)[:4000]
            if not job_id: return {"valid": True, "cancel": worker.status == "revoked"}
            job = db.get(SimulationJob, job_id)
            valid = bool(job and job.status == "running" and job.worker_id == worker_id
                         and job.attempt_id == attempt_id and job.lease_expires_at
                         and _as_utc(job.lease_expires_at) > utc_now()
                         and worker.status in ("active", "paused", "draining"))
            if valid:
                job.heartbeat_at = utc_now()
                job.lease_expires_at = utc_now()+timedelta(seconds=lease_seconds)
            return {"valid": valid, "cancel": not valid}

    def recover_remote_leases(self) -> int:
        now = utc_now()
        with self.session() as db:
            query = select(SimulationJob).where(SimulationJob.status == "running",
                         SimulationJob.attempt_id.is_not(None), SimulationJob.lease_expires_at < now)
            if self.engine.dialect.name == "postgresql": query = query.with_for_update(skip_locked=True)
            rows = db.scalars(query).all()
            for job in rows:
                if job.type == "tournament" or job.attempts >= job.max_attempts:
                    job.status = "failed"; job.error = "Worker lease expired; organizer review required." if job.type == "tournament" else "Worker lease expired."
                    job.error_kind = "WORKER_FAILURE"; job.completed_at = now
                else:
                    job.status = "queued"; job.started_at = None; job.worker_id = None
                job.attempt_id = None; job.lease_expires_at = None
                db.add(PipelineEvent(job_id=job.id, stage="worker", status="failed" if job.status == "failed" else "waiting",
                                     detail="Worker lease expired"))
                if job.type == "tournament":
                    snapshot = db.get(TournamentSnapshot, 1)
                    if snapshot:
                        state = json.loads(snapshot.state_json)
                        state.update({"status": "error", "isLive": False,
                                      "error": "Tournament worker lease expired.",
                                      "message": "Organizer review is required before starting another bracket."})
                        snapshot.state_json = json.dumps(state)
            return len(rows)

    def claim_remote_job(self, worker_id: str, version: str, lease_seconds: int = 90) -> dict | None:
        with self.session() as db:
            worker_query = select(RemoteWorker).where(RemoteWorker.id == worker_id)
            if self.engine.dialect.name == "postgresql": worker_query = worker_query.with_for_update()
            worker = db.scalar(worker_query)
            if not worker or worker.status != "active" or worker.version != version:
                return None
            active = db.scalar(select(func.count()).select_from(SimulationJob).where(
                SimulationJob.worker_id == worker_id, SimulationJob.status == "running")) or 0
            if active >= worker.max_concurrency:
                return None
            priority = case((SimulationJob.type == "tournament", 0),
                            (SimulationJob.type == "official", 1), else_=2)
            paused = [row.name for row in db.scalars(select(RemoteQueueMode).where(RemoteQueueMode.paused.is_(True))).all()]
            query = select(SimulationJob).where(SimulationJob.status == "queued")
            if paused: query = query.where(SimulationJob.queue_name.not_in(paused))
            query = query.order_by(priority, SimulationJob.created_at)
            if self.engine.dialect.name == "postgresql": query = query.with_for_update(skip_locked=True)
            job = db.scalar(query.limit(1))
            if not job: return None
            now = utc_now()
            job.status = "running"; job.worker_id = worker_id; job.attempts += 1
            job.attempt_id = str(uuid4()); job.started_at = now; job.heartbeat_at = now
            job.lease_expires_at = now+timedelta(seconds=lease_seconds)
            worker.last_heartbeat = now
            db.add(PipelineEvent(job_id=job.id, stage="worker", status="running", detail=worker.name[:120]))
            team = db.get(Team, job.team_id) if job.team_id else None
            return {**self._job_dict(job, team.username if team else None), "attemptId": job.attempt_id,
                    "evaluatorVersion": version}

    def remote_attempt_valid(self, job_id: str, worker_id: str, attempt_id: str) -> bool:
        with self.session() as db:
            job = db.get(SimulationJob, job_id)
            return bool(job and job.status == "running" and job.worker_id == worker_id
                        and job.attempt_id == attempt_id and job.lease_expires_at
                        and _as_utc(job.lease_expires_at) > utc_now())

    def fail_remote_attempt(self, job_id: str, worker_id: str, attempt_id: str,
                            error: str, error_kind: str) -> bool:
        with self.session() as db:
            query = select(SimulationJob).where(SimulationJob.id == job_id)
            if self.engine.dialect.name == "postgresql": query = query.with_for_update()
            job = db.scalar(query)
            if not job or job.status != "running" or job.worker_id != worker_id or job.attempt_id != attempt_id \
               or not job.lease_expires_at or _as_utc(job.lease_expires_at) <= utc_now():
                return False
            retryable = error_kind in {"WORKER_FAILURE", "ENGINE_FAILURE", "STORAGE_FAILURE",
                                       "DATABASE_FAILURE", "INFRASTRUCTURE_TIMEOUT"} or error_kind.startswith("INFRASTRUCTURE")
            if job.type != "tournament" and retryable and job.attempts < job.max_attempts:
                job.status = "queued"; job.started_at = None; job.worker_id = None
                job.attempt_id = None; job.lease_expires_at = None
                stage_status = "waiting"
            else:
                job.status = "failed"; job.error = error[:8000]; job.error_kind = error_kind
                job.completed_at = utc_now(); stage_status = "failed"
                if job.type == "tournament":
                    snapshot = db.get(TournamentSnapshot, 1)
                    if snapshot:
                        state = json.loads(snapshot.state_json)
                        state.update({"status": "error", "isLive": False, "error": error[:1000],
                                      "message": "Tournament job failed. Organizer review is required."})
                        snapshot.state_json = json.dumps(state)
            db.add(PipelineEvent(job_id=job.id, stage="execution", status=stage_status, detail=error[:500]))
            return True

    def list_jobs(self, username: str, limit: int=50) -> list[dict]:
        with self.session() as db:
            rows=db.execute(select(SimulationJob,Team.username).join(Team).where(func.lower(Team.username)==username.lower()).order_by(SimulationJob.created_at.desc()).limit(limit)).all();return [self._job_dict(j,n) for j,n in rows]

    def mark_job_running(self, job_id: str, worker_id: str) -> dict | None:
        with self.session() as db:
            now = utc_now()
            changed = db.execute(update(SimulationJob).where(SimulationJob.id == job_id, SimulationJob.status == "queued")
                                 .values(status="running", started_at=now, heartbeat_at=now,
                                         worker_id=worker_id, attempts=SimulationJob.attempts + 1))
            if changed.rowcount != 1:
                return None
            db.add(PipelineEvent(job_id=job_id, stage="worker", status="running", detail=worker_id))
        return self.get_job(job_id)

    def update_job_progress(self, job_id: str, current: int, total: int | None=None):
        with self.session() as db:
            job=db.get(SimulationJob,job_id)
            if job and job.status=="running":job.progress_current=current;job.progress_total=total if total is not None else job.progress_total;job.heartbeat_at=utc_now()

    def touch_job_heartbeat(self, job_id: str) -> None:
        with self.session() as db:
            db.execute(update(SimulationJob).where(SimulationJob.id == job_id, SimulationJob.status == "running")
                       .values(heartbeat_at=utc_now()))

    def requeue_running_job(self, job_id: str) -> bool:
        """Release a failed attempt before RQ schedules its retry."""
        with self.session() as db:
            job = db.get(SimulationJob, job_id)
            if not job or job.status != "running" or job.type == "tournament" or job.attempts >= job.max_attempts:
                return False
            job.status = "queued"
            job.started_at = None
            job.heartbeat_at = None
            job.worker_id = None
            return True

    def finish_job(self, job_id: str, result: dict):
        with self.session() as db:
            job=db.get(SimulationJob,job_id)
            if job and job.status not in TERMINAL_STATUSES:
                job.status="completed";job.result_json=json.dumps(result);job.completed_at=utc_now();job.heartbeat_at=utc_now();job.progress_current=job.progress_total if job.progress_total is not None else job.progress_current

    def commit_job_result(self, job_id: str, result: dict, *, error: str | None = None,
                          error_kind: str | None = None, worker_id: str | None = None,
                          attempt_id: str | None = None) -> bool:
        """Save the result and terminal state in one transaction, once per job."""
        with self.session() as db:
            query = select(SimulationJob).where(SimulationJob.id == job_id)
            if self.engine.dialect.name == "postgresql":
                query = query.with_for_update()
            job = db.scalar(query)
            if not job or job.status != "running":
                return False
            if worker_id is not None and (job.worker_id != worker_id or job.attempt_id != attempt_id
                                          or not job.lease_expires_at or _as_utc(job.lease_expires_at) <= utc_now()):
                return False
            submission = db.get(Submission, job.submission_id) if job.submission_id else None
            if job.type == "sandbox" and submission:
                db.add(SandboxRun(submission_id=submission.id, opponent=result["opponent"], seed=result["seed"],
                                  status=result["status"], winner=result.get("winner"), bot_money=result.get("botFinalMoney"),
                                  opponent_money=result.get("opponentFinalMoney"), runtime_seconds=result.get("runtimeSeconds"),
                                  replay_id=result.get("replayId"), error=result.get("error")))
                submission.sandbox_score = result.get("botFinalMoney")
                submission.runtime_seconds = result.get("runtimeSeconds")
            elif job.type == "official" and submission and not error:
                db.add(Evaluation(submission_id=submission.id, status=result.get("status", "complete"),
                                  rating=result.get("rating"), win_rate=result.get("winRate"),
                                  average_final_money=result.get("averageFinalMoney"),
                                  average_money_differential=result.get("averageMoneyDifferential"),
                                  wins=result.get("wins"), ties=result.get("ties"), games=result.get("games"),
                                  error=result.get("error")))
                db.execute(update(Submission).where(Submission.team_id == submission.team_id).values(is_active=False))
                submission.is_active = True
                submission.official_score = result.get("rating")
            job.status = ("timeout" if error_kind in ("CONTESTANT_TIMEOUT", "INFRASTRUCTURE_TIMEOUT") else "failed") if error else "completed"
            job.error = error[:8000] if error else None
            job.error_kind = error_kind
            job.result_json = json.dumps(result)
            job.completed_at = utc_now()
            job.heartbeat_at = job.completed_at
            if not error and job.progress_total is not None:
                job.progress_current = job.progress_total
            db.add(PipelineEvent(job_id=job_id, stage="result", status="failed" if error else "completed",
                                 detail=error_kind or "Result committed"))
            return True

    def fail_job(self, job_id: str, error: str, error_kind: str="infrastructure"):
        with self.session() as db:
            job=db.get(SimulationJob,job_id)
            if job and job.status not in TERMINAL_STATUSES:
                job.status="timeout" if error_kind in ("CONTESTANT_TIMEOUT", "INFRASTRUCTURE_TIMEOUT") else "failed"
                job.error=error[:8000];job.error_kind=error_kind;job.completed_at=utc_now();job.heartbeat_at=utc_now()
                db.add(PipelineEvent(job_id=job_id,stage="execution",status="failed",detail=error_kind))

    def request_job_cancel(self, job_id: str, reason: str) -> dict | None:
        """DB state wins the completion race. A worker checks the external stop flag."""
        with self.session() as db:
            query = select(SimulationJob).where(SimulationJob.id == job_id)
            if self.engine.dialect.name == "postgresql":
                query = query.with_for_update()
            job = db.scalar(query)
            if not job:
                return None
            previous = job.status
            if previous in ("queued", "running"):
                job.status = "cancelled"
                job.completed_at = utc_now()
                job.heartbeat_at = job.completed_at
                job.error = reason[:8000]
                job.error_kind = "ADMIN_CANCELLED"
                db.add(PipelineEvent(job_id=job_id, stage="cancellation", status="requested",
                                     detail=reason[:500]))
            return {"id": job_id, "previousStatus": previous, "status": job.status,
                    "worker": job.worker_id, "type": job.type}

    def cancel_job(self, job_id: str) -> bool:
        with self.session() as db:
            job=db.get(SimulationJob,job_id)
            if not job or job.status!="queued":return False
            job.status="cancelled";job.completed_at=utc_now();job.heartbeat_at=utc_now()
            return True

    def recover_stale_jobs(self, stale_seconds: int=300) -> int:
        cutoff=utc_now()-timedelta(seconds=stale_seconds)
        with self.session() as db:
            jobs=db.scalars(select(SimulationJob).where(SimulationJob.status=="running",SimulationJob.heartbeat_at<cutoff)).all()
            failed_tournament=False
            for job in jobs:
                if job.type != "tournament" and job.attempts < job.max_attempts:
                    job.status = "queued"
                    job.started_at = None
                    job.heartbeat_at = None
                    job.worker_id = None
                    job.error = None
                    job.error_kind = None
                else:
                    job.status="failed";job.error_kind="WORKER_FAILURE";job.error="Worker heartbeat expired.";job.completed_at=utc_now()
                    failed_tournament=failed_tournament or job.type=="tournament"
            if failed_tournament:
                snapshot=db.get(TournamentSnapshot,1)
                if snapshot:
                    state=json.loads(snapshot.state_json)
                    if state.get("status") in ("starting","round_running","next_round","final"):
                        state.update({"status":"error","isLive":False,"error":"Worker heartbeat expired.","message":"Tournament worker went offline. Organizer review is required."})
                        snapshot.state_json=json.dumps(state);snapshot.updated_at=utc_now()
            return len(jobs)

    def admin_metrics(self) -> dict:
        with self.session() as db:
            counts={s:int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.status==s)) or 0) for s in ("queued","running","completed","failed","timeout","cancelled")};queues={q:int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.queue_name==q,SimulationJob.status=="queued")) or 0) for q in ("sandbox","official","tournament")}
            completed=db.scalars(select(SimulationJob).where(SimulationJob.status=="completed",SimulationJob.started_at.is_not(None),SimulationJob.completed_at.is_not(None)).order_by(SimulationJob.completed_at.desc()).limit(100)).all(); runtimes=[((_as_utc(j.completed_at))-(_as_utc(j.started_at))).total_seconds() for j in completed]
            now=utc_now();queued=db.scalars(select(SimulationJob).where(SimulationJob.status=="queued")).all();waits=[max(0,(now-_as_utc(j.created_at)).total_seconds()) for j in queued]
            started=db.scalars(select(SimulationJob).where(SimulationJob.started_at.is_not(None)).order_by(SimulationJob.started_at.desc()).limit(100)).all()
            observed_waits=[max(0,(_as_utc(j.started_at)-_as_utc(j.created_at)).total_seconds()) for j in started]
            failures=db.execute(select(SimulationJob.id,SimulationJob.type,SimulationJob.error,SimulationJob.completed_at).where(SimulationJob.status.in_(("failed", "timeout"))).order_by(SimulationJob.completed_at.desc()).limit(10)).all()
            sorted_runtime=sorted(runtimes);p95_runtime=sorted_runtime[min(len(sorted_runtime)-1,int(len(sorted_runtime)*.95))] if sorted_runtime else None
            infra_kinds=("ENGINE_FAILURE","WORKER_FAILURE","DATABASE_FAILURE","REDIS_FAILURE","STORAGE_FAILURE","INFRASTRUCTURE_TIMEOUT","infrastructure")
            infra_failed=int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.status.in_(("failed", "timeout")),SimulationJob.error_kind.in_(infra_kinds))) or 0)
            finished=counts["completed"]+counts["failed"]+counts["timeout"]
            return {**counts,"queues":queues,"averageJobRuntime":round(sum(runtimes)/len(runtimes),3) if runtimes else None,"p95JobRuntime":round(p95_runtime,3) if p95_runtime is not None else None,"averageQueueWait":round(sum(observed_waits)/len(observed_waits),3) if observed_waits else None,"oldestQueuedSeconds":round(max(waits),3) if waits else None,"infrastructureFailureRate":round(infra_failed/finished,4) if finished else 0,"recentFailures":[{"id":r.id,"type":r.type,"error":r.error,"at":_iso(r.completed_at)} for r in failures]}

    def record_worker(self, worker_id: str, *, status: str, current_job_id: str | None = None):
        with self.session() as db:
            worker=db.get(WorkerRecord,worker_id)
            if not worker:
                worker=WorkerRecord(id=worker_id,status=status,last_heartbeat=utc_now(),current_job_id=current_job_id);db.add(worker)
            else:
                if worker.status=="busy" and status!="busy":
                    previous=db.get(SimulationJob, worker.current_job_id) if worker.current_job_id else None
                    if previous and previous.status in ("failed", "timeout"): worker.jobs_failed+=1
                    elif previous and previous.status == "completed": worker.jobs_completed+=1
                worker.status=status;worker.current_job_id=current_job_id;worker.last_heartbeat=utc_now()

    def worker_metrics(self, heartbeat_timeout: int=30) -> dict:
        cutoff=utc_now()-timedelta(seconds=heartbeat_timeout)
        with self.session() as db:
            rows=db.scalars(select(WorkerRecord)).all();items=[]
            for row in rows:
                status=row.status if _as_utc(row.last_heartbeat)>=cutoff else "offline"
                try:
                    from backend.services.host_telemetry import worker_snapshot
                    telemetry = worker_snapshot(row.id)
                except Exception:
                    telemetry = None
                items.append({"id":row.id,"status":status,"lastHeartbeat":_iso(row.last_heartbeat),"currentJobId":row.current_job_id if status=="busy" else None,"jobsCompleted":row.jobs_completed,"jobsFailed":row.jobs_failed,"startedAt":_iso(row.started_at),"telemetry":telemetry})
            return {"total":len(items),"busy":sum(w["status"]=="busy" for w in items),"idle":sum(w["status"]=="idle" for w in items),"offline":sum(w["status"]=="offline" for w in items),"items":items}

    def list_admin_jobs(self, *, job_type=None, status=None, team=None, error_type=None, created_after=None, created_before=None, limit=100):
        with self.session() as db:
            stmt=select(SimulationJob,Team.username).outerjoin(Team).order_by(SimulationJob.created_at.desc()).limit(limit)
            if job_type:stmt=stmt.where(SimulationJob.type==job_type)
            if status:stmt=stmt.where(SimulationJob.status==status)
            if team:stmt=stmt.where(func.lower(Team.username).contains(team.lower()))
            if error_type:stmt=stmt.where(SimulationJob.error_kind==error_type)
            if created_after:stmt=stmt.where(SimulationJob.created_at>=created_after)
            if created_before:stmt=stmt.where(SimulationJob.created_at<=created_before)
            return [self._job_dict(j,n) for j,n in db.execute(stmt).all()]

    def contestant_metrics(self):
        with self.session() as db:
            teams=db.scalars(select(Team).order_by(Team.username)).all()
            team_ids=[team.id for team in teams]
            subs=db.scalars(select(Submission).where(Submission.team_id.in_(team_ids)).order_by(Submission.team_id,Submission.version.desc())).all() if team_ids else []
            by_team={}
            for sub in subs: by_team.setdefault(sub.team_id,[]).append(sub)
            sandbox_counts=dict(db.execute(select(Submission.team_id,func.count(SandboxRun.id)).join(SandboxRun, SandboxRun.submission_id==Submission.id).where(Submission.team_id.in_(team_ids)).group_by(Submission.team_id)).all()) if team_ids else {}
            official_rows=db.scalars(select(SimulationJob).where(SimulationJob.team_id.in_(team_ids),SimulationJob.type=="official").order_by(SimulationJob.team_id,SimulationJob.created_at.desc())).all() if team_ids else []
            latest_official={}
            for job in official_rows:latest_official.setdefault(job.team_id,job)
            result=[]
            for team in teams:
                team_subs=by_team.get(team.id,[]);latest=team_subs[0] if team_subs else None;official=latest_official.get(team.id)
                active=next((sub for sub in team_subs if sub.is_active),None)
                official_status=("evaluated" if official and official.status=="completed" else official.status) if official else ("evaluated" if latest and latest.official_score is not None else "none")
                result.append({"teamId":team.id,"team":team.username,"createdAt":_iso(team.created_at),"isRehearsal":team.is_rehearsal,"latestVersion":latest.version if latest else None,"validation":latest.validation_status if latest else "none","sandboxCount":int(sandbox_counts.get(team.id,0)),"officialStatus":official_status,"rating":active.official_score if active else None,"submissionCount":len(team_subs),"savedStrategy":self.team_strategy(team.id),"lastActivity":_iso(latest.created_at) if latest else _iso(team.created_at),"suspendedReason":team.suspended_reason,"blocked":bool(team.blocked)})
            ranked={row["team"]:row["rank"] for row in self.leaderboard()}
            for row in result: row["rank"]=ranked.get(row["team"])
            return result

    def contestant_detail(self, username: str):
        if not self.team_identity_by_name(username):return None
        submissions=self.list_submissions(username)
        return {"team":username,"submissions":submissions,"jobs":self.list_jobs(username,100),"summary":self.summary(username)}

    def reset_rehearsal_data(self):
        with self.session() as db:
            team_ids=list(db.scalars(select(Team.id).where(Team.is_rehearsal.is_(True))).all())
            submission_ids=list(db.scalars(select(Submission.id).where(Submission.team_id.in_(team_ids))).all()) if team_ids else []
            if submission_ids:
                db.execute(delete(SandboxRun).where(SandboxRun.submission_id.in_(submission_ids)))
                db.execute(delete(Evaluation).where(Evaluation.submission_id.in_(submission_ids)))
                db.execute(delete(SimulationJob).where(SimulationJob.submission_id.in_(submission_ids)))
                db.execute(delete(Submission).where(Submission.id.in_(submission_ids)))
            if team_ids: db.execute(delete(SimulationJob).where(SimulationJob.team_id.in_(team_ids)));db.execute(delete(Team).where(Team.id.in_(team_ids)))
            return len(team_ids)

    def rehearsal_jobs(self):
        with self.session() as db:
            rows=db.execute(select(SimulationJob,Team.username).join(Team).where(Team.is_rehearsal.is_(True),SimulationJob.status.in_(ACTIVE_STATUSES))).all()
            return [self._job_dict(job,name) for job,name in rows]

    def failure_summary(self):
        with self.session() as db:
            rows=db.execute(select(SimulationJob.error_kind,func.count(SimulationJob.id),func.max(SimulationJob.completed_at)).where(SimulationJob.status.in_(("failed", "timeout"))).group_by(SimulationJob.error_kind).order_by(func.count(SimulationJob.id).desc())).all()
            return [{"type":kind or "UNKNOWN","count":int(count),"latest":_iso(latest)} for kind,count,latest in rows]

    def event_config(self) -> dict:
        with self.session() as db:
            cfg=db.get(EventConfig,1)
            if not cfg:cfg=EventConfig(id=1);db.add(cfg);db.flush()
            return {"mode":cfg.mode,"uploadsEnabled":cfg.uploads_enabled,"sandboxEnabled":cfg.sandbox_enabled,"officialEnabled":cfg.official_enabled,"tournamentEnabled":cfg.tournament_enabled,"registrationsEnabled":cfg.registrations_enabled,"leaderboardVisible":cfg.leaderboard_visible,"submissionLimit":cfg.submission_limit,"submissionCooldownSeconds":cfg.submission_cooldown_seconds,"updatedAt":_iso(cfg.updated_at)}

    def set_event_config(self, mode: str, *, uploads_enabled: bool | None=None, sandbox_enabled: bool | None=None, official_enabled: bool | None=None, tournament_enabled: bool | None=None,
                         registrations_enabled: bool | None=None, leaderboard_visible: bool | None=None,
                         submission_limit: int | None=None, submission_cooldown_seconds: int | None=None):
        values={"DEVELOPMENT":(True,True,True,False),"QUALIFICATION":(True,True,True,False),"TOURNAMENT":(True,False,False,True),"MAINTENANCE":(False,False,False,False)}
        if mode not in values:raise ValueError("Invalid event mode.")
        defaults=values[mode]
        with self.session() as db:
            cfg=db.get(EventConfig,1)
            if not cfg:cfg=EventConfig(id=1);db.add(cfg)
            cfg.mode=mode;cfg.uploads_enabled=defaults[0] if uploads_enabled is None else uploads_enabled;cfg.sandbox_enabled=defaults[1] if sandbox_enabled is None else sandbox_enabled;cfg.official_enabled=defaults[2] if official_enabled is None else official_enabled;cfg.tournament_enabled=defaults[3] if tournament_enabled is None else tournament_enabled
            if registrations_enabled is not None:cfg.registrations_enabled=registrations_enabled
            if leaderboard_visible is not None:cfg.leaderboard_visible=leaderboard_visible
            if submission_limit is not None:cfg.submission_limit=submission_limit
            if submission_cooldown_seconds is not None:cfg.submission_cooldown_seconds=submission_cooldown_seconds
        return self.event_config()

    def set_event_limits(self, *, registrations_enabled: bool, leaderboard_visible: bool,
                         submission_limit: int, submission_cooldown_seconds: int) -> dict:
        with self.session() as db:
            cfg=db.get(EventConfig,1)
            if not cfg:cfg=EventConfig(id=1);db.add(cfg)
            cfg.registrations_enabled=registrations_enabled
            cfg.leaderboard_visible=leaderboard_visible
            cfg.submission_limit=submission_limit
            cfg.submission_cooldown_seconds=submission_cooldown_seconds
        return self.event_config()

    def submission_policy(self, team_id: int) -> dict:
        with self.session() as db:
            count=int(db.scalar(select(func.count()).select_from(Submission).where(Submission.team_id==team_id)) or 0)
            latest=db.scalar(select(Submission.created_at).where(Submission.team_id==team_id)
                             .order_by(Submission.created_at.desc()).limit(1))
            return {"count":count,"lastAt":_iso(latest)}

    def record_audit(self, action: str, target: str | None=None, metadata: dict | None=None):
        with self.session() as db:db.add(AdminAudit(action=action,target=target,metadata_json=json.dumps(metadata or {})))

    def audit_history(self, limit: int=100):
        with self.session() as db:
            rows=db.scalars(select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(limit)).all()
            return [{"id":r.id,"action":r.action,"target":r.target,"metadata":json.loads(r.metadata_json),"createdAt":_iso(r.created_at)} for r in rows]

    def get_tournament_state(self, default: dict) -> dict:
        with self.session() as db:
            snap=db.get(TournamentSnapshot,1)
            if not snap:snap=TournamentSnapshot(id=1,state_json=json.dumps(default));db.add(snap);db.flush()
            state=json.loads(snap.state_json)
            # Older aborted brackets could retain a stale "running" match.
            if state.get("status")=="error":
                for match in state.get("currentMatches",[]):
                    if match.get("status") in ("running","pending"):
                        match.update(status="aborted",error=state.get("error"))
            return state

    def save_tournament_state(self, state: dict):
        with self.session() as db:
            snap=db.get(TournamentSnapshot,1)
            if snap:snap.state_json=json.dumps(state);snap.updated_at=utc_now()
            else:db.add(TournamentSnapshot(id=1,state_json=json.dumps(state)))

    def _lock_tournament(self, db) -> None:
        if self.engine.dialect.name=="postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(78426136)"))
        elif self.engine.dialect.name=="sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")

    def add_tournament_player(self, username: str, default: dict, limit: int = 100) -> dict:
        with self.session() as db:
            self._lock_tournament(db)
            query=select(TournamentSnapshot).where(TournamentSnapshot.id==1)
            if self.engine.dialect.name=="postgresql":query=query.with_for_update()
            snap=db.scalar(query)
            if not snap:
                snap=TournamentSnapshot(id=1,state_json=json.dumps(default));db.add(snap);db.flush()
            state=json.loads(snap.state_json)
            if state["status"] not in ("registration","finished","champion","error"):
                raise ValueError("Registration is closed while the tournament is active.")
            players=state.get("registeredPlayers",[])
            if len(players)>=limit:raise ValueError("Maximum 100 players have already registered.")
            if any(name.casefold()==username.casefold() for name in players):
                raise ValueError("Team is already registered for this tournament.")
            players.append(username)
            state["registeredPlayers"]=players
            state["playersCount"]=len(players)
            state["selectedQualifiers"]=[]
            snap.state_json=json.dumps(state);snap.updated_at=utc_now()
            return state

    def claim_tournament_start(self, state: dict, default: dict) -> bool:
        with self.session() as db:
            self._lock_tournament(db)
            query=select(TournamentSnapshot).where(TournamentSnapshot.id==1)
            if self.engine.dialect.name=="postgresql":query=query.with_for_update()
            snap=db.scalar(query)
            if not snap:
                snap=TournamentSnapshot(id=1,state_json=json.dumps(default));db.add(snap);db.flush()
            current=json.loads(snap.state_json)
            if current.get("status") in ("starting","round_running","next_round","final"):
                return False
            snap.state_json=json.dumps(state);snap.updated_at=utc_now()
            return True

store=PlatformStore()
