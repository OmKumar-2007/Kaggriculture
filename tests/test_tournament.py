import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tournament import run_tournament
from backend.jobs import _run_tournament


class TournamentTests(unittest.TestCase):
    def participants(self, count):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        result = []
        for index in range(count):
            path = root / f"p{index}.py"
            path.write_text("def agent(obs): return {}", encoding="utf-8")
            result.append({"username": f"p{index}", "filePath": str(path)})
        return result

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def test_final_swaps_sides_and_aggregates(self):
        calls = []
        favored = [None]
        def fake_match(first, second, seed):
            calls.append((first["username"], second["username"], seed))
            favored[0] = favored[0] or first["username"]
            p1_wins = first["username"] == favored[0]
            return {"p1Score": 200 if p1_wins else 100, "p2Score": 100 if p1_wins else 200,
                    "winner": 0 if p1_wins else 1, "tie": False}
        with patch("tournament.run_match", side_effect=fake_match):
            result = run_tournament(self.participants(2), random_seed=1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:2], tuple(reversed(calls[1][:2])))
        self.assertEqual(result["history"][0]["legs"], 2)

    def test_bye_advances_without_a_match(self):
        events = []
        def first_named_wins(first, second, seed):
            p1_wins = first["username"] < second["username"]
            return {"p1Score": 200 if p1_wins else 100, "p2Score": 100 if p1_wins else 200,
                    "winner": 0 if p1_wins else 1, "tie": False}
        with patch("tournament.run_match", side_effect=first_named_wins):
            result = run_tournament(self.participants(3), random_seed=2, on_progress=lambda event, data: events.append((event, data)))
        first_round = next(data for event, data in events if event == "ROUND_START")
        self.assertIsNotNone(first_round["byePlayer"])
        self.assertIsNotNone(result["champion"])

    def test_contestant_failure_is_recorded_and_tournament_continues(self):
        def failed_match(first, second, seed):
            bad_is_first = first["username"] == "p0"
            return {"p1Score": 0 if bad_is_first else 100, "p2Score": 100 if bad_is_first else 0,
                    "winner": 1 if bad_is_first else 0, "tie": False,
                    "failure": {"type": "contestant", "player": 0 if bad_is_first else 1}}
        with patch("tournament.run_match", side_effect=failed_match):
            result = run_tournament(self.participants(2), random_seed=1)
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["history"][0]["failures"]), 2)

    def test_tied_series_replays_with_next_seed(self):
        seeds = []
        favored = [None]
        def fake_match(first, second, seed):
            seeds.append(seed)
            if seed == 10:
                return {"p1Score": 100, "p2Score": 100, "winner": None, "tie": True}
            favored[0] = favored[0] or first["username"]
            p1_wins = first["username"] == favored[0]
            return {"p1Score": 200 if p1_wins else 100, "p2Score": 100 if p1_wins else 200,
                    "winner": 0 if p1_wins else 1, "tie": False}
        with patch("tournament.run_match", side_effect=fake_match):
            result = run_tournament(self.participants(2), seed=10, random_seed=1)
        self.assertEqual(seeds, [10, 10, 11, 11])
        self.assertEqual(result["history"][0]["tieReplays"], 1)

    def test_persistent_exact_tie_uses_reproducible_seeded_draw(self):
        seeds = []
        events = []
        def tied_match(_first, _second, seed):
            seeds.append(seed)
            return {"p1Score": 100, "p2Score": 100, "winner": None, "tie": True}
        participants = self.participants(2)
        with patch("tournament.run_match", side_effect=tied_match):
            first = run_tournament(participants, random_seed=42,
                                   on_progress=lambda event, data: events.append((event, data)))
            second = run_tournament(participants, random_seed=42)
        self.assertIsNone(first["error"])
        self.assertEqual(first["champion"], second["champion"])
        self.assertEqual(first["history"][0]["tieReplays"], 10)
        self.assertEqual(first["history"][0]["tieBreak"], "seeded_lot")
        self.assertEqual(first["history"][0]["p1Score"], first["history"][0]["p2Score"])
        self.assertEqual(len(seeds), 44)
        self.assertEqual([event for event, _ in events].count("MATCH_END"), 1)

    def test_progress_persistence_failure_stops_tournament(self):
        def reject_progress(event, _data):
            if event == "ROUND_START":
                raise OSError("database unavailable")
        with patch("tournament.run_match") as match:
            with self.assertRaisesRegex(OSError, "database unavailable"):
                run_tournament(self.participants(2), random_seed=1, on_progress=reject_progress)
        match.assert_not_called()

    def test_champion_and_match_history_do_not_expose_source_paths(self):
        def match(first, second, _seed):
            first_wins = first["username"] == "p0"
            return {"p1Score": 200 if first_wins else 100, "p2Score": 100 if first_wins else 200,
                    "winner": 0 if first_wins else 1, "tie": False}
        with patch("tournament.run_match", side_effect=match):
            result = run_tournament(self.participants(2), random_seed=1)
        self.assertEqual(set(result["champion"]), {"username"})
        self.assertNotIn("player1File", result["history"][0])
        self.assertNotIn("player2File", result["history"][0])

    def test_final_keeps_both_real_replay_identifiers(self):
        calls = ["a" * 32, "b" * 32]
        def match(_first, _second, _seed):
            replay_id = calls.pop(0)
            return {"p1Score": 300 if replay_id.startswith("a") else 100,
                    "p2Score": 100 if replay_id.startswith("a") else 200,
                    "winner": 0 if replay_id.startswith("a") else 1,
                    "tie": False, "replayId": replay_id}
        with patch("tournament.run_match", side_effect=match):
            result = run_tournament(self.participants(2), random_seed=1)
        self.assertEqual(result["history"][0]["replayIds"], ["a" * 32, "b" * 32])

    def test_aborted_tournament_is_not_a_successful_job_result(self):
        import hashlib
        job = {"id": "test-job", "type": "tournament"}
        source=b"def agent(obs): return {}"
        roster=[{"team":name,"objectKey":f"test/{name}","sha256":hashlib.sha256(source).hexdigest(),"seed":i} for i,name in enumerate(("p0","p1"),1)]
        with patch("backend.jobs.store.job_payload", return_value={"roster":roster}), \
             patch("backend.jobs.objects.get_bytes", return_value=source), \
             patch("backend.jobs.store.get_tournament_state", return_value={}), \
             patch("tournament.run_seeded_tournament", return_value={"champion": None, "history": [], "error": "match failed"}):
            with self.assertRaisesRegex(RuntimeError, "Tournament aborted: match failed"):
                _run_tournament(job)


if __name__ == "__main__":
    unittest.main()
