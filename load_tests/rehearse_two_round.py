"""Run the real 60-bot two-round pipeline against an isolated rehearsal database.

Requires DATABASE_URL containing ``farmcraft_rehearsal``, an isolated Redis DB,
and LOCAL_STORAGE_ROOT containing ``rehearsal``. Never enables fake simulation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import psutil

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("FARMCRAFT_REHEARSAL_KIT", "D:/kaggriculture/farmcraft-rehearsal-kit/farmcraft_load_suite"))
REPORT_DIR = Path(os.environ.get("FARMCRAFT_REHEARSAL_REPORT_DIR", "D:/kaggriculture/farmcraft-rehearsal-results"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", "")
STORAGE_ROOT = os.environ.get("LOCAL_STORAGE_ROOT", "")
if (not urlparse(DATABASE_URL).path.lstrip("/").startswith("farmcraft_rehearsal_")
        or urlparse(REDIS_URL).path not in ("/1", "/2", "/3")
        or "rehearsal" not in STORAGE_ROOT.lower()):
    raise SystemExit("Refusing to run outside an isolated rehearsal database, Redis DB, and storage root.")
if os.environ.get("LOAD_TEST_FAKE_SIMULATION") == "1" or os.environ.get("NEURAL_COLISEUM_TRUSTED_LOCAL") == "1":
    raise SystemExit("Real rehearsal requires Docker isolation and fake simulation disabled.")
if not all((KIT / "agents" / f"farmbot_{index:02d}" / "agent.py").is_file() for index in range(1, 61)):
    raise SystemExit("The 60-agent kit is incomplete.")

sys.path.insert(0, str(ROOT))
from backend.services.blob_storage import objects
from backend.services.bracket import opening_bracket
from backend.services.queueing import enqueue
from backend.services.scoring import load_scoring_config
from backend.services.storage import store
from backend.services.tournament_state import initial_state

REPORT_DIR.mkdir(parents=True, exist_ok=True)
STARTED = time.monotonic()
SAMPLES = []
REPORT = {"status": "starting", "startedAt": datetime.now(timezone.utc).isoformat(),
          "mode": "real Docker evaluation", "teamCount": 60, "referenceCount": 5,
          "qualificationSeeds": 2, "plannedQualificationGames": 1200,
          "plannedMinimumTournamentGames": 30, "workerConcurrency": 1,
          "database": urlparse(DATABASE_URL).path.lstrip("/"), "jobs": {}}


def snapshot():
    REPORT["elapsedSeconds"] = round(time.monotonic() - STARTED, 2)
    REPORT["sampleCount"] = len(SAMPLES)
    if SAMPLES:
        REPORT["peakHostRamPercent"] = max(s["ramPercent"] for s in SAMPLES)
        REPORT["peakHostCpuPercent"] = max(s["cpuPercent"] for s in SAMPLES)
    (REPORT_DIR / "two_round_60_progress.json").write_text(json.dumps(REPORT, indent=2), encoding="utf-8")


def sample():
    SAMPLES.append({"atSeconds": round(time.monotonic() - STARTED, 1),
                    "ramPercent": psutil.virtual_memory().percent,
                    "cpuPercent": psutil.cpu_percent(interval=None)})


def wait_jobs(job_ids, label, *, timeout_hours=8):
    deadline = time.monotonic() + timeout_hours * 3600
    last_count = -1
    last_progress = time.monotonic()
    while True:
        jobs = [store.get_job(job_id) for job_id in job_ids]
        counts = {status: sum(job["status"] == status for job in jobs)
                  for status in ("queued", "running", "completed", "failed", "timeout", "cancelled")}
        completed_games = sum(job.get("progressCurrent") or 0 for job in jobs)
        if completed_games != last_count:
            last_progress = time.monotonic()
            last_count = completed_games
        REPORT["jobs"][label] = counts | {"completedGames": completed_games}
        sample(); snapshot()
        print(f"{label}: {counts}, accepted games={completed_games}", flush=True)
        if counts["queued"] + counts["running"] == 0:
            return jobs
        if time.monotonic() > deadline or time.monotonic() - last_progress > 1200:
            raise TimeoutError(f"{label} did not progress before the rehearsal deadline.")
        time.sleep(30)


def enqueue_durably(job):
    """The PostgreSQL job survives a temporary Redis response timeout."""
    for attempt in range(3):
        try:
            enqueue(job)
            return
        except Exception as exc:
            print(f"Queue transport retry {attempt + 1}/3 for {job['id']}: {exc}", flush=True)
            time.sleep(3)
    # The worker's reconcile loop restores queued PostgreSQL jobs to Redis.
    print(f"Job {job['id']} remains durable in PostgreSQL for worker reconciliation.", flush=True)


def start_worker():
    log = (REPORT_DIR / "rehearsal-worker.log").open("a", encoding="utf-8")
    env = os.environ.copy()
    env["MAX_EVALUATION_WORKERS"] = "1"
    env["WORKER_NODE_NAME"] = "farmcraft-rehearsal"
    worker = subprocess.Popen([sys.executable, "-m", "backend.worker"], cwd=ROOT,
                              env=env, stdout=log, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    REPORT["workerPid"] = worker.pid
    snapshot()
    return worker, log


def stop_worker(worker, log):
    try:
        parent = psutil.Process(worker.pid)
        processes = parent.children(recursive=True) + [parent]
        for process in processes:
            process.terminate()
        _, alive = psutil.wait_procs(processes, timeout=5)
        for process in alive:
            process.kill()
    except psutil.NoSuchProcess:
        pass
    log.close()


def main():
    from backend.services.storage import SimulationJob
    current = store.competition()
    if current["phase"] not in ("SETUP", "QUALIFICATION_OPEN"):
        raise RuntimeError(f"Cannot resume rehearsal from phase {current['phase']}.")
    # A machine sleep or orchestrator restart can leave a real match marked running.
    # Give that isolated rehearsal job one infrastructure retry before recovery.
    with store.session() as db:
        for job in db.query(SimulationJob).filter(SimulationJob.status == "running",
                                                  SimulationJob.type == "official"):
            job.max_attempts = max(job.max_attempts, job.attempts + 1)
    store.recover_stale_jobs(300)
    worker, log = start_worker()
    try:
        if current["phase"] == "SETUP":
            if store.total_submissions():
                raise RuntimeError("Setup database already contains submissions.")
            store.configure_competition(qualifier_count=16, registration_capacity=60,
                official_attempt_limit=3, reference_count=5, qualification_seed_count=2,
                tie_replay_limit=3)
            references = []
            test_ids = []
            for index in range(1, 6):
                source = (KIT / "agents" / f"farmbot_{index:02d}" / "agent.py").read_bytes()
                reference = store.add_reference_bot(source, f"Rehearsal Reference {index}")
                references.append(reference)
                job = store.create_job(None, "reference_test", payload={"referenceBotId": reference["id"]})
                enqueue_durably(job); test_ids.append(job["id"])
            tests = wait_jobs(test_ids, "referenceTests", timeout_hours=1)
            if any(job["status"] != "completed" for job in tests):
                raise RuntimeError("A real reference bot sandbox test failed.")
            for reference in references:
                store.set_reference_bot(reference["id"], selected=True)
            frozen = store.start_qualification(load_scoring_config())
        else:
            frozen = current
            REPORT["resumedExistingSubmissions"] = store.total_submissions()
        if len(frozen["evaluationConfig"]["opponents"]) != 5:
            raise RuntimeError("Reference pool snapshot has the wrong size.")
        REPORT["phase"] = frozen["phase"]
        job_ids = []
        submitted_at = {}
        for index in range(1, 61):
            team = f"rehearsal_bot_{index:02d}"
            source = (KIT / "agents" / f"farmbot_{index:02d}" / "agent.py").read_bytes()
            submissions = store.list_submissions(team)
            if submissions:
                submission = submissions[0]
            else:
                key = f"submissions/{team}/v1/agent.py"
                objects.put_bytes(key, source, "text/x-python")
                submission = store.create_submission(team, key, valid=True)
                store.add_tournament_player(team, initial_state(), limit=60)
            prior = [job for job in store.list_jobs(team, 10) if job["type"] == "official"]
            if prior and prior[0]["status"] in ("queued", "running", "completed"):
                job = prior[0]
            else:
                job = store.create_job(team, "official", submission_id=submission["id"],
                    progress_total=20, payload={"evaluationConfig": frozen["evaluationConfig"],
                        "referencePool": frozen["referencePool"],
                        "submissionSha256": hashlib.sha256(source).hexdigest()})
                enqueue_durably(job)
            submitted_at[job["id"]] = time.monotonic()
            job_ids.append(job["id"])
        REPORT["status"] = "qualifying"
        REPORT["officialJobIds"] = job_ids
        snapshot()
        qualified_start = time.monotonic()
        jobs = wait_jobs(job_ids, "qualification")
        REPORT["qualificationDurationSeconds"] = round(time.monotonic() - qualified_start, 2)
        completed = [job for job in jobs if job["status"] == "completed"]
        REPORT["qualificationCompletedGames"] = sum((job["result"] or {}).get("games", 0) for job in completed)
        REPORT["qualificationFailures"] = [{"team": job["team"], "error": job["error"],
             "errorKind": job["errorKind"]} for job in jobs if job["status"] != "completed"]
        durations = [(datetime.fromisoformat(job["completedAt"]) - datetime.fromisoformat(job["startedAt"])).total_seconds()
                     for job in completed if job["startedAt"] and job["completedAt"]]
        if durations:
            REPORT["meanOfficialJobSeconds"] = statistics.mean(durations)
            REPORT["p95OfficialJobSeconds"] = sorted(durations)[math.ceil(len(durations) * .95) - 1]
        store.close_qualification()
        if REPORT["qualificationFailures"]:
            raise RuntimeError("One or more official jobs failed; inspect and resolve them before finalization.")
        for old in store.list_admin_jobs(job_type="official", limit=1000):
            if old["status"] in ("failed", "timeout") and not (old.get("errorKind") or "").startswith("CONTESTANT_"):
                store.adjudicate_infrastructure_failure(old["id"], "Recovered by a completed rehearsal retry.")
        final = store.finalize_qualification()
        roster = final["qualifiers"]
        REPORT["standings"] = [{k: v for k, v in row.items() if k not in ("objectKey", "teamId")}
                               for row in store.qualification_leaderboard()]
        REPORT["qualifiers"] = [{k: v for k, v in row.items() if k != "objectKey"} for row in roster]
        bracket = opening_bracket(roster)
        state = initial_state([row["team"] for row in roster])
        state.update(status="ready", selectedQualifiers=[row["team"] for row in roster],
                     qualifierCount=len(roster), bracketCapacity=bracket["capacity"])
        store.save_tournament_state(state)
        store.transition_competition("QUALIFICATION_FINALIZED", "TOURNAMENT_READY")
        state.update(status="starting", isLive=True, registeredPlayers=[row["team"] for row in roster],
                     playersCount=len(roster), currentMatches=[], roundsHistory=[], byes=[],
                     eliminatedPlayers=[], allMatches=[], champion=None, error=None)
        if not store.claim_tournament_start(state, initial_state()):
            raise RuntimeError("Could not claim the seeded tournament start.")
        tournament = store.create_job(None, "tournament", payload={"roster": roster, "tieReplayLimit": 3})
        store.transition_competition("TOURNAMENT_READY", "TOURNAMENT_RUNNING")
        enqueue(tournament)
        REPORT["status"] = "tournament_running"
        REPORT["tournamentJobId"] = tournament["id"]
        snapshot()
        tournament_start = time.monotonic()
        result = wait_jobs([tournament["id"]], "tournament")[0]
        REPORT["tournamentDurationSeconds"] = round(time.monotonic() - tournament_start, 2)
        if result["status"] != "completed":
            raise RuntimeError(f"Tournament job ended {result['status']}: {result['error']}")
        games = store.tournament_games()
        history = result["result"]["history"]
        REPORT["tournamentGames"] = len(games)
        REPORT["tournamentMatches"] = len(history)
        REPORT["champion"] = result["result"]["champion"]
        REPORT["tournamentHistory"] = history
        REPORT["competitionPhase"] = store.competition()["phase"]
        if len(history) != 15 or len(games) < 30 or REPORT["competitionPhase"] != "TOURNAMENT_COMPLETED":
            raise RuntimeError("The completed bracket failed its consistency checks.")
        with (REPORT_DIR / "qualification_standings.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["rank", "team", "rating", "winRate", "averageFinalMoney", "games"])
            writer.writeheader()
            for row in REPORT["standings"]:
                writer.writerow({key: row.get(key) for key in writer.fieldnames})
        REPORT["status"] = "completed"
    finally:
        stop_worker(worker, log)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        REPORT["status"] = "failed"
        REPORT["error"] = f"{type(exc).__name__}: {exc}"
        print(REPORT["error"], file=sys.stderr, flush=True)
        raise
    finally:
        REPORT["finishedAt"] = datetime.now(timezone.utc).isoformat()
        snapshot()
        (REPORT_DIR / "two_round_60_report.json").write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
