"""Durable remote evaluator ownership and recovery checks."""
from datetime import timedelta
import gzip
import hashlib
import sqlite3

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.blob_storage import LocalObjectStorage
from backend.services.storage import PlatformStore, RemoteControl, SimulationJob, utc_now
from backend.services.scoring import aggregate_games
from tests.official_helpers import open_round_one, official_payload


def registered(store, name="Laptop A"):
    token = store.issue_worker_registration()
    identity = store.register_remote_worker(token, name, "2026.10.09")
    assert identity
    assert store.register_remote_worker(token, "Laptop B", "2026.10.09") is None
    assert store.register_remote_worker(store.issue_worker_registration(), name.lower(), "2026.10.09") is None
    return identity


def test_legacy_remote_control_gets_local_evaluator_mode(tmp_path):
    path = tmp_path / "legacy-control.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE remote_control (id INTEGER PRIMARY KEY, registration_enabled BOOLEAN NOT NULL)")
        db.execute("INSERT INTO remote_control VALUES (1, 1)")
    store = PlatformStore(path)
    assert store.evaluator_mode_state()["activeMode"] == "LOCAL"
    assert store.evaluator_mode_state()["generation"] == 1


def test_remote_registration_claim_result_once_and_revoke(tmp_path):
    store = PlatformStore(tmp_path / "remote.db")
    identity = registered(store)
    team = store.register_team("remote_team")
    submission = store.create_submission(team["team"], "submissions/remote/main.py", valid=True)
    open_round_one(store)
    job = store.create_job(team["team"], "official", submission_id=submission["id"], payload=official_payload())
    claimed = store.claim_remote_job(identity["workerId"], "2026.10.09")
    assert claimed["id"] == job["id"]
    assert store.claim_remote_job(identity["workerId"], "wrong-version") is None
    assert not store.commit_job_result(job["id"], {"rating": 99}, worker_id="stolen-id", attempt_id=claimed["attemptId"])
    assert store.remote_heartbeat(identity["workerId"], {}, job["id"], claimed["attemptId"])["valid"]
    result = {"status": "complete", "rating": 825, "winRate": 50, "averageFinalMoney": 1000, "games": 8}
    assert store.commit_job_result(job["id"], result, worker_id=identity["workerId"], attempt_id=claimed["attemptId"])
    assert not store.commit_job_result(job["id"], result, worker_id=identity["workerId"], attempt_id=claimed["attemptId"])
    assert store.leaderboard()[0]["rating"] == 825
    assert store.set_remote_worker_status(identity["workerId"], "revoked")
    assert store.authenticate_remote_worker(identity["workerId"], identity["credential"]) is None
    replacement = store.register_remote_worker(store.issue_worker_registration(), "Laptop A", "2026.10.09")
    assert replacement["workerId"] == identity["workerId"]
    assert replacement["credential"] != identity["credential"]


def test_registration_records_independent_worker_capacity(tmp_path):
    store = PlatformStore(tmp_path / "worker-capacity.db")
    first = store.register_remote_worker(store.issue_worker_registration(), "Slot One", "2026.10.09", 1)
    second = store.register_remote_worker(store.issue_worker_registration(), "Slot Two", "2026.10.09", 1)
    assert first["workerId"] != second["workerId"]
    workers = {item["id"]: item for item in store.remote_worker_metrics()["items"]}
    assert workers[first["workerId"]]["maxConcurrency"] == 1
    assert workers[second["workerId"]]["maxConcurrency"] == 1


def test_remote_cancellation_and_expired_lease_recovery(tmp_path):
    store = PlatformStore(tmp_path / "leases.db")
    identity = registered(store)
    store.register_team("worker_team")
    first = store.create_job("worker_team", "sandbox", opponent="random", seed=1)
    claimed = store.claim_remote_job(identity["workerId"], "2026.10.09")
    assert claimed["id"] == first["id"]
    store.request_job_cancel(first["id"], "Organizer stop")
    assert store.remote_heartbeat(identity["workerId"], {}, first["id"], claimed["attemptId"])["cancel"]
    assert not store.commit_job_result(first["id"], {}, worker_id=identity["workerId"], attempt_id=claimed["attemptId"])
    second = store.create_job("worker_team", "sandbox", opponent="random", seed=2)
    claimed = store.claim_remote_job(identity["workerId"], "2026.10.09")
    with store.session() as db:
        row = db.get(SimulationJob, second["id"])
        row.lease_expires_at = utc_now() - timedelta(seconds=1)
    assert store.recover_remote_leases() == 1
    reassigned = store.claim_remote_job(identity["workerId"], "2026.10.09")
    assert reassigned["id"] == second["id"]
    assert reassigned["attemptId"] != claimed["attemptId"]
    assert not store.commit_job_result(second["id"], {}, worker_id=identity["workerId"], attempt_id=claimed["attemptId"])


