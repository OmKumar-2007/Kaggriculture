"""Resolve the Python interpreter used to run Harvest Protocol matches.

This module is intentionally tracked because the backend, tournament runner,
and command-line utilities all import it on a clean checkout.
"""

import os
from pathlib import Path
import sys


def get_kaggle_python() -> str:
    """Return an explicit project interpreter or the current Python executable."""
    root = Path(__file__).resolve().parent
    configured = os.environ.get("NEURAL_COLISEUM_PYTHON")
    candidates = (
        Path(configured).expanduser() if configured else None,
        root / "NITW_Farm_AI_Challenge_v2_Web" / ".venv" / "Scripts" / "python.exe",
        root / "NITW_Farm_AI_Challenge_v2_Web" / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    )
    return str(next((path for path in candidates if path and path.is_file()), Path(sys.executable)))
