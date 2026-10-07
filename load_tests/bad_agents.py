"""Synthetic agent sources used by isolated-runner verification."""
from pathlib import Path

VALID = (Path(__file__).with_name("agent.py")).read_text(encoding="utf-8")

AGENTS = {
    "syntax_error": "def agent(obs):\n    return {\n",
    "runtime_exception": "def agent(obs):\n    raise RuntimeError('synthetic runtime failure')\n",
    "timeout": "def agent(obs):\n    while True:\n        pass\n",
    "invalid_action": "def agent(obs):\n    return {'farmer': ['TELEPORT'], 'hands': [], 'market': []}\n",
    "very_slow": "def agent(obs):\n    import time\n    time.sleep(0.2)\n    return {'farmer': ['PASS'], 'hands': [], 'market': []}\n",
    "valid": VALID,
}