def test_independent_workers_claim_distinct_jobs_and_fence_progress(tmp_path):
    store = PlatformStore(tmp_path / "multiworker.db")
    first_worker = registered(store, "Independent One")
    second_worker = registered(store, "Independent Two")
    assert store.set_remote_concurrency(first_worker["workerId"], 1)
    assert store.set_remote_concurrency(second_worker["workerId"], 1)
    store.register_team("first_team")
    store.register_team("second_team")
    first_job = store.create_job("first_team", "sandbox", opponent="random", seed=1)
    second_job = store.create_job("second_team", "sandbox", opponent="random", seed=2)
    first = store.claim_remote_job(first_worker["workerId"], "2026.10.09")
    second = store.claim_remote_job(second_worker["workerId"], "2026.10.09")
    assert {first["id"], second["id"]} == {first_job["id"], second_job["id"]}
    assert store.record_remote_progress(first["id"], first_worker["workerId"], first["attemptId"],
                                        "match", "running", "1/6", 1, 6)
    assert store.get_job_status(first["id"])["progressCurrent"] == 1
    assert not store.record_remote_progress(first["id"], second_worker["workerId"], second["attemptId"],
                                            "match", "running", "stolen", 6, 6)
    with store.session() as db:
        db.get(SimulationJob, first["id"]).lease_expires_at = utc_now() - timedelta(seconds=1)
    assert store.recover_remote_leases() == 1
    replacement = store.claim_remote_job(second_worker["workerId"], "2026.10.09")
    assert replacement is None  # Its one available slot is still occupied.
    replacement = store.claim_remote_job(first_worker["workerId"], "2026.10.09")
    assert replacement["id"] == first["id"]
    assert replacement["attemptId"] != first["attemptId"]
    assert not store.record_remote_progress(first["id"], first_worker["workerId"], first["attemptId"],
                                            "match", "completed", "stale", 6, 6)
    assert store.record_remote_progress(first["id"], first_worker["workerId"], replacement["attemptId"],
                                        "match", "completed", "2/6", 2, 6)
    assert store.get_job_status(first["id"])["progressCurrent"] == 2


def test_official_game_checkpoints_survive_reassignment_and_fence_result(tmp_path):
    store = PlatformStore(tmp_path / "checkpoint.db")
    first_worker = registered(store, "Checkpoint One")
    second_worker = registered(store, "Checkpoint Two")
    team = store.register_team("checkpoint_team")
    submission = store.create_submission(team["team"], "submissions/checkpoint.py", valid=True)
    open_round_one(store)
    config = {"opponents": ["ref_1"], "seeds": [7], "sides": [0, 1],
              "weights": {"win_rate": 0.6, "economic": 0.4},
              "economic_scale": 1000, "rating_scale": 1000}
    payload = {**official_payload(), "evaluationConfig": config, "checkpointRequired": True}
    job = store.create_job(team["team"], "official", submission_id=submission["id"],
                           payload=payload, progress_total=2)
    first = store.claim_remote_job(first_worker["workerId"], "2026.10.09")
    game_one = {"opponent": "ref_1", "seed": 7, "side": 0,
                "contestantMoney": 1100.0, "opponentMoney": 900.0, "replayId": "a" * 32}
    assert store.record_official_game(job["id"], first_worker["workerId"],
                                      first["attemptId"], 1, game_one)
    with store.session() as db:
        db.get(SimulationJob, job["id"]).lease_expires_at = utc_now() - timedelta(seconds=1)
    assert store.recover_remote_leases() == 1
    assert store.get_job_status(job["id"])["progressCurrent"] == 1
    second = store.claim_remote_job(second_worker["workerId"], "2026.10.09")
    assert second["id"] == job["id"] and second["attemptId"] != first["attemptId"]
    assert store.official_game_checkpoints(job["id"]) == [{"index": 1, "game": game_one}]
    assert not store.record_official_game(job["id"], first_worker["workerId"],
                                          first["attemptId"], 2, game_one)
    game_two = {"opponent": "ref_1", "seed": 7, "side": 1,
                "contestantMoney": 950.0, "opponentMoney": 1000.0, "replayId": "b" * 32}
    assert store.record_official_game(job["id"], second_worker["workerId"],
                                      second["attemptId"], 2, game_two)
    result = {**aggregate_games([game_one, game_two], config), "status": "complete",
              "matchResults": [game_one, game_two]}
    altered = {**result, "rating": result["rating"] + 1}
    assert not store.commit_job_result(job["id"], altered, worker_id=second_worker["workerId"],
                                       attempt_id=second["attemptId"])
    assert store.commit_job_result(job["id"], result, worker_id=second_worker["workerId"],
                                   attempt_id=second["attemptId"])
    assert not store.commit_job_result(job["id"], result, worker_id=second_worker["workerId"],
                                       attempt_id=second["attemptId"])


