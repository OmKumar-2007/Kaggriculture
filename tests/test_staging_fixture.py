import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.admin import (ActionPayload, _require_staging_fixture,
                           queue_staging_fixture, queue_isolated_staging_fixture,
                           require_admin)
from backend.main import app
from backend.services.blob_storage import LocalObjectStorage
from backend.services.storage import PlatformStore


STAGING_ENV = {
    "FARMCRAFT_STAGING_FIXTURE_ENABLED": "1",
    "DATABASE_URL": "postgresql+psycopg://user:example@farmcraftstgpg20261012omk.postgres.database.azure.com/farmcraft_test",
    "AZURE_STORAGE_ACCOUNT_URL": "https://fcstg6chsyox4t2zfa.blob.core.windows.net",
    "QUEUE_BACKEND": "postgres",
}
CLOSED_EVENT = {
    "mode": "MAINTENANCE", "registrationsEnabled": False,
    "uploadsEnabled": False, "sandboxEnabled": False,
    "officialEnabled": False, "tournamentEnabled": False,
}


class StagingFixtureGateTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                _require_staging_fixture("SETUP")
        self.assertEqual(caught.exception.status_code, 404)

    def test_rejects_other_database_or_storage(self):
        for key, value in (
            ("DATABASE_URL", "postgresql://user:example@production.example/db"),
            ("AZURE_STORAGE_ACCOUNT_URL", "https://other.blob.core.windows.net"),
        ):
            with self.subTest(key=key), patch.dict("os.environ", {**STAGING_ENV, key: value}, clear=True):
                with self.assertRaises(HTTPException) as caught:
                    _require_staging_fixture("SETUP")
                self.assertEqual(caught.exception.status_code, 404)

    def test_public_controls_must_stay_closed(self):
        for key in ("registrationsEnabled", "uploadsEnabled", "sandboxEnabled",
                    "officialEnabled", "tournamentEnabled"):
            with self.subTest(key=key), patch.dict("os.environ", STAGING_ENV, clear=True):
                with patch("backend.admin.store.event_config", return_value={**CLOSED_EVENT, key: True}):
                    with self.assertRaises(HTTPException) as caught:
                        _require_staging_fixture("SETUP")
                self.assertEqual(caught.exception.status_code, 409)

    def test_accepts_only_requested_phase(self):
        with patch.dict("os.environ", STAGING_ENV, clear=True):
            with patch("backend.admin.store.event_config", return_value=CLOSED_EVENT):
                with patch("backend.admin.store.competition", return_value={"phase": "SETUP"}):
                    self.assertEqual(_require_staging_fixture("SETUP"), {"phase": "SETUP"})
                    with self.assertRaises(HTTPException) as caught:
                        _require_staging_fixture("QUALIFICATION_OPEN")
        self.assertEqual(caught.exception.status_code, 409)

    def test_queue_requires_exact_six_game_snapshot(self):
        snapshot = {"phase": "QUALIFICATION_OPEN", "referencePool": [{"id": i} for i in range(3)],
                    "evaluationConfig": {"opponents": [f"ref_{i}" for i in range(3)],
                                         "seeds": [7], "sides": [0, 1]}}
        submission = {"id": 42, "validation_status": "valid", "object_key": "fixture/agent.py"}
        job = {"id": "fixture-job"}
        with patch("backend.admin._require_staging_fixture", return_value=snapshot), \
             patch("backend.admin.store.current_submission", return_value=submission), \
             patch("backend.admin.objects.get_bytes", return_value=b"def agent(obs): pass"), \
             patch("backend.admin.store.create_job", return_value=job) as create_job, \
             patch("backend.services.queueing.enqueue") as enqueue, \
             patch("backend.admin.store.record_audit"):
            result = queue_staging_fixture(ActionPayload(confirmation="QUEUE SIX STAGING GAMES"))
        self.assertEqual(result["games"], 6)
        self.assertEqual(create_job.call_args.kwargs["progress_total"], 6)
        self.assertEqual(create_job.call_args.kwargs["payload"]["evaluationConfig"], snapshot["evaluationConfig"])
        enqueue.assert_called_once_with(job)

        snapshot["evaluationConfig"]["seeds"] = [7, 8]
        with patch("backend.admin._require_staging_fixture", return_value=snapshot):
            with self.assertRaises(HTTPException) as caught:
                queue_staging_fixture(ActionPayload(confirmation="QUEUE SIX STAGING GAMES"))
        self.assertEqual(caught.exception.status_code, 409)

    def test_isolated_fixture_requires_rehearsal_identity_and_one_frozen_schedule(self):
        team = "staging_fixture_" + "a" * 32
        snapshot = {"phase": "QUALIFICATION_OPEN", "referencePool": [{"id": i} for i in range(3)],
                    "evaluationConfig": {"opponents": [f"ref_{i}" for i in range(3)],
                                         "seeds": [7], "sides": [0, 1]}}
        submission = {"id": 52, "validation_status": "valid", "object_key": "fixture/agent.py"}
        with patch("backend.admin._require_staging_fixture", return_value=snapshot), \
             patch("backend.admin.store.is_rehearsal_team", return_value=False):
            with self.assertRaises(HTTPException) as caught:
                queue_isolated_staging_fixture(team, ActionPayload(confirmation="QUEUE SIX STAGING GAMES"))
        self.assertEqual(caught.exception.status_code, 404)
        with patch("backend.admin._require_staging_fixture", return_value=snapshot), \
             patch("backend.admin.store.is_rehearsal_team", return_value=True), \
             patch("backend.admin.store.current_submission", return_value=submission), \
             patch("backend.admin.objects.get_bytes", return_value=b"def agent(obs): pass"), \
             patch("backend.admin.store.create_job", return_value={"id": "isolated-job"}) as create_job, \
             patch("backend.services.queueing.enqueue") as enqueue, \
             patch("backend.admin.store.record_audit"):
            result = queue_isolated_staging_fixture(team, ActionPayload(confirmation="QUEUE SIX STAGING GAMES"))
        self.assertEqual(result["games"], 6)
        self.assertEqual(create_job.call_args.args[:2], (team, "official"))
        self.assertTrue(create_job.call_args.kwargs["payload"]["checkpointRequired"])
        enqueue.assert_called_once_with({"id": "isolated-job"})

    def test_isolated_upload_creates_a_new_rehearsal_team(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            store = PlatformStore(Path(directory) / "fixture.db")
            blobs = LocalObjectStorage(Path(directory) / "objects")
            snapshot = {"phase": "QUALIFICATION_OPEN", "referencePool": [{"id": i} for i in range(3)],
                        "evaluationConfig": {"opponents": [f"ref_{i}" for i in range(3)],
                                             "seeds": [7], "sides": [0, 1]}}
            app.dependency_overrides[require_admin] = lambda: None
            try:
                with patch.dict("os.environ", STAGING_ENV, clear=False), \
                     patch("backend.admin.store", store), \
                     patch("backend.admin.objects", blobs), \
                     patch.object(store, "event_config", return_value=CLOSED_EVENT), \
                     patch.object(store, "competition", return_value=snapshot), \
                     patch("backend.admin.inspect_agent_source") as inspect:
                    inspect.return_value.valid = True
                    inspect.return_value.to_dict.return_value = {"valid": True}
                    with TestClient(app) as client:
                        response = client.post("/api/admin/staging-fixtures/upload",
                            data={"confirmation": "CREATE ISOLATED STAGING FIXTURE"},
                            files={"file": ("agent.py", b"def agent(obs): return {}", "text/x-python")})
                    self.assertEqual(response.status_code, 200, response.text)
                    team = response.json()["team"]
                    self.assertTrue(team.startswith("staging_fixture_"))
                    self.assertTrue(store.is_rehearsal_team(team))
                    self.assertIsNotNone(store.current_submission(team))
            finally:
                app.dependency_overrides.pop(require_admin, None)


if __name__ == "__main__":
    unittest.main()
