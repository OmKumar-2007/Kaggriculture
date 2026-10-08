"""Local host invariants without touching the live event database or queue."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.services.participants import hash_access_code, verify_access_code
from backend.services.storage import PlatformStore


def test_access_code_hash_is_salted_and_verifiable():
    first = hash_access_code("a sufficiently long team secret")
    second = hash_access_code("a sufficiently long team secret")
    assert first != second
    assert verify_access_code("a sufficiently long team secret", first)
    assert not verify_access_code("wrong", first)


def test_atomic_claim_and_single_result_commit():
    with TemporaryDirectory() as root:
        local = PlatformStore(Path(root) / "test.sqlite")
        local.register_team_access("team_1", hash_access_code("a very long access code"))
        submission = local.create_submission("team_1", "fixture/agent.py", valid=True)
        job = local.create_job("team_1", "sandbox", submission_id=submission["id"], opponent="random", seed=1)
        assert local.mark_job_running(job["id"], "worker-a")
        assert local.mark_job_running(job["id"], "worker-b") is None
        result = {"status": "success", "opponent": "random", "seed": 1, "winner": "bot", "botFinalMoney": 2,
                  "opponentFinalMoney": 1, "runtimeSeconds": 1, "replayId": None}
        assert local.commit_job_result(job["id"], result)
        assert not local.commit_job_result(job["id"], result)
        assert local.get_job(job["id"])["status"] == "completed"
        assert local.sandbox_count("team_1") == 1


def test_abandoned_job_requeues_before_attempt_limit():
    with TemporaryDirectory() as root:
        local = PlatformStore(Path(root) / "test.sqlite")
        local.register_team_access("team_1", hash_access_code("a very long access code"))
        submission = local.create_submission("team_1", "fixture/agent.py", valid=True)
        job = local.create_job("team_1", "sandbox", submission_id=submission["id"], opponent="random", seed=1)
        local.mark_job_running(job["id"], "worker-a")
        with local.session() as db:
            from backend.services.storage import SimulationJob, utc_now
            from datetime import timedelta
            db.get(SimulationJob, job["id"]).heartbeat_at = utc_now() - timedelta(hours=1)
        assert local.recover_stale_jobs(60) == 1
        assert local.get_job(job["id"])["status"] == "queued"


def test_retry_limit_and_timeout_state():
    with TemporaryDirectory() as root:
        local = PlatformStore(Path(root) / "test.sqlite")
        local.register_team_access("team_1", hash_access_code("a very long access code"))
        submission = local.create_submission("team_1", "fixture/agent.py", valid=True)
        job = local.create_job("team_1", "sandbox", submission_id=submission["id"], opponent="random", seed=1,
                               max_attempts=2)
        local.mark_job_running(job["id"], "worker-a")
        assert local.requeue_running_job(job["id"])
        local.mark_job_running(job["id"], "worker-b")
        assert not local.requeue_running_job(job["id"])
        local.fail_job(job["id"], "Deadline exceeded", "INFRASTRUCTURE_TIMEOUT")
        assert local.get_job(job["id"])["status"] == "timeout"


def test_tournament_match_uses_isolated_runner_by_default():
    import tournament
    with TemporaryDirectory() as root:
        a, b = Path(root) / "a.py", Path(root) / "b.py"
        a.write_text("def agent(obs): return {}")
        b.write_text("def agent(obs): return {}")
        with patch.dict("os.environ", {"NEURAL_COLISEUM_TRUSTED_LOCAL": "0"}), patch(
            "backend.services.sandbox._run_docker", return_value={"p1Score": 2, "p2Score": 1, "winner": 0}
        ) as runner:
            result = tournament.run_match({"username": "a", "filePath": str(a)}, {"username": "b", "filePath": str(b)}, 1)
        assert result["winner"] == 0
        runner.assert_called_once()