def test_official_game_http_requires_replay_and_active_attempt(monkeypatch, tmp_path):
    import backend.remote_workers as api

    store = PlatformStore(tmp_path / "game-http.db")
    blobs = LocalObjectStorage(tmp_path / "objects")
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "objects", blobs)
    identity = registered(store, "Game Checkpoint HTTP")
    team = store.register_team("game_http_team")
    submission = store.create_submission(team["team"], "submissions/game-http.py", valid=True)
    open_round_one(store)
    config = {"opponents": ["ref_1"], "seeds": [7], "sides": [0],
              "weights": {"win_rate": 0.6, "economic": 0.4},
              "economic_scale": 1000, "rating_scale": 1000}
    job = store.create_job(team["team"], "official", submission_id=submission["id"],
                           payload={**official_payload(), "evaluationConfig": config,
                                    "checkpointRequired": True}, progress_total=1)
    claimed = store.claim_remote_job(identity["workerId"], "2026.10.09")
    headers = {"Authorization": f"Bearer {identity['workerId']}.{identity['credential']}"}
    route = f"/api/remote-workers/jobs/{job['id']}/game"
    game = {"opponent": "ref_1", "seed": 7, "side": 0,
            "contestantMoney": 1100.0, "opponentMoney": 900.0, "replayId": "c" * 32}
    body = {"attemptId": claimed["attemptId"], "index": 1, "game": game}
    with TestClient(app) as client:
        assert client.post(route, json=body).status_code == 401
        assert client.post(route, headers=headers, json=body).status_code == 409
        blobs.put_bytes(f"replays/{game['replayId']}.json", b"{}")
        assert client.post(route, headers=headers, json=body).status_code == 200
        assert client.post(route, headers=headers, json=body).status_code == 200
        assert client.post(route, headers=headers,
                           json={**body, "game": {**game, "contestantMoney": 9999}}).status_code == 409
        assert client.post(route, headers=headers,
                           json={**body, "attemptId": "stale"}).status_code == 409


def test_remote_http_scopes_and_verified_source(monkeypatch, tmp_path):
    import backend.remote_workers as api

    store = PlatformStore(tmp_path / "api.db")
    blobs = LocalObjectStorage(tmp_path / "objects")
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "objects", blobs)
    identity = registered(store)
    store.register_team("api_team")
    blobs.put_bytes("submissions/agent.py", b"def agent(obs): return {'farmer': ['PASS']}")
    submission = store.create_submission("api_team", "submissions/agent.py", valid=True)
    job = store.create_job("api_team", "sandbox", submission_id=submission["id"], opponent="random", seed=1)
    headers = {"Authorization": f"Bearer {identity['workerId']}.{identity['credential']}"}
    with TestClient(app) as client:
        assert client.get("/api/remote-workers/me").status_code == 401
        own = client.get("/api/remote-workers/me", headers=headers)
        assert own.status_code == 200
        assert own.json()["id"] == identity["workerId"]
        assert "credential" not in own.json()
        assert client.post("/api/remote-workers/claim").status_code == 401
        claimed = client.post("/api/remote-workers/claim", headers=headers).json()["job"]
        assert claimed["id"] == job["id"]
        params = {"attemptId": claimed["attemptId"]}
        source = client.get(f"/api/remote-workers/jobs/{job['id']}/source/{submission['id']}",
                            headers=headers, params=params)
        assert source.status_code == 200
        assert source.content.startswith(b"def agent")
        replay_id = "a" * 32
        replay_data = b'{"steps":[1,2,3]}'
        uploaded = client.put(f"/api/remote-workers/jobs/{job['id']}/replay/{replay_id}",
                              headers={**headers, "Content-Encoding": "gzip"}, params=params,
                              content=gzip.compress(replay_data))
        assert uploaded.status_code == 200
        assert blobs.get_bytes(f"replays/{replay_id}.json") == replay_data
        assert client.put(f"/api/remote-workers/jobs/{job['id']}/replay/{replay_id}",
                          headers={**headers, "Content-Encoding": "gzip"}, params=params,
                          content=b"invalid gzip").status_code == 400
        assert client.post(f"/api/remote-workers/jobs/{job['id']}/result", headers=headers,
            json={"attemptId": "incorrect", "result": {"status": "success"}}).status_code == 409


