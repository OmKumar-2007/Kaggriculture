"""Control Center state transitions and migration behavior."""
from __future__ import annotations

import pytest

from backend.services.storage import PlatformStore
from backend.services.evaluation import ContestantEvaluationError, evaluate_source
from backend.services.tournament_state import initial_state, apply_progress
from backend.services.blob_storage import LocalObjectStorage
from concurrent.futures import ThreadPoolExecutor


def test_running_cancellation_blocks_late_official_score(tmp_path):
    store = PlatformStore(tmp_path / "cancel.db")
    team = store.register_team("CancelTeam")
    submission = store.create_submission(team["team"], "submissions/test/agent.py", valid=True)
    job = store.create_job(team["team"], "official", submission_id=submission["id"])
    assert store.mark_job_running(job["id"], "worker-1")["status"] == "running"
    outcome = store.request_job_cancel(job["id"], "Organizer stopped it")
    assert outcome["previousStatus"] == "running"
    assert store.commit_job_result(job["id"], {"status": "complete", "rating": 9000, "games": 8}) is False
    assert store.get_job(job["id"])["status"] == "cancelled"
    assert store.leaderboard() == []
    assert [event["stage"] for event in store.pipeline_events(job["id"])] == ["queue", "worker", "cancellation"]


def test_queued_cancel_is_idempotent_and_cannot_be_claimed(tmp_path):
    store = PlatformStore(tmp_path / "queued.db")
    job = store.create_job("QueueTeam", "sandbox", opponent="starter_crop", seed=42)
    first = store.request_job_cancel(job["id"], "Organizer action")
    second = store.request_job_cancel(job["id"], "Repeated click")
    assert first["previousStatus"] == "queued"
    assert second["previousStatus"] == "cancelled"
    assert store.mark_job_running(job["id"], "worker-1") is None
    assert store.get_job(job["id"])["status"] == "cancelled"


def test_team_block_suspend_and_session_version(tmp_path):
    store = PlatformStore(tmp_path / "teams.db")
    identity = store.register_team("SecureTeam")
    suspended = store.set_team_state(identity["id"], suspended_reason="Organizer review")
    assert suspended["suspendedReason"] == "Organizer review"
    assert store.team_identity(identity["id"])["sessionVersion"] == 1
    store.set_team_state(identity["id"], clear_suspension=True)
    assert store.team_identity(identity["id"])["suspendedReason"] is None
    store.set_team_state(identity["id"], blocked=True)
    assert store.team_identity(identity["id"])["blocked"] is True
    assert store.revoke_team_sessions(identity["id"]) is True
    assert store.team_identity(identity["id"])["sessionVersion"] == 3


def test_event_limits_persist_and_old_scores_survive(tmp_path):
    path = tmp_path / "settings.db"
    store = PlatformStore(path)
    team = store.register_team("RatedTeam")
    submission = store.create_submission(team["team"], "submissions/first.py", valid=True)
    job = store.create_job(team["team"], "official", submission_id=submission["id"])
    store.mark_job_running(job["id"], "worker-1")
    assert store.commit_job_result(job["id"], {"status": "complete", "rating": 1000, "winRate": 50, "averageFinalMoney": 1000, "games": 8})
    store.set_event_config("QUALIFICATION", registrations_enabled=False, leaderboard_visible=False,
                           submission_limit=1, submission_cooldown_seconds=60)
    reopened = PlatformStore(path)
    assert reopened.event_config()["registrationsEnabled"] is False
    assert reopened.event_config()["submissionLimit"] == 1
    assert reopened.leaderboard()[0]["team"] == "RatedTeam"


def test_official_evaluation_rejects_contestant_failure_in_swapped_side():
    config = {"opponents": ["baseline_alpha"], "seeds": [42], "sides": [1],
              "weights": {"win_rate": .5, "economic": .5}, "economic_scale": 1000, "rating_scale": 1000}

    def runner(_first, _second, _seed, _replay):
        return {"p1Score": 100, "p2Score": 0, "failure": {"player": 1, "error": "SyntaxError: bad agent"}}

    with pytest.raises(ContestantEvaluationError, match="SyntaxError"):
        evaluate_source("def agent(obs): return {}", runner=runner, config=config)


