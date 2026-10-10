"""Replay routes must respect ownership and hide official source details."""

import json

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.blob_storage import LocalObjectStorage
from backend.services.storage import PlatformStore


def test_replay_routes_enforce_ownership_and_hide_uncommitted_replays(monkeypatch, tmp_path):
    import backend.main as api

    store = PlatformStore(tmp_path / "routes.db")
    blobs = LocalObjectStorage(tmp_path / "objects")
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "objects", blobs)
    monkeypatch.setattr(api, "REPLAY_DIR", tmp_path / "replays")
    store.register_team("TeamAlpha")
    submission = store.create_submission("TeamAlpha", "submissions/alpha/agent.py", valid=True)
    sandbox_id, official_id, tournament_id = "a" * 32, "b" * 32, "c" * 32
    farms = [{"money": 100, "tiles": [[None]], "farmer": [0, 0], "hands": []},
             {"money": 200, "tiles": [[None]], "farmer": [0, 0], "hands": []}]
    replay = {"steps": [[{"observation": {"farms": farms, "private": {"secret": "HIDDEN"}},
                           "action": {"farmer": ["PASS"]}, "reward": 100},
                          {"observation": {"farms": farms, "private": {"secret": "HIDDEN"}},
                           "action": {"farmer": ["PASS"]}, "reward": 200}]]}
    for replay_id in (sandbox_id, official_id, tournament_id):
        blobs.put_bytes(f"replays/{replay_id}.json", json.dumps(replay).encode(), "application/json")
    store.record_sandbox(submission["id"], {"opponent": "random", "seed": 1, "status": "success",
                                            "replayId": sandbox_id})
    store.record_tournament_game({"gameId": "GAME_1", "matchId": "R1_M1", "round": 1,
                                  "replay": 0, "leg": 0, "seed": 1, "playerZero": "TeamAlpha",
                                  "playerOne": "TeamBeta", "scoreZero": 100, "scoreOne": 200,
                                  "replayId": tournament_id})
    with TestClient(app) as client:
        assert client.get(f"/replays/{sandbox_id}/frame/0").status_code == 401
        assert client.get(f"/replays/{official_id}/playback").status_code == 404
        public = client.get(f"/replays/{tournament_id}/playback")
        assert public.status_code == 200
        assert len(public.json()["players"]) == 2
        assert "HIDDEN" not in public.text
        monkeypatch.setattr(api, "current_session", lambda request: {"team": "TeamBeta"})
        assert client.get(f"/replays/{sandbox_id}/analytics").status_code == 404
        monkeypatch.setattr(api, "current_session", lambda request: {"team": "TeamAlpha"})
        owned = client.get(f"/replays/{sandbox_id}/playback")
        assert owned.status_code == 200
        assert len(owned.json()["players"]) == 1
        assert client.get(f"/replays/{sandbox_id}/frame/0").status_code == 200
        assert client.get(f"/replays/{sandbox_id}/analytics").status_code == 200
