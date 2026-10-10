"""Prevent Windows idle sleep only while the isolated rehearsal runner is alive."""
from __future__ import annotations

import ctypes
import sys
import time

import psutil

if sys.platform != "win32":
    raise SystemExit("This helper is only needed on Windows.")

runner = psutil.Process(int(sys.argv[1]))
created = runner.create_time()
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
set_state = ctypes.windll.kernel32.SetThreadExecutionState
if not set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
    raise SystemExit("Windows refused the temporary wake request.")
try:
    while runner.is_running() and runner.create_time() == created:
        time.sleep(30)
except psutil.NoSuchProcess:
    pass
finally:
    set_state(ES_CONTINUOUS)
