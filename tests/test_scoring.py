import unittest

from backend.services.evaluation import evaluate_source, evaluation_plan
from backend.services.scoring import aggregate_games


CONFIG = {
    "seeds": [3, 7], "opponents": ["baseline_alpha"], "sides": [0, 1],
    "weights": {"win_rate": 0.6, "economic": 0.4},
    "economic_scale": 1000, "rating_scale": 1000, "qualifier_count": 16,
}


class ScoringTests(unittest.TestCase):
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
