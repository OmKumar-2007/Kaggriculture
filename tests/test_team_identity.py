"""Passwordless team ownership and additive migration checks."""
from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from backend.services.storage import PlatformStore, Team, utc_now


def test_case_insensitive_claim_and_persistent_strategy(tmp_path):
    path = tmp_path / "teams.db"
    store = PlatformStore(path)
    first = store.register_team("Team_Alpha")
    assert first["id"] > 0
    assert store.team_identity_by_name("team_alpha")["id"] == first["id"]
    with pytest.raises(ValueError, match="already registered"):
        store.register_team("TEAM_ALPHA")
    second = store.register_team("OtherTeam")
    store.set_team_strategy(first["id"], "livestock")
    assert PlatformStore(path).team_strategy(first["id"]) == "livestock"
    assert store.team_strategy(second["id"]) is None


def test_one_time_recovery_revokes_older_session_version(tmp_path):
    store = PlatformStore(tmp_path / "recovery.db")
    team = store.register_team("RecoveredTeam")
    digest = hashlib.sha256(b"a one time organizer token").hexdigest()
    issued = store.issue_team_recovery("recoveredteam", digest, utc_now() + timedelta(minutes=15))
    assert issued["id"] == team["id"]
    assert store.team_identity(team["id"])["sessionVersion"] == 1
    recovered = store.consume_team_recovery("RECOVEREDTEAM", digest)
    assert recovered["id"] == team["id"]
    assert recovered["sessionVersion"] == 2
    assert store.consume_team_recovery("RecoveredTeam", digest) is None


def test_concurrent_case_variants_create_one_team(tmp_path):
    path = tmp_path / "race.db"
    PlatformStore(path)

    def attempt(name):
        try:
            return PlatformStore(path).register_team(name)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("RaceTeam", "RACETEAM")))
    assert sum(item is not None for item in results) == 1
    with PlatformStore(path).session() as db:
        assert db.query(Team).count() == 1


def test_legacy_team_row_keeps_id_and_adds_identity_columns(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE teams (id INTEGER PRIMARY KEY, username VARCHAR(80) UNIQUE, created_at TIMESTAMP, is_rehearsal BOOLEAN DEFAULT 0 NOT NULL)")
    connection.execute("INSERT INTO teams (id, username, created_at, is_rehearsal) VALUES (17, 'OldTeam', '2026-01-01 00:00:00', 0)")
    connection.commit()
    connection.close()
    store = PlatformStore(path)
    assert store.team_identity_by_name("oldteam")["id"] == 17
    assert store.team_identity(17)["sessionVersion"] == 0
