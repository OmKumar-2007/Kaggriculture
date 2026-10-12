import unittest
import hashlib

from backend.services.evaluation import evaluate_source, evaluation_plan
from backend.services.scoring import aggregate_games


CONFIG = {
    "seeds": [3, 7], "opponents": ["baseline_alpha"], "sides": [0, 1],
    "weights": {"win_rate": 0.6, "economic": 0.4},
    "economic_scale": 1000, "rating_scale": 1000, "qualifier_count": 16,
}


class ScoringTests(unittest.TestCase):
    def test_three_reference_single_seed_schedule_and_replays(self):
        source = "def agent(obs): return {}"
        names = ["ref_1", "ref_2", "ref_3"]
        config = {**CONFIG, "opponents": names, "seeds": [41021]}
        references = {name: {"source": source, "sha256": hashlib.sha256(source.encode()).hexdigest()}
                      for name in names}
        calls, uploads = [], []

        def runner(first, second, seed, replay):
            calls.append((first.name, second.name, seed))
            replay.write_text('{}', encoding='utf-8')
            return {"p1Score": 1500, "p2Score": 1000}

        result = evaluate_source(source, runner=runner, config=config,
                                 reference_sources=references,
                                 on_replay=lambda replay_id, data: uploads.append((replay_id, data)))
        self.assertEqual(result["games"], 6)
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(uploads), 6)
        self.assertEqual(len({row["replayId"] for row in result["matchResults"]}), 6)
        self.assertEqual([row["side"] for row in result["matchResults"]], [0, 1] * 3)
        self.assertEqual([row["opponent"] for row in result["matchResults"]],
                         [name for name in names for _ in range(2)])
        self.assertEqual(result["wins"], 3)
        self.assertTrue(all(seed == 41021 for _, _, seed in calls))

    def test_retry_reuses_completed_game_without_rerunning_or_reuploading(self):
        config = {**CONFIG, "opponents": ["baseline_alpha"], "seeds": [3]}
        saved = {"opponent": "baseline_alpha", "seed": 3, "side": 0,
                 "contestantMoney": 1200.0, "opponentMoney": 1000.0, "replayId": "a" * 32}
        calls, uploads, checkpoints = [], [], []
        def runner(first, second, seed, replay):
            calls.append((first.name, second.name))
            replay.write_text("{}", encoding="utf-8")
            return {"p1Score": 900, "p2Score": 800}
        result = evaluate_source("def agent(obs): return {}", runner=runner, config=config,
            completed_games={1: saved},
            on_replay=lambda replay_id, data: uploads.append(replay_id),
            on_game=lambda index, game: checkpoints.append(index))
        self.assertEqual(result["games"], 2)
        self.assertEqual(result["matchResults"][0], saved)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(uploads), 1)
        self.assertEqual(checkpoints, [2])

    def test_score_uses_wins_and_economy(self):
        result = aggregate_games([
            {"contestantMoney": 1200, "opponentMoney": 1000},
            {"contestantMoney": 900, "opponentMoney": 1000},
        ], CONFIG)
        self.assertEqual(result["games"], 2)
        self.assertEqual(result["winRate"], 50.0)
        self.assertGreater(result["rating"], 500)

    def test_plan_swaps_every_seed(self):
        plan = evaluation_plan(CONFIG)
        self.assertEqual(len(plan), 4)
        self.assertEqual({item["side"] for item in plan}, {0, 1})

    def test_evaluation_maps_scores_back_to_contestant(self):
        calls = []
        def fake_runner(first, second, seed, replay):
            calls.append((first.name, second.name, seed))
            return {"p1Score": 1500, "p2Score": 1000, "winner": 0}
        result = evaluate_source("def agent(obs): return {}", runner=fake_runner, config=CONFIG)
        self.assertEqual(result["games"], 4)
        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["winRate"], 50.0)
        self.assertEqual(len(calls), 4)


if __name__ == "__main__":
    unittest.main()
