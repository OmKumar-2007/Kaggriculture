import json
from pathlib import Path

from backend.services import analytics


def test_playback_bundle_reads_once_and_supports_both_players(monkeypatch):
    def farm(x, money):
        return {
            "money": money,
            "tiles": [[None, "LOCKED"]],
            "farmer": [x, 0],
            "hands": [],
            "unlocked_quadrants": ["NW"],
        }

    farms = [farm(0, 100), farm(1, 200)]

    def state(actor, hour):
        return {
            "observation": {
                "day": 0,
                "hour": hour,
                "farms": farms,
                "market": {"prices": {"WHEAT": 25}},
                "private": {"secret": "DO_NOT_EXPOSE"},
            },
            "action": {"farmer": ["PASS" if actor == 0 else "EAST"]},
            "reward": 100 + actor,
        }

    replay = {
        "steps": [
            [state(0, 0), state(1, 0)],
            [state(0, 1), state(1, 1)],
        ]
    }

    calls = []

    def fake_load(path):
        calls.append(path)
        return replay

    monkeypatch.setattr(analytics, "load_replay", fake_load)

    bundle = analytics.build_playback_bundle(Path("fixture.json"))

    assert bundle["version"] == 1
    assert bundle["totalSteps"] == 2
    assert len(bundle["players"]) == 2

    assert bundle["players"][0][0]["farm"]["money"] == 100
    assert bundle["players"][1][0]["farm"]["money"] == 200

    assert bundle["players"][0][1]["hour"] == 1
    assert bundle["players"][1][1]["action"]["farmer"] == ["EAST"]

    assert bundle["players"][0][0]["marketPrices"]["WHEAT"] == 25
    assert len(calls) == 1

    assert "DO_NOT_EXPOSE" not in json.dumps(bundle)
