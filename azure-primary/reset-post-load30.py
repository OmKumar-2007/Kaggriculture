"""Guarded final cleanup of the authorized 30-team Azure staging rehearsal."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from urllib.parse import urlparse

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from sqlalchemy import create_engine, text

EXPECTED = {f"LOAD30_20261012_{number:02d}" for number in range(1, 31)}
DELETE_ORDER = (
    "official_game_checkpoints", "pipeline_events", "official_submission_claims",
    "sandbox_runs", "evaluations", "participant_sessions", "team_strategies",
    "simulation_jobs", "submissions", "tournament_games", "teams",
    "shared_rate_limits", "tournament_state",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-key", required=True)
    parser.add_argument("--backup-sha256", required=True)
    args = parser.parse_args()
    assert args.backup_key.startswith("backups/post-load30/") and args.backup_key.endswith(".pkl.gz")
    assert len(args.backup_sha256) == 64
    assert os.environ.get("STORAGE_BACKEND") == "azure"
    assert os.environ.get("AZURE_STORAGE_CONTAINER") == "private-artifacts"
    assert urlparse(os.environ["DATABASE_URL"]).hostname == "farmcraftstgpg20261012omk.postgres.database.azure.com"
    assert urlparse(os.environ["DATABASE_URL"]).path == "/farmcraft"
    assert urlparse(os.environ["AZURE_STORAGE_ACCOUNT_URL"]).hostname == "fcstg6chsyox4t2zfa.blob.core.windows.net"
    blob = BlobServiceClient(account_url=os.environ["AZURE_STORAGE_ACCOUNT_URL"],
                             credential=DefaultAzureCredential()).get_blob_client(
                                 "private-artifacts", args.backup_key)
    assert hashlib.sha256(blob.download_blob().readall()).hexdigest() == args.backup_sha256
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(78426136)"))
        event = db.execute(text("SELECT mode, registrations_enabled, uploads_enabled, sandbox_enabled, official_enabled, tournament_enabled FROM event_config WHERE id=1 FOR UPDATE")).one()
        assert event.mode == "MAINTENANCE" and not any(event[1:])
        phase = db.execute(text("SELECT phase FROM competition_state WHERE id=1 FOR UPDATE")).scalar_one()
        assert phase == "TOURNAMENT_COMPLETED", phase
        actual = set(db.execute(text("SELECT username FROM teams")).scalars())
        assert actual == EXPECTED, f"Expected 30 approved test teams; found {len(actual)}"
        assert db.execute(text("SELECT count(*) FROM simulation_jobs WHERE status IN ('queued','running')")).scalar_one() == 0
        protected = {name: db.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()
                     for name in ("reference_bots", "remote_workers", "worker_registrations", "admin_audit_log")}
        assert protected["reference_bots"] == 3
        before = {name: db.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() for name in DELETE_ORDER}
        for name in DELETE_ORDER:
            db.execute(text(f"DELETE FROM {name}"))
        db.execute(text("UPDATE competition_state SET phase='SETUP', reference_snapshot_json='[]', evaluation_config_json='{}', qualifier_roster_json='[]', standings_json='[]', started_at=NULL, updated_at=now() WHERE id=1"))
        db.execute(text("UPDATE event_config SET mode='MAINTENANCE', registrations_enabled=false, uploads_enabled=false, sandbox_enabled=false, official_enabled=false, tournament_enabled=false, leaderboard_visible=false, qualifier_count=16, registration_capacity=100, official_attempt_limit=1, reference_count=3, qualification_seed_count=1, tie_replay_limit=3, updated_at=now() WHERE id=1"))
        db.execute(text("INSERT INTO admin_audit_log (action,target,metadata_json,created_at) VALUES (:action,:target,:metadata,now())"), {
            "action": "load30_final_reset", "target": "azure_staging",
            "metadata": json.dumps({"backupKey": args.backup_key, "backupSha256": args.backup_sha256,
                                    "deletedCounts": before}),
        })
        assert all(db.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() == 0 for name in DELETE_ORDER)
        assert all(db.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() == value
                   for name, value in protected.items() if name != "admin_audit_log")
    print(json.dumps({"result": "final_reset_committed", "deletedCounts": before,
                      "preservedCounts": protected, "backupKey": args.backup_key}, sort_keys=True))


if __name__ == "__main__":
    main()
