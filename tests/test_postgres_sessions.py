"""Shared PostgreSQL session path used by Azure instead of Redis."""
from backend.services.storage import PlatformStore


def test_session_and_rate_limit_survive_store_restart(tmp_path):
    path = tmp_path / "sessions.db"
    store = PlatformStore(path)
    team = store.register_team("AzureTeam")
    key = "arena:participant:session:opaque-token-hash"
    payload = {"team": "AzureTeam", "teamId": team["id"], "sessionVersion": 0,
               "csrf": "csrf", "created": 10, "seen": 11, "idle": False}
    store.put_participant_session(key, team["id"], payload, 300)
    assert store.bump_rate_limit("login:azure", 300) == 1
    assert store.bump_rate_limit("login:azure", 300) == 2
    reopened = PlatformStore(path)
    assert reopened.get_participant_session(key) == payload
    assert reopened.rate_limit_count("login:azure") == 2
    sessions = reopened.list_participant_sessions(team["id"])
    assert len(sessions) == 1
    assert reopened.revoke_participant_session_id(sessions[0]["id"], team["id"])
    assert reopened.get_participant_session(key) is None
    reopened.clear_rate_limit("login:azure")
    assert reopened.rate_limit_count("login:azure") == 0
