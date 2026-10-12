"""Guarded, one-time reset of the 16 explicitly approved staging accounts."""

import hashlib
import json
import os
from urllib.parse import urlparse

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from sqlalchemy import create_engine, text

EXPECTED = {"Beta", "Codewarts", "Dark", "DM", "Eleven", "elonmusk", "FarmCraft",
            "Nimbus2000", "sdec_test", "team", "TeamMasterBlaster_TheWinner",
            "temp1", "TheGodfather", "X", "y", "Z"}
BACKUP_KEY = "backups/pre-load50/20261012T210047Z-314f3fca0ee0.pkl.gz"
BACKUP_SHA256 = "314f3fca0ee0fca4948a841b20940f51833a7c4d52df2002324c2de01e478e7a"
DELETE_ORDER = (
    "official_game_checkpoints", "pipeline_events", "official_submission_claims",
    "sandbox_runs", "evaluations", "participant_sessions", "team_strategies",
    "simulation_jobs", "submissions", "tournament_games", "teams",
    "shared_rate_limits", "tournament_state",
)


def main():
    assert os.environ.get("STORAGE_BACKEND") == "azure"
    assert os.environ.get("AZURE_STORAGE_CONTAINER") == "private-artifacts"
    assert urlparse(os.environ["DATABASE_URL"]).hostname == "farmcraftstgpg20261012omk.postgres.database.azure.com"
    assert urlparse(os.environ["DATABASE_URL"]).path == "/farmcraft"
    assert urlparse(os.environ["AZURE_STORAGE_ACCOUNT_URL"]).hostname == "fcstg6chsyox4t2zfa.blob.core.windows.net"
    blob = BlobServiceClient(account_url=os.environ["AZURE_STORAGE_ACCOUNT_URL"],
                             credential=DefaultAzureCredential()).get_blob_client("private-artifacts", BACKUP_KEY)
    assert hashlib.sha256(blob.download_blob().readall()).hexdigest() == BACKUP_SHA256
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(78426136)"))
        event = db.execute(text("SELECT mode, registrations_enabled, uploads_enabled, sandbox_enabled, official_enabled, tournament_enabled FROM event_config WHERE id=1 FOR UPDATE")).one()
        assert event.mode == "MAINTENANCE" and not any(event[1:])
        assert db.execute(text("SELECT phase FROM competition_state WHERE id=1 FOR UPDATE")).scalar_one() == "TOURNAMENT_COMPLETED"
        actual = set(db.execute(text("SELECT username FROM teams")).scalars())
        assert actual == EXPECTED, f"Team inventory changed: {len(actual)}"
        assert db.execute(text("SELECT count(*) FROM simulation_jobs WHERE status IN ('queued','running')")).scalar_one() == 0
        protected = {table: db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                     for table in ("reference_bots", "remote_workers", "worker_registrations", "admin_audit_log")}
        assert protected["reference_bots"] == 3
        before = {table: db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in DELETE_ORDER}
        for table in DELETE_ORDER:
            db.execute(text(f"DELETE FROM {table}"))
        db.execute(text("UPDATE competition_state SET phase='SETUP', reference_snapshot_json='[]', evaluation_config_json='{}', qualifier_roster_json='[]', standings_json='[]', started_at=NULL, updated_at=now() WHERE id=1"))
        db.execute(text("UPDATE event_config SET mode='MAINTENANCE', registrations_enabled=false, uploads_enabled=false, sandbox_enabled=false, official_enabled=false, tournament_enabled=false, leaderboard_visible=false, qualifier_count=16, registration_capacity=100, official_attempt_limit=1, reference_count=3, qualification_seed_count=1, tie_replay_limit=3, updated_at=now() WHERE id=1"))
        db.execute(text("INSERT INTO admin_audit_log (action,target,metadata_json,created_at) VALUES (:action,:target,:metadata,now())"), {
            "action": "load50_preparation_reset", "target": "azure_staging",
            "metadata": json.dumps({"backupKey": BACKUP_KEY, "backupSha256": BACKUP_SHA256,
                                    "deletedCounts": before}),
        })
        assert all(db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0 for table in DELETE_ORDER)
        assert all(db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == count
                   for table, count in protected.items() if table != "admin_audit_log")
    print(json.dumps({"result": "reset_committed", "deletedCounts": before,
                      "preservedCounts": protected, "backupKey": BACKUP_KEY}, sort_keys=True))


if __name__ == "__main__":
    main()
