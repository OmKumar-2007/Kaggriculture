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
    average_opponent_money: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_money_differential: Mapped[float | None] = mapped_column(Float, nullable=True)
    economic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    wins: Mapped[int | None] = mapped_column(Integer, nullable=True); losses: Mapped[int | None] = mapped_column(Integer, nullable=True); ties: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

class OfficialSubmissionClaim(Base):
    """One immutable Round 1 submission per team and competition start."""
    __tablename__ = "official_submission_claims"
    __table_args__ = (UniqueConstraint("team_id", "round_started_at", name="uq_official_team_round"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    round_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[str] = mapped_column(String(36), unique=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"))
    source_sha256: Mapped[str] = mapped_column(String(64))

class ParticipantSession(Base):
    __tablename__ = "participant_sessions"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class SharedRateLimit(Base):
    __tablename__ = "shared_rate_limits"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

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
    evaluator_mode: Mapped[str] = mapped_column(String(30), default="LOCAL")
    evaluator_generation: Mapped[int] = mapped_column(Integer, default=1)

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
    qualifier_count: Mapped[int] = mapped_column(Integer, default=16)
    registration_capacity: Mapped[int] = mapped_column(Integer, default=100)
    official_attempt_limit: Mapped[int] = mapped_column(Integer, default=1)
    reference_count: Mapped[int] = mapped_column(Integer, default=5)
    qualification_seed_count: Mapped[int] = mapped_column(Integer, default=2)
    tie_replay_limit: Mapped[int] = mapped_column(Integer, default=3)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class CompetitionState(Base):
    __tablename__ = "competition_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    phase: Mapped[str] = mapped_column(String(40), default="SETUP")
    reference_snapshot_json: Mapped[str] = mapped_column(Text, default="[]")
    evaluation_config_json: Mapped[str] = mapped_column(Text, default="{}")
    qualifier_roster_json: Mapped[str] = mapped_column(Text, default="[]")
    standings_json: Mapped[str] = mapped_column(Text, default="[]")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class TournamentGame(Base):
    __tablename__ = "tournament_games"
    game_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    match_id: Mapped[str] = mapped_column(String(40), index=True)
    round_number: Mapped[int] = mapped_column(Integer)
    replay_number: Mapped[int] = mapped_column(Integer)
    leg: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    player_zero: Mapped[str] = mapped_column(String(80))
    player_one: Mapped[str] = mapped_column(String(80))
    score_zero: Mapped[float] = mapped_column(Float)
    score_one: Mapped[float] = mapped_column(Float)
    replay_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class ReferenceBot(Base):
    __tablename__ = "reference_bots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    object_key: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[str] = mapped_column(String(20), default="valid")
    test_status: Mapped[str] = mapped_column(String(20), default="untested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (UniqueConstraint("family_id", "version", name="uq_reference_family_version"),)

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
        else: engine_options.update({"pool_size": 6, "max_overflow": 4, "pool_timeout": 10, "pool_recycle": 300})
        self.engine = create_engine(self.database_url, **engine_options)
        self._version_lock = threading.Lock()
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        with self._schema_lock():
            self._initialize_schema()

    @contextmanager
    def _schema_lock(self):
        """Serialize additive schema initialization across API and worker processes."""
        if self.engine.dialect.name != "postgresql":
            yield
            return
        with self.engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(78426137)"))
            connection.commit()
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(78426137)"))
                connection.commit()

    def _initialize_schema(self):
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
                                     ("submission_cooldown_seconds", "INTEGER DEFAULT 0 NOT NULL"),
                                     ("qualifier_count", "INTEGER DEFAULT 16 NOT NULL"),
                                     ("registration_capacity", "INTEGER DEFAULT 100 NOT NULL"),
                                     ("official_attempt_limit", "INTEGER DEFAULT 1 NOT NULL"),
                                     ("reference_count", "INTEGER DEFAULT 5 NOT NULL"),
                                     ("qualification_seed_count", "INTEGER DEFAULT 2 NOT NULL"),
                                     ("tie_replay_limit", "INTEGER DEFAULT 3 NOT NULL")):
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
            control_columns = {column["name"] for column in __import__("sqlalchemy").inspect(connection).get_columns("remote_control")}
            if "evaluator_mode" not in control_columns:
                connection.execute(text("ALTER TABLE remote_control ADD COLUMN evaluator_mode VARCHAR(30) DEFAULT 'LOCAL' NOT NULL"))
            if "evaluator_generation" not in control_columns:
                connection.execute(text("ALTER TABLE remote_control ADD COLUMN evaluator_generation INTEGER DEFAULT 1 NOT NULL"))
            connection.execute(text("UPDATE event_config SET official_attempt_limit = 1 WHERE official_attempt_limit <> 1"))
            evaluation_columns={column["name"] for column in __import__("sqlalchemy").inspect(connection).get_columns("evaluations")}
            for name,definition in (("average_opponent_money","FLOAT"),("economic_score","FLOAT"),("losses","INTEGER")):
                if name not in evaluation_columns:
                    connection.execute(text(f"ALTER TABLE evaluations ADD COLUMN {name} {definition}"))
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

    @staticmethod
    def _session_hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def put_participant_session(self, key: str, team_id: int, payload: dict, lifetime: int) -> None:
        digest = self._session_hash(key)
        with self.session() as db:
            row = db.get(ParticipantSession, digest)
            if row is None:
                row = ParticipantSession(key_hash=digest, team_id=team_id)
                db.add(row)
            row.payload_json = json.dumps(payload)
            row.expires_at = utc_now() + timedelta(seconds=lifetime)
            row.updated_at = utc_now()

    def get_participant_session(self, key: str) -> dict | None:
        with self.session() as db:
            row = db.get(ParticipantSession, self._session_hash(key))
            return json.loads(row.payload_json) if row and _as_utc(row.expires_at) > utc_now() else None

    def list_participant_sessions(self, team_id: int | None = None) -> list[dict]:
        with self.session() as db:
            query = select(ParticipantSession).where(ParticipantSession.expires_at > utc_now())
            if team_id is not None: query = query.where(ParticipantSession.team_id == team_id)
            rows = db.scalars(query.order_by(ParticipantSession.updated_at.desc()).limit(500)).all()
            return [{"id": row.key_hash, "teamId": row.team_id, **json.loads(row.payload_json)} for row in rows]

    def revoke_participant_session(self, key: str, team_id: int | None = None) -> bool:
        with self.session() as db:
            query = delete(ParticipantSession).where(ParticipantSession.key_hash == self._session_hash(key))
            if team_id is not None: query = query.where(ParticipantSession.team_id == team_id)
            return bool(db.execute(query).rowcount)

    def revoke_participant_session_id(self, session_id: str, team_id: int) -> bool:
        with self.session() as db:
            return bool(db.execute(delete(ParticipantSession).where(
                ParticipantSession.key_hash == session_id,
                ParticipantSession.team_id == team_id)).rowcount)

    def bump_rate_limit(self, key: str, seconds: int) -> int:
        digest = self._session_hash(key)
        with self.session() as db:
            if self.engine.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": digest})
            elif self.engine.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            row = db.get(SharedRateLimit, digest)
            now = utc_now()
            if row is None:
                row = SharedRateLimit(key_hash=digest, count=1, expires_at=now + timedelta(seconds=seconds))
                db.add(row)
            elif _as_utc(row.expires_at) <= now:
                row.count = 1; row.expires_at = now + timedelta(seconds=seconds)
            else: row.count += 1
            db.flush()
            return row.count

    def rate_limit_count(self, key: str) -> int:
        with self.session() as db:
            row = db.get(SharedRateLimit, self._session_hash(key))
            return row.count if row and _as_utc(row.expires_at) > utc_now() else 0

    def clear_rate_limit(self, key: str) -> None:
        with self.session() as db:
            db.execute(delete(SharedRateLimit).where(SharedRateLimit.key_hash == self._session_hash(key)))

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
            competition=db.get(CompetitionState,1)
            if competition and any(row.get("submissionId")==submission_id for row in
                                   json.loads(competition.qualifier_roster_json or "[]")):
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

    def replay_access(self, replay_id: str) -> dict | None:
        """Classify only replays committed to a completed sandbox or tournament game."""
        with self.session() as db:
            owner = db.execute(select(Team.username).join(Submission, Submission.team_id == Team.id)
                               .join(SandboxRun, SandboxRun.submission_id == Submission.id)
                               .where(SandboxRun.replay_id == replay_id, SandboxRun.status == "success")
                               .limit(1)).scalar_one_or_none()
            if owner:
                return {"kind": "sandbox", "team": owner}
            public = db.scalar(select(TournamentGame.game_id).where(TournamentGame.replay_id == replay_id).limit(1))
            return {"kind": "tournament"} if public else None

    def record_evaluation(self, submission_id: int, result: dict) -> dict:
        with self.session() as db:
            db.add(Evaluation(submission_id=submission_id, status=result.get("status", "complete"), rating=result.get("rating"), win_rate=result.get("winRate"), average_final_money=result.get("averageFinalMoney"), average_opponent_money=result.get("averageOpponentMoney"), average_money_differential=result.get("averageMoneyDifferential"), economic_score=result.get("economicScore"), wins=result.get("wins"), losses=result.get("losses"), ties=result.get("ties"), games=result.get("games"), error=result.get("error")))
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

    def summary(self, username: str, submissions: list[dict] | None = None) -> dict:
        if submissions is None:submissions=self.list_submissions(username)
        current=submissions[0] if submissions else None; active=next((x for x in submissions if x["is_active"]),None)
        scored=[x["sandbox_score"] for x in submissions if x["sandbox_score"] is not None]
        competition=self.competition()
        entry=next((row for row in self.qualification_leaderboard() if row["team"].casefold()==username.casefold()),None) if competition["phase"]!="SETUP" else None
        return {"team":username,"currentSubmission":current,"activeSubmission":active,"currentVersion":f"v{current['version']}" if current else None,"validationStatus":current["validation_status"] if current else "not_uploaded","lastTest":self.last_sandbox(current["id"]) if current else None,"bestScore":max(scored) if scored else None,"submissionCount":len(submissions),"sandboxRunCount":self.sandbox_count(username),"leaderboardRank":entry["rank"] if entry else None,"winRate":entry["winRate"] if entry else None,"qualificationRating":entry["rating"] if entry else None,"qualificationPhase":competition["phase"],"qualifierCount":competition["settings"]["qualifierCount"],"officialAttempts":self.official_attempts(username),"qualified":any(row["team"].casefold()==username.casefold() for row in competition["qualifiers"]),"jobs":self.list_jobs(username,10)}

    def create_job(self, username: str | None, job_type: str, *, submission_id: int | None=None, opponent: str | None=None, seed: int | None=None, payload: dict | None=None, progress_total: int | None=None, max_attempts: int | None=None) -> dict:
        if max_attempts is None:
            max_attempts = max(1, int(os.getenv("MAX_INFRASTRUCTURE_RETRIES", "2")) + 1)
        queue_name={"tournament":"tournament","official":"official"}.get(job_type,"sandbox")
        with self._version_lock, self.session() as db:
            if job_type == "official":
                self._lock_tournament(db)
            team=self._team(db,username,lock=True) if username else None
            state=db.get(CompetitionState,1) if job_type == "official" else None
            if job_type == "official":
                if not team or not state or state.phase != "QUALIFICATION_OPEN" or not state.started_at:
                    raise ValueError("Round 1 qualification is not open.")
                submission=db.get(Submission,submission_id) if submission_id else None
                if not submission or submission.team_id != team.id or submission.validation_status != "valid":
                    raise ValueError("Choose a valid version belonging to this team.")
                if not payload or not isinstance(payload.get("submissionSha256"),str) or len(payload["submissionSha256"]) != 64:
                    raise ValueError("The official source hash is required.")
                prior=db.scalar(select(OfficialSubmissionClaim).where(
                    OfficialSubmissionClaim.team_id==team.id,
                    OfficialSubmissionClaim.round_started_at==state.started_at))
                historical=db.scalar(select(SimulationJob.id).where(
                    SimulationJob.team_id==team.id,SimulationJob.type=="official",
                    SimulationJob.created_at>=state.started_at).limit(1))
                if prior or historical:
                    raise ActiveJobError("This team has already used its one official Round 1 submission.")
            if team and job_type in ("sandbox","official"):
                default_limit="1"
                limit=int(os.getenv(f"MAX_ACTIVE_{job_type.upper()}_PER_TEAM",default_limit))
                existing=int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.team_id==team.id,SimulationJob.type==job_type,SimulationJob.status.in_(ACTIVE_STATUSES))) or 0)
                if existing>=limit: raise ActiveJobError(f"You already have the maximum active {job_type} jobs.")
            job=SimulationJob(id=str(uuid4()),team_id=team.id if team else None,type=job_type,queue_name=queue_name,status="queued",submission_id=submission_id,opponent=opponent,seed=seed,payload_json=json.dumps(payload or {}),progress_current=0 if progress_total else None,progress_total=progress_total,max_attempts=max_attempts)
            db.add(job);db.flush()
            if job_type == "official":
                db.add(OfficialSubmissionClaim(team_id=team.id,round_started_at=state.started_at,
                    job_id=job.id,submission_id=submission_id,source_sha256=payload["submissionSha256"]))
                db.flush()
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

    def register_remote_worker(self, token: str, name: str, version: str,
                               max_concurrency: int = 2) -> dict | None:
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
                existing.max_concurrency = max_concurrency
                worker_id = existing.id
            else:
                worker_id = str(uuid4())
                db.add(RemoteWorker(id=worker_id, name=name, version=version,
                                    credential_hash=self._credential_hash(secret), last_heartbeat=now,
                                    max_concurrency=max_concurrency))
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

    def evaluator_mode_state(self) -> dict:
        with self.session() as db:
            row = db.get(RemoteControl, 1)
            return {"activeMode": row.evaluator_mode if row else "LOCAL",
                    "generation": row.evaluator_generation if row else 1,
                    "cloudEvaluationAvailable": False}

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
            control = db.get(RemoteControl, 1)
            valid = bool((not control or control.evaluator_mode == "LOCAL")
                         and job and job.status == "running" and job.worker_id == worker_id
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
            control = db.get(RemoteControl, 1)
            if control and control.evaluator_mode != "LOCAL":
                return None
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
            control = db.get(RemoteControl, 1)
            if control and control.evaluator_mode != "LOCAL":
                return False
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

    def retry_failed_infrastructure_job(self, job_id: str, max_retries: int) -> dict | None:
        """Requeue the same frozen job; stale worker attempts are fenced out."""
        allowed = {"ENGINE_FAILURE", "WORKER_FAILURE", "DATABASE_FAILURE", "REDIS_FAILURE",
                   "STORAGE_FAILURE", "INFRASTRUCTURE_TIMEOUT", "infrastructure"}
        with self.session() as db:
            query = select(SimulationJob).where(SimulationJob.id == job_id)
            if self.engine.dialect.name == "postgresql": query = query.with_for_update()
            job = db.scalar(query)
            if not job or job.status not in ("failed", "timeout") or job.error_kind not in allowed:
                return None
            payload = json.loads(job.payload_json or "{}")
            count = int(payload.get("_adminRetryCount", 0))
            if count >= max_retries: return None
            payload["_adminRetryCount"] = count + 1
            job.payload_json = json.dumps(payload)
            job.status = "queued"
            job.started_at = None; job.completed_at = None; job.heartbeat_at = None
            job.worker_id = None; job.attempt_id = None; job.lease_expires_at = None
            job.error = None; job.error_kind = None; job.result_json = None
            job.progress_current = 0 if job.progress_total is not None else None
            job.attempts = 0
            db.add(PipelineEvent(job_id=job.id, stage="retry", status="waiting",
                                 detail=f"Infrastructure retry {count + 1} of {max_retries}"))
            team = db.get(Team, job.team_id) if job.team_id else None
            return self._job_dict(job, team.username if team else None)

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
            if worker_id is not None:
                control = db.get(RemoteControl, 1)
                if control and control.evaluator_mode != "LOCAL":
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
                                  average_opponent_money=result.get("averageOpponentMoney"),
                                  average_money_differential=result.get("averageMoneyDifferential"),
                                  economic_score=result.get("economicScore"),
                                  wins=result.get("wins"), losses=result.get("losses"), ties=result.get("ties"), games=result.get("games"),
                                  error=result.get("error")))
                db.execute(update(Submission).where(Submission.team_id == submission.team_id).values(is_active=False))
                submission.is_active = True
                submission.official_score = result.get("rating")
            elif job.type == "reference_test":
                bot_id=json.loads(job.payload_json or "{}").get("referenceBotId")
                bot=db.get(ReferenceBot,bot_id) if bot_id else None
                if bot:bot.test_status="passed" if not error and result.get("status")=="passed" else "failed"
            elif job.type == "tournament" and not error and result.get("champion"):
                state=db.get(CompetitionState,1)
                if state and state.phase=="TOURNAMENT_RUNNING":
                    state.phase="TOURNAMENT_COMPLETED";state.updated_at=utc_now()
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
                if job.type=="reference_test":
                    bot_id=json.loads(job.payload_json or "{}").get("referenceBotId")
                    bot=db.get(ReferenceBot,bot_id) if bot_id else None
                    if bot:bot.test_status="failed"
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
            if not cfg:
                self._lock_tournament(db)
                cfg=db.get(EventConfig,1)
                if not cfg:cfg=EventConfig(id=1);db.add(cfg);db.flush()
            return {"mode":cfg.mode,"uploadsEnabled":cfg.uploads_enabled,"sandboxEnabled":cfg.sandbox_enabled,"officialEnabled":cfg.official_enabled,"tournamentEnabled":cfg.tournament_enabled,"registrationsEnabled":cfg.registrations_enabled,"leaderboardVisible":cfg.leaderboard_visible,"submissionLimit":cfg.submission_limit,"submissionCooldownSeconds":cfg.submission_cooldown_seconds,"qualifierCount":cfg.qualifier_count,"registrationCapacity":cfg.registration_capacity,"officialAttemptLimit":cfg.official_attempt_limit,"referenceCount":cfg.reference_count,"qualificationSeedCount":cfg.qualification_seed_count,"tieReplayLimit":cfg.tie_replay_limit,"updatedAt":_iso(cfg.updated_at)}

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

    @staticmethod
    def _reference_dict(row: ReferenceBot) -> dict:
        return {"id":row.id,"familyId":row.family_id,"version":row.version,
                "displayName":row.display_name,"description":row.description,
                "category":row.category,"sourceSha256":row.source_sha256,
                "enabled":row.enabled,"selected":row.selected,"archived":row.archived,
                "validationStatus":row.validation_status,"testStatus":row.test_status,
                "createdAt":_iso(row.created_at)}

    def reference_bots(self) -> list[dict]:
        with self.session() as db:
            return [self._reference_dict(row) for row in db.scalars(
                select(ReferenceBot).order_by(ReferenceBot.family_id,ReferenceBot.version.desc())).all()]

    def add_reference_bot(self, source: bytes, display_name: str, description: str="",
                          category: str="", family_id: str | None=None) -> dict:
        from backend.services.blob_storage import objects
        from backend.services.validator import validate_agent_source
        validate_agent_source(source.decode("utf-8"))
        digest=hashlib.sha256(source).hexdigest()
        with self.session() as db:
            family=family_id or str(uuid4())
            prior=db.scalar(select(ReferenceBot).where(ReferenceBot.family_id==family)
                            .order_by(ReferenceBot.version.desc()).limit(1))
            if family_id and not prior:raise ValueError("Reference bot family does not exist.")
            version=(prior.version+1) if prior else 1
            key=f"private/reference-bots/{family}/v{version}-{digest}.py"
            objects.put_bytes(key,source,"text/x-python")
            if prior:
                db.execute(update(ReferenceBot).where(ReferenceBot.family_id==family).values(
                    selected=False,enabled=False))
            row=ReferenceBot(family_id=family,version=version,display_name=display_name,
                             description=description,category=category,object_key=key,
                             source_sha256=digest)
            db.add(row);db.flush()
            return self._reference_dict(row)

    def set_reference_bot(self, bot_id: int, *, selected: bool | None=None,
                          enabled: bool | None=None, archived: bool | None=None) -> dict | None:
        with self.session() as db:
            row=db.get(ReferenceBot,bot_id)
            if not row:return None
            if selected is not None:row.selected=selected
            if enabled is not None:row.enabled=enabled
            if archived is not None:row.archived=archived
            if row.archived or not row.enabled:row.selected=False
            db.flush();return self._reference_dict(row)

    def reference_source(self, bot_id: int) -> bytes | None:
        from backend.services.blob_storage import objects
        with self.session() as db:
            row=db.get(ReferenceBot,bot_id)
            return objects.get_bytes(row.object_key) if row else None

    def set_reference_test(self, bot_id: int, passed: bool) -> None:
        with self.session() as db:
            row=db.get(ReferenceBot,bot_id)
            if row:row.test_status="passed" if passed else "failed"

    def official_attempts(self, username: str) -> dict:
        with self.session() as db:
            state=db.get(CompetitionState,1)
            cfg=db.get(EventConfig,1)
            if not state or not state.started_at:
                return {"used":0,"remaining":1}
            team=self._team(db,username)
            if not team:return {"used":0,"remaining":1}
            rows=db.scalars(select(SimulationJob).where(SimulationJob.team_id==team.id,
                SimulationJob.type=="official",SimulationJob.created_at>=state.started_at)).all()
            used=1 if rows else 0
            active=sum(job.status in ACTIVE_STATUSES for job in rows)
            return {"used":used,"remaining":1-used,
                    "active":active}

    def adjudicate_infrastructure_failure(self, job_id: str, reason: str) -> bool:
        with self.session() as db:
            state=db.get(CompetitionState,1)
            job=db.get(SimulationJob,job_id)
            if (not state or state.phase!="QUALIFICATION_CLOSING" or not job or
                job.type!="official" or job.created_at<state.started_at or
                job.status not in ("failed","timeout") or
                (job.error_kind or "").startswith("CONTESTANT_")):
                return False
            job.error_kind="INFRASTRUCTURE_ADJUDICATED"
            db.add(PipelineEvent(job_id=job.id,stage="adjudication",status="completed",
                                 detail=reason[:500]))
            return True

    def competition(self) -> dict:
        with self.session() as db:
            state=db.get(CompetitionState,1)
            if not state:
                self._lock_tournament(db)
                state=db.get(CompetitionState,1)
                if not state:state=CompetitionState(id=1);db.add(state);db.flush()
            result={"phase":state.phase,"referencePool":json.loads(state.reference_snapshot_json),
                    "evaluationConfig":json.loads(state.evaluation_config_json),
                    "qualifiers":json.loads(state.qualifier_roster_json)}
        return {**result,"settings":self.event_config()}

    def configure_competition(self, *, qualifier_count: int, registration_capacity: int,
                              official_attempt_limit: int, reference_count: int,
                              tie_replay_limit: int, qualification_seed_count: int=2) -> dict:
        if not 2<=qualifier_count<=registration_capacity<=1000:
            raise ValueError("Qualifier count must be 2 through registration capacity (maximum 1000).")
        if reference_count not in (5,10):raise ValueError("Select 5 or 10 reference opponents.")
        if official_attempt_limit!=1 or not 0<=tie_replay_limit<=20 or not 1<=qualification_seed_count<=10:
            raise ValueError("Attempt or tie replay limit is outside the allowed range.")
        with self.session() as db:
            self._lock_tournament(db)
            state=db.get(CompetitionState,1)
            if not state:state=CompetitionState(id=1);db.add(state)
            cfg=db.get(EventConfig,1)
            if not cfg:cfg=EventConfig(id=1);db.add(cfg)
            if state.phase not in ("SETUP","QUALIFICATION_OPEN","QUALIFICATION_CLOSING"):
                raise ValueError("Qualifier count is locked after Round 1 finalization.")
            if state.phase!="SETUP" and (cfg.registration_capacity!=registration_capacity or
                cfg.official_attempt_limit!=official_attempt_limit or cfg.reference_count!=reference_count or
                cfg.tie_replay_limit!=tie_replay_limit or cfg.qualification_seed_count!=qualification_seed_count):
                raise ValueError("Only the qualifier count may change before Round 1 finalization.")
            cfg.qualifier_count=qualifier_count;cfg.registration_capacity=registration_capacity
            cfg.official_attempt_limit=official_attempt_limit;cfg.reference_count=reference_count
            cfg.qualification_seed_count=qualification_seed_count
            cfg.tie_replay_limit=tie_replay_limit
        return self.competition()

    def start_qualification(self, evaluation_config: dict) -> dict:
        from backend.services.blob_storage import objects
        current=self.competition()
        if current["phase"]=="QUALIFICATION_OPEN":return current
        with self.session() as db:
            self._lock_tournament(db)
            state=db.get(CompetitionState,1)
            if not state:state=CompetitionState(id=1);db.add(state)
            if state.phase!="SETUP":
                raise ValueError("Qualification has already advanced beyond setup.")
            cfg=db.get(EventConfig,1)
            if not cfg:cfg=EventConfig(id=1);db.add(cfg);db.flush()
            rows=db.scalars(select(ReferenceBot).where(ReferenceBot.selected.is_(True),
                ReferenceBot.enabled.is_(True),ReferenceBot.archived.is_(False))
                .order_by(ReferenceBot.id)).all()
            if len(rows)!=cfg.reference_count:
                raise ValueError(f"Select exactly {cfg.reference_count} enabled reference bots.")
            pool=[]
            for row in rows:
                if row.validation_status!="valid" or row.test_status!="passed":
                    raise ValueError("Every selected reference bot must pass validation and a real sandbox test.")
                source=objects.get_bytes(row.object_key)
                if hashlib.sha256(source).hexdigest()!=row.source_sha256:
                    raise ValueError("Reference bot source hash differs from its stored version.")
                pool.append({"id":row.id,"name":row.display_name,"version":row.version,
                             "objectKey":row.object_key,"sha256":row.source_sha256})
            evaluator_version=os.getenv("FARMCRAFT_EVALUATOR_VERSION", "2026.10.09").strip()
            seeds=list(evaluation_config["seeds"][:cfg.qualification_seed_count])
            while len(seeds)<cfg.qualification_seed_count:
                candidate=secrets.randbelow(2_147_483_647)
                if candidate not in seeds:seeds.append(candidate)
            evaluation_config={**evaluation_config,"opponents":[f"ref_{item['id']}" for item in pool],
                               "seeds":seeds,
                               "qualifier_count":cfg.qualifier_count,
                               "evaluator_version":evaluator_version}
            state.reference_snapshot_json=json.dumps(pool)
            state.evaluation_config_json=json.dumps(evaluation_config)
            state.phase="QUALIFICATION_OPEN";state.started_at=utc_now()
            state.updated_at=utc_now()
            cfg.mode="QUALIFICATION";cfg.official_enabled=True
            cfg.registrations_enabled=True;cfg.uploads_enabled=True;cfg.sandbox_enabled=True
            cfg.tournament_enabled=False
        return self.competition()

    def close_qualification(self) -> dict:
        with self.session() as db:
            self._lock_tournament(db)
            state=db.get(CompetitionState,1)
            if not state or state.phase not in ("QUALIFICATION_OPEN","QUALIFICATION_CLOSING"):
                raise ValueError("Qualification is not open.")
            state.phase="QUALIFICATION_CLOSING"
            cfg=db.get(EventConfig,1)
            cfg.official_enabled=False;cfg.registrations_enabled=False
        return self.competition()

    def qualification_leaderboard(self) -> list[dict]:
        with self.session() as db:
            state=db.get(CompetitionState,1)
            if not state or not state.started_at:return []
            if state.phase in ("QUALIFICATION_FINALIZED","TOURNAMENT_READY","TOURNAMENT_RUNNING","TOURNAMENT_COMPLETED"):
                return json.loads(state.standings_json or "[]")
            rows=db.execute(select(SimulationJob,Submission,Team).join(
                Submission,SimulationJob.submission_id==Submission.id).join(
                Team,Submission.team_id==Team.id).where(
                SimulationJob.type=="official",SimulationJob.status=="completed",
                SimulationJob.created_at>=state.started_at,
                Team.is_rehearsal.is_(False))).all()
            best={}
            for job,submission,team in rows:
                result=json.loads(job.result_json or "{}")
                if result.get("status")!="complete" or result.get("rating") is None:
                    continue
                entry={"team":team.username,"teamId":team.id,"submissionId":submission.id,
                       "version":submission.version,"objectKey":submission.object_key,
                       "rating":float(result["rating"]),"winRate":float(result.get("winRate",0)),
                       "averageMoneyDifferential":float(result.get("averageMoneyDifferential",0)),
                       "averageFinalMoney":float(result.get("averageFinalMoney",0)),
                       "averageOpponentMoney":float(result.get("averageOpponentMoney",0)),
                       "economicScore":float(result.get("economicScore",0)),
                       "wins":int(result.get("wins",0)),"losses":int(result.get("losses",0)),
                       "ties":int(result.get("ties",0)),
                       "games":int(result.get("games",0)),"jobId":job.id}
                key=(entry["rating"],entry["winRate"],entry["averageMoneyDifferential"],
                     entry["averageFinalMoney"],-entry["submissionId"])
                existing=best.get(team.id)
                if not existing or key>existing[0]:best[team.id]=(key,entry)
            ordered=sorted((item[1] for item in best.values()),key=lambda item:(
                -item["rating"],-item["winRate"],-item["averageMoneyDifferential"],
                -item["averageFinalMoney"],item["team"].casefold(),item["submissionId"]))
            return [{**item,"rank":rank} for rank,item in enumerate(ordered,1)]

    def finalize_qualification(self) -> dict:
        from backend.services.blob_storage import objects
        with self.session() as db:
            self._lock_tournament(db)
            state=db.get(CompetitionState,1)
            if not state or state.phase!="QUALIFICATION_CLOSING":
                raise ValueError("Close qualification before finalizing.")
            cfg=db.get(EventConfig,1)
            jobs=db.scalars(select(SimulationJob).where(SimulationJob.type=="official",
                SimulationJob.created_at>=state.started_at)).all()
            unresolved=[job for job in jobs if job.status in ACTIVE_STATUSES or
                        (job.status in ("failed","timeout") and not ((job.error_kind or "").startswith("CONTESTANT_") or
                          job.error_kind=="INFRASTRUCTURE_ADJUDICATED"))]
            if unresolved:raise ValueError(f"Resolve {len(unresolved)} pending or infrastructure-failed official jobs first.")
            standings=self.qualification_leaderboard()
            if len(standings)<cfg.qualifier_count:
                raise ValueError(f"Only {len(standings)} eligible teams; lower the cutoff before finalization.")
            roster=[]
            for row in standings[:cfg.qualifier_count]:
                source=objects.get_bytes(row["objectKey"])
                roster.append({"team":row["team"],"teamId":row["teamId"],
                               "seed":row["rank"],"rank":row["rank"],
                               "rating":row["rating"],"submissionId":row["submissionId"],
                               "version":row["version"],"objectKey":row["objectKey"],
                               "sha256":hashlib.sha256(source).hexdigest(),
                               "qualifiedAt":_iso(utc_now())})
            state.qualifier_roster_json=json.dumps(roster)
            state.standings_json=json.dumps(standings)
            state.phase="QUALIFICATION_FINALIZED";state.updated_at=utc_now()
            cfg.official_enabled=False
        return self.competition()

    def transition_competition(self, expected: str, target: str) -> dict:
        with self.session() as db:
            self._lock_tournament(db)
            state=db.get(CompetitionState,1)
            if not state or state.phase!=expected:
                raise ValueError(f"Expected competition phase {expected}.")
            state.phase=target;state.updated_at=utc_now()
            if target=="TOURNAMENT_READY":
                cfg=db.get(EventConfig,1)
                cfg.mode="TOURNAMENT";cfg.tournament_enabled=True
                cfg.official_enabled=False;cfg.registrations_enabled=False
        return self.competition()

    def record_tournament_game(self, data: dict) -> bool:
        with self.session() as db:
            row=db.get(TournamentGame,data["gameId"])
            if row:
                if (row.player_zero,row.player_one,row.score_zero,row.score_one)!=(
                    data["playerZero"],data["playerOne"],float(data["scoreZero"]),float(data["scoreOne"])):
                    raise ValueError("Repeated game produced a conflicting result.")
                return False
            db.add(TournamentGame(game_id=data["gameId"],match_id=data["matchId"],
                round_number=data["round"],replay_number=data["replay"],leg=data["leg"],
                seed=data["seed"],player_zero=data["playerZero"],player_one=data["playerOne"],
                score_zero=float(data["scoreZero"]),score_one=float(data["scoreOne"]),
                replay_id=data.get("replayId")))
            return True

    def tournament_games(self) -> list[dict]:
        with self.session() as db:
            rows=db.scalars(select(TournamentGame).order_by(TournamentGame.round_number,
                TournamentGame.match_id,TournamentGame.replay_number,TournamentGame.leg)).all()
            return [{"gameId":row.game_id,"matchId":row.match_id,"round":row.round_number,
                     "replay":row.replay_number,"leg":row.leg,"seed":row.seed,
                     "playerZero":row.player_zero,"playerOne":row.player_one,
                     "scoreZero":row.score_zero,"scoreOne":row.score_one,
                     "replayId":row.replay_id,"createdAt":_iso(row.created_at)} for row in rows]

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
            if len(players)>=limit:raise ValueError(f"Maximum {limit} teams have already registered.")
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
            if current.get("status") != "ready":
                return False
            snap.state_json=json.dumps(state);snap.updated_at=utc_now()
            return True

    def claim_tournament_resume(self) -> bool:
        with self.session() as db:
            self._lock_tournament(db)
            snap=db.get(TournamentSnapshot,1)
            if not snap:return False
            state=json.loads(snap.state_json)
            if state.get("status")!="error":return False
            state.update(status="starting",isLive=True,error=None,
                         message="Resuming from completed persisted pairings.")
            snap.state_json=json.dumps(state);snap.updated_at=utc_now()
            return True

store=PlatformStore()
