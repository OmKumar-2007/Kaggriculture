import tempfile
import unittest
from pathlib import Path

from backend.services.storage import PlatformStore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PlatformStore(Path(self.temp.name) / "test.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_submission_history_is_versioned_and_preserved(self):
        first = self.store.create_submission("TeamOne", Path("v1/agent.py"), valid=True)
        second = self.store.create_submission("TeamOne", Path("v2/agent.py"), valid=False, errors="syntax")
        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        history = self.store.list_submissions("teamone")
        self.assertEqual([item["version"] for item in history], [2, 1])
        self.assertEqual(history[0]["validation_errors"], "syntax")

    def test_active_submission_is_identifiable(self):
        first = self.store.create_submission("TeamOne", Path("v1/agent.py"), valid=True)
        second = self.store.create_submission("TeamOne", Path("v2/agent.py"), valid=True)
        self.store.activate_submission("TeamOne", first["id"])
        self.assertTrue(self.store.summary("TeamOne")["activeSubmission"]["is_active"])
        self.store.activate_submission("TeamOne", second["id"])
        active = self.store.summary("TeamOne")["activeSubmission"]
        self.assertEqual(active["version"], 2)

    def test_sandbox_result_updates_score_without_overwriting_history(self):
        submission = self.store.create_submission("TeamOne", Path("v1/agent.py"), valid=True)
        result = {
            "opponent": "balanced", "seed": 7, "status": "success", "winner": "bot",
            "botFinalMoney": 5000.0, "opponentFinalMoney": 3000.0,
            "runtimeSeconds": 1.5, "error": None,
        }
        self.store.record_sandbox(submission["id"], result)
        summary = self.store.summary("TeamOne")
        self.assertEqual(summary["bestScore"], 5000.0)
        self.assertEqual(summary["lastTest"]["opponent"], "balanced")


if __name__ == "__main__":
    unittest.main()
