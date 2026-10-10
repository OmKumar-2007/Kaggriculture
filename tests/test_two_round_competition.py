import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from backend.services.bracket import aggregate_swapped_legs, bracket_capacity, opening_bracket
from backend.services.blob_storage import LocalObjectStorage
from backend.services.evaluation import evaluate_source, evaluation_plan
from backend.services.storage import PlatformStore
from backend.services.storage import utc_now
from tournament import run_seeded_tournament


SIZES = (2, 3, 4, 5, 7, 8, 10, 12, 16, 17, 24, 31, 32, 48, 50, 60, 64)


class BracketTests(unittest.TestCase):
    def test_qualification_plan_has_same_sources_seeds_and_both_sides(self):
        config={"opponents":[f"ref_{i}" for i in range(5)],"seeds":[3,7],"sides":[0,1],
                "weights":{"win_rate":.65,"economic":.35},"economic_scale":10000,"rating_scale":1000}
        source="def agent(obs): return {'farmer':['PASS'],'hands':[],'market':[]}"
        references={name:{"source":source,"sha256":__import__("hashlib").sha256(source.encode()).hexdigest()}
                    for name in config["opponents"]}
        calls=[]
        def runner(left,right,seed,replay):
            calls.append((left.name,right.name,seed))
            return {"p1Score":1000,"p2Score":900}
        result=evaluate_source(source,runner=runner,config=config,reference_sources=references)
        self.assertEqual(result["games"],20)
        self.assertEqual(len(calls),20)
        self.assertEqual(len(evaluation_plan(config)),20)
        self.assertEqual(sum(1 for left,_,_ in calls if left=="agent.py"),10)
        self.assertEqual(sum(1 for _,right,_ in calls if right=="agent.py"),10)

    def test_arbitrary_sizes_and_top_seed_byes(self):
        for count in SIZES:
            with self.subTest(count=count):
                bracket = opening_bracket([{"team": f"team_{i}"} for i in range(1, count + 1)])
                self.assertEqual(bracket["capacity"], bracket_capacity(count))
                self.assertEqual(bracket["byes"], bracket["capacity"] - count)
                self.assertEqual(bracket["requiredPairings"], count - 1)
                self.assertEqual(bracket["matches"][0]["teamA"]["seed"], 1)
                self.assertEqual(bracket["matches"][0]["teamB"]["seed"] if bracket["matches"][0]["teamB"] else None,
                                 bracket["capacity"] if count == bracket["capacity"] else None)
                byes = sorted(match["teamA"]["seed"] for match in bracket["matches"] if match["teamB"] is None)
                self.assertEqual(byes, list(range(1, bracket["byes"] + 1)))
                seeds = [player["seed"] for match in bracket["matches"]
                         for player in (match["teamA"], match["teamB"]) if player]
                self.assertEqual(sorted(seeds), list(range(1, count + 1)))

    def test_side_swapped_scores(self):
        self.assertEqual(aggregate_swapped_legs(
            {"p1Score": 5000, "p2Score": 4000},
            {"p1Score": 4700, "p2Score": 4300}), (9300, 8700))
        with self.assertRaises(ValueError):
            aggregate_swapped_legs({"p1Score": 1, "p2Score": 0, "failure": {"player": 1}},
                                   {"p1Score": 1, "p2Score": 2})

    def test_progression_every_size(self):
        def match(a, b, seed, **kwargs):
            return {"p1Score": 1000 if a["seed"] < b["seed"] else 500,
                    "p2Score": 1000 if b["seed"] < a["seed"] else 500}
        with patch("tournament.run_match", side_effect=match):
            for count in SIZES:
                with self.subTest(count=count):
                    players = [{"team": f"team_{i}", "username": f"team_{i}",
                                "seed": i, "filePath": "unused.py"} for i in range(1, count + 1)]
                    result = run_seeded_tournament(players)
                    self.assertEqual(result["champion"]["username"], "team_1")
                    self.assertEqual(len(result["history"]), count - 1)
                    self.assertTrue(all(row["legs"] == 2 for row in result["history"]))

    def test_restart_reuses_completed_pairings(self):
        players=[{"team":f"team_{i}","username":f"team_{i}","seed":i,
                  "filePath":"unused.py"} for i in range(1,5)]
        with patch("tournament.run_match",return_value={"p1Score":1000,"p2Score":900}):
            first=run_seeded_tournament(players)
        with patch("tournament.run_match",side_effect=AssertionError("Completed game reran")):
            resumed=run_seeded_tournament(players,completed_matches=first["history"])
        self.assertEqual(resumed["champion"],first["champion"])
        self.assertEqual(len(resumed["history"]),3)

    def test_restart_reuses_committed_first_leg(self):
        players=[{"username":"alpha","seed":1,"filePath":"unused.py"},
                 {"username":"beta","seed":2,"filePath":"unused.py"}]
        saved=[]
        def fail_after_first(event,data):
            if event=="GAME_END":
                saved.append(data)
                raise RuntimeError("worker interrupted")
        with patch("tournament.run_match",return_value={"p1Score":1000,"p2Score":900}):
            with self.assertRaises(RuntimeError):
                run_seeded_tournament(players,on_progress=fail_after_first)
        self.assertEqual(len(saved),1)
        with patch("tournament.run_match",return_value={"p1Score":900,"p2Score":1000}) as runner:
            result=run_seeded_tournament(players,completed_games=saved)
        self.assertEqual(runner.call_count,1)
        self.assertEqual(result["champion"]["username"],"alpha")


