"""Optional real Docker containment test; skipped without the evaluator image."""
import shutil
import subprocess
from unittest.mock import patch

import pytest

from backend.services.sandbox import SandboxError, run_sandbox_source


def test_unbounded_agent_times_out_and_container_is_removed():
    if not shutil.which("docker") or subprocess.run(["docker", "image", "inspect", "nitw-farm-ai-evaluator"],
                                                       capture_output=True, timeout=10).returncode:
        pytest.skip("Evaluator image is unavailable")
    source = "def agent(obs):\n    while True:\n        pass\n"
    with patch("backend.services.sandbox.MATCH_TIMEOUT_SECONDS", 3):
        with pytest.raises(SandboxError, match="exceeded"):
            run_sandbox_source(source, "random", 1)
    remaining = subprocess.run(["docker", "ps", "-a", "--filter", "name=farmcraft-eval-", "--format", "{{.Names}}"],
                               capture_output=True, text=True, timeout=10, check=True)
    assert not remaining.stdout.strip()
