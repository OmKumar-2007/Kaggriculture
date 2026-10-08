"""The bracket runner must produce a retrievable replay from a real evaluator game."""
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

from backend.services.blob_storage import LocalObjectStorage
from backend.services.analytics import replay_frame
from tournament import run_match


def test_tournament_match_persists_real_replay(tmp_path):
    if not shutil.which("docker") or subprocess.run(
        ["docker", "image", "inspect", "nitw-farm-ai-evaluator"], capture_output=True, timeout=10
    ).returncode:
        pytest.skip("Evaluator image is unavailable")
    root = Path(__file__).resolve().parents[1] / "NITW_Farm_AI_Challenge_v1" / "examples"
    first = {"username": "starter", "filePath": str(root / "starter_agent.py")}
    second = {"username": "random", "filePath": str(root / "random_agent.py")}
    replay_dir = tmp_path / "replays"
    replay_dir.mkdir()
    objects = LocalObjectStorage(tmp_path / "objects")
    with patch.dict("os.environ", {"NEURAL_COLISEUM_TRUSTED_LOCAL": "0"}), \
         patch("backend.services.sandbox.REPLAY_DIR", replay_dir), \
         patch("backend.services.blob_storage.objects", objects):
        result = run_match(first, second, 41021)
    replay_id = result["replayId"]
    assert len(replay_id) == 32
    assert objects.exists(f"replays/{replay_id}.json")
    frame = replay_frame(replay_dir / f"{replay_id}.json", 0)
    assert frame["totalSteps"] > 1
    assert result["winner"] in (0, 1, None)
