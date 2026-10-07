"""Transactional persistence for the arena.

PostgreSQL is the production database. SQLite remains a limited fallback for
unit tests and zero-config boot; Docker Compose supplies PostgreSQL normally.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, func, select, update, text, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "neural_coliseum.db"
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")

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

class EventConfig(Base):
    __tablename__ = "event_config"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(String(30), default="DEVELOPMENT")
    uploads_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sandbox_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    official_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tournament_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
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
    return configured.replace("postgres://", "postgresql+psycopg://", 1) if configured.startswith("postgres://") else configured

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
                    item = Submission(team_id=team.id, version=version, object_key=str(object_key), file_path=str(object_key), validation_status="valid" if valid else "invalid", validation_errors=errors)
                    db.add(item); db.flush(); return self._submission_dict(item, team.username)
            except IntegrityError:
                if attempt == 2: raise
        raise RuntimeError("Could not allocate a submission version.")

    def get_submission(self, submission_id: int) -> dict | None:
        with self.session() as db:
            row = db.execute(select(Submission, Team.username).join(Team).where(Submission.id == submission_id)).first()
            return self._submission_dict(row[0], row[1]) if row else None

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

    def create_job(self, username: str | None, job_type: str, *, submission_id: int | None=None, opponent: str | None=None, seed: int | None=None, payload: dict | None=None, progress_total: int | None=None, max_attempts: int=2) -> dict:
        queue_name={"tournament":"tournament","official":"official"}.get(job_type,"sandbox")
        with self.session() as db:
            team=self._team(db,username,lock=True) if username else None
            if team and job_type in ("sandbox","official"):
                default_limit="1"
                limit=int(os.getenv(f"MAX_ACTIVE_{job_type.upper()}_PER_TEAM",default_limit))
                existing=int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.team_id==team.id,SimulationJob.type==job_type,SimulationJob.status.in_(ACTIVE_STATUSES))) or 0)
                if existing>=limit: raise ActiveJobError(f"You already have the maximum active {job_type} jobs.")
            job=SimulationJob(id=str(uuid4()),team_id=team.id if team else None,type=job_type,queue_name=queue_name,status="queued",submission_id=submission_id,opponent=opponent,seed=seed,payload_json=json.dumps(payload or {}),progress_current=0 if progress_total else None,progress_total=progress_total,max_attempts=max_attempts)
            db.add(job);db.flush();return self._job_dict(job,team.username if team else None)

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

    def list_jobs(self, username: str, limit: int=50) -> list[dict]:
        with self.session() as db:
            rows=db.execute(select(SimulationJob,Team.username).join(Team).where(func.lower(Team.username)==username.lower()).order_by(SimulationJob.created_at.desc()).limit(limit)).all();return [self._job_dict(j,n) for j,n in rows]

    def mark_job_running(self, job_id: str, worker_id: str) -> dict | None:
        with self.session() as db:
            job=db.get(SimulationJob,job_id)
            if not job or job.status!="queued":return None
            job.status="running";job.started_at=utc_now();job.heartbeat_at=utc_now();job.worker_id=worker_id;job.attempts+=1
        return self.get_job(job_id)

    def update_job_progress(self, job_id: str, current: int, total: int | None=None):
        with self.session() as db:
            job=db.get(SimulationJob,job_id)
            if job and job.status=="running":job.progress_current=current;job.progress_total=total if total is not None else job.progress_total;job.heartbeat_at=utc_now()

    def finish_job(self, job_id: str, result: dict):
        with self.session() as db:
            job=db.get(SimulationJob,job_id)
            if job and job.status not in TERMINAL_STATUSES:
                job.status="completed";job.result_json=json.dumps(result);job.completed_at=utc_now();job.heartbeat_at=utc_now();job.progress_current=job.progress_total if job.progress_total is not None else job.progress_current

    def fail_job(self, job_id: str, error: str, error_kind: str="infrastructure"):
        with self.session() as db:
            job=db.get(SimulationJob,job_id)
            if job and job.status not in TERMINAL_STATUSES:job.status="failed";job.error=error[:8000];job.error_kind=error_kind;job.completed_at=utc_now();job.heartbeat_at=utc_now()

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
            counts={s:int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.status==s)) or 0) for s in ("queued","running","completed","failed","cancelled")};queues={q:int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.queue_name==q,SimulationJob.status=="queued")) or 0) for q in ("sandbox","official","tournament")}
            completed=db.scalars(select(SimulationJob).where(SimulationJob.status=="completed",SimulationJob.started_at.is_not(None),SimulationJob.completed_at.is_not(None)).order_by(SimulationJob.completed_at.desc()).limit(100)).all(); runtimes=[((_as_utc(j.completed_at))-(_as_utc(j.started_at))).total_seconds() for j in completed]
            now=utc_now();queued=db.scalars(select(SimulationJob).where(SimulationJob.status=="queued")).all();waits=[max(0,(now-(j.created_at.replace(tzinfo=timezone.utc) if j.created_at.tzinfo is None else j.created_at)).total_seconds()) for j in queued]
            failures=db.execute(select(SimulationJob.id,SimulationJob.type,SimulationJob.error,SimulationJob.completed_at).where(SimulationJob.status=="failed").order_by(SimulationJob.completed_at.desc()).limit(10)).all()
            sorted_runtime=sorted(runtimes);p95_runtime=sorted_runtime[min(len(sorted_runtime)-1,int(len(sorted_runtime)*.95))] if sorted_runtime else None
            infra_kinds=("ENGINE_FAILURE","WORKER_FAILURE","DATABASE_FAILURE","REDIS_FAILURE","STORAGE_FAILURE","INFRASTRUCTURE_TIMEOUT","infrastructure")
            infra_failed=int(db.scalar(select(func.count()).select_from(SimulationJob).where(SimulationJob.status=="failed",SimulationJob.error_kind.in_(infra_kinds))) or 0)
            finished=counts["completed"]+counts["failed"]
            return {**counts,"queues":queues,"averageJobRuntime":round(sum(runtimes)/len(runtimes),3) if runtimes else None,"p95JobRuntime":round(p95_runtime,3) if p95_runtime is not None else None,"averageQueueWait":round(sum(waits)/len(waits),3) if waits else None,"oldestQueuedSeconds":round(max(waits),3) if waits else None,"infrastructureFailureRate":round(infra_failed/finished,4) if finished else 0,"recentFailures":[{"id":r.id,"type":r.type,"error":r.error,"at":_iso(r.completed_at)} for r in failures]}

    def record_worker(self, worker_id: str, *, status: str, current_job_id: str | None = None):
        with self.session() as db:
            worker=db.get(WorkerRecord,worker_id)
            if not worker:
                worker=WorkerRecord(id=worker_id,status=status,last_heartbeat=utc_now(),current_job_id=current_job_id);db.add(worker)
            else:
                if worker.status=="busy" and status!="busy":
                    previous=db.get(SimulationJob, worker.current_job_id) if worker.current_job_id else None
                    if previous and previous.status=="failed": worker.jobs_failed+=1
                    else: worker.jobs_completed+=1
                worker.status=status;worker.current_job_id=current_job_id;worker.last_heartbeat=utc_now()

    def worker_metrics(self, heartbeat_timeout: int=30) -> dict:
        cutoff=utc_now()-timedelta(seconds=heartbeat_timeout)
        with self.session() as db:
            rows=db.scalars(select(WorkerRecord)).all();items=[]
            for row in rows:
                status=row.status if _as_utc(row.last_heartbeat)>=cutoff else "offline"
                items.append({"id":row.id,"status":status,"lastHeartbeat":_iso(row.last_heartbeat),"currentJobId":row.current_job_id if status=="busy" else None,"jobsCompleted":row.jobs_completed,"jobsFailed":row.jobs_failed,"startedAt":_iso(row.started_at)})
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
                official_status=("evaluated" if official and official.status=="completed" else official.status) if official else ("evaluated" if latest and latest.official_score is not None else "none")
                result.append({"team":team.username,"isRehearsal":team.is_rehearsal,"latestVersion":latest.version if latest else None,"validation":latest.validation_status if latest else "none","sandboxCount":int(sandbox_counts.get(team.id,0)),"officialStatus":official_status,"rating":latest.official_score if latest else None,"submissionCount":len(team_subs),"lastActivity":_iso(latest.created_at) if latest else _iso(team.created_at)})
            ranked={row["team"]:row["rank"] for row in self.leaderboard()}
            for row in result: row["rank"]=ranked.get(row["team"])
            return result

    def contestant_detail(self, username: str):
        submissions=self.list_submissions(username)
        if not submissions:return None
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
            rows=db.execute(select(SimulationJob.error_kind,func.count(SimulationJob.id),func.max(SimulationJob.completed_at)).where(SimulationJob.status=="failed").group_by(SimulationJob.error_kind).order_by(func.count(SimulationJob.id).desc())).all()
            return [{"type":kind or "UNKNOWN","count":int(count),"latest":_iso(latest)} for kind,count,latest in rows]

    def event_config(self) -> dict:
        with self.session() as db:
            cfg=db.get(EventConfig,1)
            if not cfg:cfg=EventConfig(id=1);db.add(cfg);db.flush()
            return {"mode":cfg.mode,"uploadsEnabled":cfg.uploads_enabled,"sandboxEnabled":cfg.sandbox_enabled,"officialEnabled":cfg.official_enabled,"tournamentEnabled":cfg.tournament_enabled,"updatedAt":_iso(cfg.updated_at)}

    def set_event_config(self, mode: str, *, uploads_enabled: bool | None=None, sandbox_enabled: bool | None=None, official_enabled: bool | None=None, tournament_enabled: bool | None=None):
        values={"DEVELOPMENT":(True,True,True,False),"QUALIFICATION":(True,True,True,False),"TOURNAMENT":(True,False,False,True),"MAINTENANCE":(False,False,False,False)}
        if mode not in values:raise ValueError("Invalid event mode.")
        defaults=values[mode]
        with self.session() as db:
            cfg=db.get(EventConfig,1)
            if not cfg:cfg=EventConfig(id=1);db.add(cfg)
            cfg.mode=mode;cfg.uploads_enabled=defaults[0] if uploads_enabled is None else uploads_enabled;cfg.sandbox_enabled=defaults[1] if sandbox_enabled is None else sandbox_enabled;cfg.official_enabled=defaults[2] if official_enabled is None else official_enabled;cfg.tournament_enabled=defaults[3] if tournament_enabled is None else tournament_enabled
        return self.event_config()

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
            return json.loads(snap.state_json)

    def save_tournament_state(self, state: dict):
        with self.session() as db:
            snap=db.get(TournamentSnapshot,1)
            if snap:snap.state_json=json.dumps(state);snap.updated_at=utc_now()
            else:db.add(TournamentSnapshot(id=1,state_json=json.dumps(state)))

store=PlatformStore()