class CompetitionStoreTests(unittest.TestCase):
    def test_single_version_and_finalized_roster_are_frozen(self):
        with tempfile.TemporaryDirectory() as root:
            store=PlatformStore(Path(root)/"competition.db")
            storage=LocalObjectStorage(Path(root)/"objects")
            store.configure_competition(qualifier_count=3,registration_capacity=10,
                official_attempt_limit=1,reference_count=5,tie_replay_limit=2)
            from backend.services.storage import CompetitionState
            with store.session() as db:
                state=db.get(CompetitionState,1)
                state.phase="QUALIFICATION_OPEN"
                state.started_at=utc_now()-timedelta(minutes=1)
            with patch("backend.services.blob_storage.objects",storage):
                for team,scores in (("alpha",(900,)),("beta",(700,))):
                    for version,score in enumerate(scores,1):
                        key=f"submissions/{team}/{version}.py"
                        storage.put_bytes(key,f"def agent(obs): return {{}} # {team} {version}".encode())
                        submission=store.create_submission(team,key,valid=True)
                        job=store.create_job(team,"official",submission_id=submission["id"],
                            payload={"submissionSha256":__import__("hashlib").sha256(storage.get_bytes(key)).hexdigest()})
                        store.mark_job_running(job["id"],"test")
                        self.assertTrue(store.commit_job_result(job["id"],{
                            "status":"complete","rating":score,"winRate":50,
                            "averageMoneyDifferential":100,"averageFinalMoney":3000,"games":20}))
                self.assertEqual(store.qualification_leaderboard()[0]["version"],1)
                store.close_qualification()
                with self.assertRaises(ValueError):store.finalize_qualification()
                store.configure_competition(qualifier_count=2,registration_capacity=10,
                    official_attempt_limit=1,reference_count=5,tie_replay_limit=2)
                finalized=store.finalize_qualification()
                self.assertEqual([row["team"] for row in finalized["qualifiers"]],["alpha","beta"])
                self.assertEqual(finalized["qualifiers"][0]["version"],1)
                self.assertEqual(store.qualification_leaderboard()[0]["rating"],900)
                reopened=PlatformStore(Path(root)/"competition.db")
                self.assertEqual(reopened.competition()["qualifiers"][0]["submissionId"],
                                 finalized["qualifiers"][0]["submissionId"])
                with self.assertRaises(ValueError):
                    store.configure_competition(qualifier_count=3,registration_capacity=10,
                        official_attempt_limit=1,reference_count=5,tie_replay_limit=2)

    def test_reference_snapshot_survives_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            store = PlatformStore(Path(root) / "competition.db")
            storage = LocalObjectStorage(Path(root) / "objects")
            with patch("backend.services.blob_storage.objects", storage):
                bots=[]
                for index in range(5):
                    row=store.add_reference_bot(f"def agent(obs): return {{'farmer':['PASS'],'hands':[],'market':[]}} # {index}".encode(),f"Bot {index}")
                    store.set_reference_test(row["id"],True)
                    store.set_reference_bot(row["id"],selected=True)
                    bots.append(row)
                config={"seeds":[3,7],"sides":[0,1],"weights":{"win_rate":.65,"economic":.35},
                        "economic_scale":10000,"rating_scale":1000}
                first=store.start_qualification(config)
                self.assertEqual(len(first["referencePool"]),5)
                self.assertEqual(len(first["evaluationConfig"]["opponents"])*4,20)
                replacement=store.add_reference_bot(b"def agent(obs): return {'farmer':['PASS'],'hands':[],'market':[]} # new",
                    "Bot 0",family_id=bots[0]["familyId"])
                frozen=store.competition()["referencePool"]
                self.assertEqual(frozen[0]["id"],bots[0]["id"])
                self.assertNotEqual(frozen[0]["id"],replacement["id"])

    def test_cutoff_edit_lock(self):
        with tempfile.TemporaryDirectory() as root:
            store = PlatformStore(Path(root) / "competition.db")
            store.configure_competition(qualifier_count=12, registration_capacity=60,
                official_attempt_limit=1, reference_count=5, tie_replay_limit=2)
            self.assertEqual(store.competition()["settings"]["qualifierCount"], 12)
            with store.session() as db:
                from backend.services.storage import CompetitionState
                db.get(CompetitionState,1).phase="QUALIFICATION_OPEN"
            store.configure_competition(qualifier_count=10, registration_capacity=60,
                official_attempt_limit=1, reference_count=5, tie_replay_limit=2)
            with self.assertRaises(ValueError):
                store.configure_competition(qualifier_count=10, registration_capacity=61,
                    official_attempt_limit=1, reference_count=5, tie_replay_limit=2)
            store.transition_competition("QUALIFICATION_OPEN", "QUALIFICATION_FINALIZED")
            with self.assertRaises(ValueError):
                store.configure_competition(qualifier_count=8, registration_capacity=60,
                    official_attempt_limit=1, reference_count=5, tie_replay_limit=2)


if __name__ == "__main__":
    unittest.main()