def test_admin_registration_toggle_and_single_use_http(monkeypatch, tmp_path):
    import backend.remote_workers as api

    store = PlatformStore(tmp_path / "registration.db")
    monkeypatch.setattr(api, "store", store)
    salt = "remote-test"
    digest = hashlib.pbkdf2_hmac("sha256", b"test-password", salt.encode(), 1000).hex()
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"pbkdf2_sha256$1000${salt}${digest}")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "remote-test-session-secret-that-is-long-enough")
    with TestClient(app) as client:
        assert client.post("/api/admin/remote-workers/registration").status_code == 401
        login = client.post("/api/admin/login", json={"password": "test-password"})
        csrf = {"X-Admin-CSRF": login.json()["csrfToken"]}
        issued = client.post("/api/admin/remote-workers/registration", headers=csrf)
        assert issued.status_code == 200
        token = issued.json()["token"]
        data = {"token": token, "name": "Laptop A", "version": api.VERSION}
        assert client.post("/api/remote-workers/register", json=data).status_code == 200
        assert client.post("/api/remote-workers/register", json={**data, "name": "Laptop B"}).status_code == 409
        assert client.post("/api/admin/remote-workers/registration/disable", headers=csrf,
                           json={"confirmation": "DISABLE"}).status_code == 200
        assert client.post("/api/admin/remote-workers/registration", headers=csrf).status_code == 423


def test_unverified_cloud_mode_is_rejected_and_local_claims_are_fenced(monkeypatch, tmp_path):
    import backend.remote_workers as api

    store = PlatformStore(tmp_path / "mode.db")
    monkeypatch.setattr(api, "store", store)
    identity = registered(store)
    store.register_team("mode_team")
    queued = store.create_job("mode_team", "sandbox", opponent="random", seed=17)
    assert store.evaluator_mode_state() == {"activeMode": "LOCAL", "generation": 1,
                                             "cloudEvaluationAvailable": False}
    salt = "mode-test"
    digest = hashlib.pbkdf2_hmac("sha256", b"test-password", salt.encode(), 1000).hex()
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"pbkdf2_sha256$1000${salt}${digest}")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "mode-test-session-secret-that-is-long-enough")
    with TestClient(app) as client:
        login = client.post("/api/admin/login", json={"password": "test-password"})
        csrf = {"X-Admin-CSRF": login.json()["csrfToken"]}
        route = "/api/admin/remote-workers/evaluator-mode"
        assert client.get(route, headers=csrf).json()["activeMode"] == "LOCAL"
        blocked = client.post(route, headers=csrf,
                              json={"mode": "AZURE_CLOUD", "confirmation": "SWITCH TO AZURE_CLOUD"})
        assert blocked.status_code == 423
        assert store.evaluator_mode_state()["activeMode"] == "LOCAL"
    claimed = store.claim_remote_job(identity["workerId"], "2026.10.09")
    assert claimed["id"] == queued["id"]
    # Simulate an operator-side mode fence, including an outstanding attempt.
    with store.session() as db:
        db.add(RemoteControl(id=1, evaluator_mode="AZURE_CLOUD", evaluator_generation=2))
    assert store.claim_remote_job(identity["workerId"], "2026.10.09") is None
    assert not store.remote_attempt_valid(queued["id"], identity["workerId"], claimed["attemptId"])
    assert store.remote_heartbeat(identity["workerId"], {}, queued["id"], claimed["attemptId"])["cancel"]
    assert not store.commit_job_result(queued["id"], {"status": "success"},
                                       worker_id=identity["workerId"], attempt_id=claimed["attemptId"])
