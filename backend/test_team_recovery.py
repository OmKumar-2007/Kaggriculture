"""Organizer recovery contract against an isolated temporary database."""
import hashlib
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import admin
from backend.services import participants
from backend.services.storage import PlatformStore, Team, utc_now


class TeamRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(Path(self.temp.name) / "recovery.sqlite")
        self.store.register_team("Alpha")
        self.patches = [patch.object(admin, "store", self.store),
                        patch.object(participants, "store", self.store),
                        patch.dict(os.environ, {"SESSION_BACKEND": "postgres"})]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        app = FastAPI()
        app.include_router(admin.router)
        app.include_router(participants.router)
        self.client = TestClient(app)
        self.app = app

    def issue(self):
        self.app.dependency_overrides[admin.require_admin] = lambda: "test-admin"
        response = self.client.post("/api/admin/contestants/Alpha/recovery",
                                    json={"confirmation": "RESET SESSION"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["recoveryCode"]

    def recover(self, code, team="Alpha"):
        return self.client.post("/api/participants/recover", json={"team": team, "recoveryCode": code})

    def test_admin_only_issuance_and_four_character_success(self):
        denied = self.client.post("/api/admin/contestants/Alpha/recovery",
                                  json={"confirmation": "RESET SESSION"})
        self.assertEqual(denied.status_code, 401)
        code = self.issue()
        self.assertRegex(code, r"^[ACDEFHJKMNPQRTUVWXY3479]{4}$")
        with self.store.session() as db:
            team = db.query(Team).filter_by(username="Alpha").one()
            self.assertNotEqual(team.recovery_hash, code)
            self.assertEqual(team.recovery_hash, hashlib.sha256(code.encode()).hexdigest())
        self.assertEqual(self.recover(code).status_code, 200)
        self.assertEqual(self.recover(code).status_code, 401)

    def test_lowercase_and_legacy_unexpired_code(self):
        code = self.issue()
        self.assertEqual(self.recover(code.lower()).status_code, 200)
        legacy = "oldCaseSensitiveRecoveryToken123"
        self.store.issue_team_recovery("Alpha", hashlib.sha256(legacy.encode()).hexdigest(),
                                       utc_now() + timedelta(minutes=15))
        self.assertEqual(self.recover(legacy).status_code, 200)

    def test_invalid_and_expired_codes(self):
        code = self.issue()
        self.assertEqual(self.recover("ZZZZ").status_code, 401)
        with self.store.session() as db:
            db.query(Team).filter_by(username="Alpha").one().recovery_expires_at = utc_now() - timedelta(seconds=1)
        self.assertEqual(self.recover(code).status_code, 401)

    def test_team_and_ip_attempt_limits(self):
        self.issue()
        for _ in range(8):
            self.assertEqual(self.recover("ZZZZ").status_code, 401)
        self.assertEqual(self.recover("ZZZZ").status_code, 429)
        for index in range(5):
            self.store.register_team(f"Other{index}")
        # Same IP stays limited even when guessing different teams.
        for index in range(32):
            self.recover("ZZZZ", f"Other{index % 5}")
        self.assertEqual(self.recover("ZZZZ", "Other0").status_code, 429)

    def test_issue_and_redeem_revoke_existing_session(self):
        original = self.store.team_identity_by_name("Alpha")
        response = self._response()
        old_session = participants._create_session(original, self._request(), response)
        self.assertEqual(old_session["team"], "Alpha")
        token = response.headers["set-cookie"].split("=", 1)[1].split(";", 1)[0]
        old_request = self._request(token)
        self.assertEqual(participants.current_session(old_request)["team"], "Alpha")
        old_version = original["sessionVersion"]
        code = self.issue()
        self.assertGreater(self.store.team_identity_by_name("Alpha")["sessionVersion"], old_version)
        with self.assertRaises(participants.HTTPException):
            participants.current_session(old_request)
        self.assertEqual(self.recover(code).status_code, 200)
        self.assertGreater(self.store.team_identity_by_name("Alpha")["sessionVersion"], old_version + 1)

    @staticmethod
    def _request(token=None):
        from starlette.requests import Request
        headers = [(b"cookie", f"{participants.COOKIE}={token}".encode())] if token else []
        return Request({"type": "http", "method": "GET", "scheme": "http", "path": "/",
                        "headers": headers, "client": ("127.0.0.1", 1234), "server": ("testserver", 80)})

    @staticmethod
    def _response():
        from starlette.responses import Response
        return Response()


if __name__ == "__main__":
    unittest.main()
