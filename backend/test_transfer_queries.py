"""Keep frequently polled dashboard reads away from large evaluation results."""
from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event

from backend.services.storage import PlatformStore, SimulationJob, TeamStrategy, utc_now


class TransferQueryTests(unittest.TestCase):
    def test_job_status_skips_large_result_and_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlatformStore(Path(directory) / "arena.sqlite")
            team = store.register_team("StatusProbe")
            job_id = str(uuid4())
            with store.session() as db:
                db.add(SimulationJob(
                    id=job_id, team_id=team["id"], type="sandbox",
                    queue_name="sandbox", status="completed",
                    result_json='{"large":"' + 'x' * 100_000 + '"}',
                    payload_json='{"large":"' + 'y' * 100_000 + '"}',
                ))
            statements = []
            def record(_connection, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().lower().startswith("select"):
                    statements.append(statement.lower())
            event.listen(store.engine, "before_cursor_execute", record)
            try:
                status = store.get_job_status(job_id)
            finally:
                event.remove(store.engine, "before_cursor_execute", record)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["team"], "StatusProbe")
            self.assertNotIn("result", status)
            self.assertFalse(any("simulation_jobs.result_json" in sql or
                                 "simulation_jobs.payload_json" in sql for sql in statements))

    def test_polled_metrics_use_status_columns_without_result_json(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlatformStore(Path(directory) / "arena.sqlite")
            team = store.register_team("TransferProbe")
            now = utc_now()
            with store.session() as db:
                db.add(TeamStrategy(team_id=team["id"], mission_id="growth"))
                db.add(SimulationJob(
                    id=str(uuid4()), team_id=team["id"], type="official",
                    queue_name="official", status="completed",
                    created_at=now - timedelta(seconds=10),
                    started_at=now - timedelta(seconds=5), completed_at=now,
                    result_json='{"large":"' + 'x' * 100_000 + '"}',
                ))
            statements = []

            def record(_connection, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().lower().startswith("select"):
                    statements.append(statement.lower())

            event.listen(store.engine, "before_cursor_execute", record)
            try:
                metrics = store.admin_metrics()
                contestants = store.contestant_metrics()
            finally:
                event.remove(store.engine, "before_cursor_execute", record)

            self.assertEqual(metrics["completed"], 1)
            self.assertEqual(contestants[0]["officialStatus"], "evaluated")
            self.assertEqual(contestants[0]["savedStrategy"], "growth")
            self.assertFalse(any("simulation_jobs.result_json" in sql for sql in statements))


if __name__ == "__main__":
    unittest.main()
