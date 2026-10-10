from backend.services.storage import PlatformStore


def test_sandbox_replay_has_an_owner(tmp_path):
    store = PlatformStore(tmp_path / "replay_access.db")
    store.register_team("TeamAlpha")

    submission = store.create_submission(
        "TeamAlpha",
        "submissions/alpha/agent.py",
        valid=True,
    )

    replay_id = "a" * 32

    store.record_sandbox(
        submission["id"],
        {
            "opponent": "random",
            "seed": 42,
            "status": "success",
            "winner": "bot",
            "botFinalMoney": 1200,
            "opponentFinalMoney": 800,
            "runtimeSeconds": 1.0,
            "replayId": replay_id,
        },
    )

    assert store.replay_access(replay_id) == {
        "kind": "sandbox",
        "team": "TeamAlpha",
    }

    assert store.replay_access("c" * 32) is None


def test_tournament_replay_is_identifiable(tmp_path):
    store = PlatformStore(tmp_path / "tournament_replay.db")

    replay_id = "b" * 32

    store.record_tournament_game({
        "gameId": "GAME_1",
        "matchId": "R1_M1",
        "round": 1,
        "replay": 0,
        "leg": 0,
        "seed": 42,
        "playerZero": "TeamAlpha",
        "playerOne": "TeamBeta",
        "scoreZero": 1200,
        "scoreOne": 800,
        "replayId": replay_id,
    })

    assert store.replay_access(replay_id) == {
        "kind": "tournament",
    }
