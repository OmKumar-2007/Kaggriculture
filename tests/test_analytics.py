import json
import tempfile
import unittest
from pathlib import Path

from backend.services.analytics import analyze_replay, replay_frame


class AnalyticsTests(unittest.TestCase):
    def test_derives_only_recorded_metrics(self):
        farm = {
            "money": 3200, "farmer": [1, 1], "hands": [[2, 1]],
            "unlocked_quadrants": ["NW"],
            "tiles": [[None, {"kind": "PLANT", "crop": "WHEAT"}], ["LOCKED", {"kind": "COOP", "animal": "GOOSE"}]],
        }
        observations = [
            {"day": 0, "hour": 0, "farms": [dict(farm, money=3000), {}], "market": {"prices": {"WHEAT": 25}}},
            {"day": 0, "hour": 1, "farms": [farm, {}], "market": {"prices": {"WHEAT": 26}}},
        ]
        replay = {"steps": [
            [{"observation": observations[0], "action": {"farmer": ["PLANT", "WHEAT"], "hands": [["PASS"]], "market": [["HIRE"]]}, "reward": 0}, {}],
            [{"observation": observations[1], "action": {"farmer": ["EAST"], "hands": [["HARVEST"]], "market": [["SELL", "WHEAT", 2]]}, "reward": 3200}, {}],
        ]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            path.write_text(json.dumps(replay), encoding="utf-8")
            metrics = analyze_replay(path)
            frame = replay_frame(path, 99)
        self.assertEqual(metrics["finalCash"], 3200)
        self.assertEqual(metrics["plantsPlanted"], 1)
        self.assertEqual(metrics["plantsHarvested"], 1)
        self.assertEqual(metrics["workersHired"], 1)
        self.assertEqual(metrics["productsSold"], {"WHEAT": 2})
        self.assertIn("movementRate", metrics)
        self.assertIn("diagnostics", metrics)
        self.assertEqual(frame["step"], 1)


if __name__ == "__main__":
    unittest.main()