def test_simultaneous_tournament_registration_keeps_both_players(tmp_path):
    path=tmp_path / "tournament.db"
    PlatformStore(path)
    def register(name):
        return PlatformStore(path).add_tournament_player(name,initial_state())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(register,("TeamA","TeamB")))
    assert set(PlatformStore(path).get_tournament_state(initial_state())["registeredPlayers"])=={"TeamA","TeamB"}


def test_pipeline_overview_uses_latest_recorded_event(tmp_path, monkeypatch):
    from backend import admin as admin_module

    store = PlatformStore(tmp_path / "pipeline.db")
    team = store.register_team("PipelineTeam")
    store.create_submission(team["team"], "submissions/pipeline/agent.py", valid=True)
    job = store.create_job(team["team"], "official")
    store.pipeline_event(job["id"], "container", "running", "started")
    store.pipeline_event(job["id"], "match", "completed", "game 1/8")
    latest = store.latest_pipeline_stages([job["id"]])
    assert latest[job["id"]]["stage"] == "match"
    assert latest[job["id"]]["status"] == "completed"
    assert store.total_submissions() == 1
    monkeypatch.setattr(admin_module, "store", store)
    for listing in (admin_module.jobs(limit=10, _="admin"), admin_module.pipeline(_="admin")):
        assert listing["jobs"][0]["currentStage"] == "match"
        assert listing["jobs"][0]["stageStatus"] == "completed"
    monkeypatch.setattr(store, "latest_pipeline_stages", lambda _ids: {})
    untracked = admin_module._with_latest_stages([
        {"id": "old", "status": "completed"}, {"id": "new", "status": "queued"}])
    assert [(item["currentStage"], item["stageStatus"]) for item in untracked] == [
        ("untracked", "unknown"), ("queue", "waiting")]


def test_aborted_tournament_has_no_running_match_in_saved_or_legacy_view(tmp_path):
    store = PlatformStore(tmp_path / "bracket.db")
    state = initial_state(["TeamA", "TeamB"])
    state["currentMatches"] = [{"id": "R1_M1", "status": "running"}]
    state["status"] = "error"
    state["error"] = "match failed"
    store.save_tournament_state(state)
    assert store.get_tournament_state(initial_state())["currentMatches"][0]["status"] == "aborted"
    state["status"] = "final"
    apply_progress(state, "TOURNAMENT_ERROR", {"error": "match failed"})
    assert state["currentMatches"][0]["status"] == "aborted"


def test_old_completed_tournament_error_is_reconciled_once(tmp_path):
    path = tmp_path / "old-tournament.db"
    store = PlatformStore(path)
    job = store.create_job(None, "tournament")
    assert store.mark_job_running(job["id"], "worker-1")
    assert store.commit_job_result(job["id"], {"champion": None, "history": [], "error": "exact tie"})
    reopened = PlatformStore(path)
    corrected = reopened.get_job(job["id"])
    assert corrected["status"] == "failed"
    assert corrected["errorKind"] == "TOURNAMENT_ERROR"
    assert corrected["result"]["error"] == "exact tie"
    assert reopened.reconcile_legacy_tournament_errors() == 0
    assert len([event for event in reopened.pipeline_events(job["id"])
                if event["detail"] == "Historical tournament error reconciled"]) == 1


def test_failed_roster_admission_discards_unqueued_upload_and_file(tmp_path):
    store = PlatformStore(tmp_path / "admission.db")
    team = store.register_team("RosterTeam")
    objects = LocalObjectStorage(tmp_path / "objects")
    key = f"submissions/team_{team['id']}/upload/agent.py"
    objects.put_bytes(key, b"def agent(obs): return {}")
    submission = store.create_submission(team["team"], key, valid=True)
    assert store.discard_unqueued_submission(submission["id"])
    objects.delete_prefix(key)
    assert store.get_submission(submission["id"]) is None
    assert not objects.exists(key)
