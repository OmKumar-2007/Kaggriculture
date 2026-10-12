# FarmCraft — Wave 1 analytics/replay recovery (non-destructive)

**This patch contains just four files. It does not contain or replace your `runtime/` folder, cookies, bots, `teams.csv`, database dumps, or other test artifacts.**

## What changed

- `FarmCraft_50_Full_Rehearsal/rehearsal.py`:
  - fixes the `sum(int, NoneType)` crash by converting pending `analytics.ok` to `bool`.
  - evaluates existing replays using an authorized organizer session (the backend explicitly allows admin replay access), instead of requiring each original participant session cookie.
  - retries transient HTTP 500/502/503/504 on **GET only**, never on POST.
  - continues to skip already verified analytics and checks all 50 before proceeding.
  - raises a clear error listing still-failing teams if any replay endpoint remains broken.
- `Resume-FarmCraft-Sandboxes.ps1`: before wave 2, calls a session verifier/repair tool.
- `FarmCraft_50_Full_Rehearsal/restore_missing_qa_sessions.py`: checks each saved participant session; only when it's definitely missing/HTTP 401 or 403 can it issue an admin recovery and save a new session. Requires the typed approval `RECOVER QA SESSIONS ONLY` before doing any recovery writes. This invalidates older sessions *for the selected QA team*, per backend behavior. It never registers another team or submits a bot/job. Recovery codes are never written to disk; cookies still reside in your local `runtime/sessions/` folder. It stops on ambiguous HTTP responses or identity mismatches.
- `FarmCraft_50_Full_Rehearsal/tests_readonly_recovery.py`: offline HTTP 500 retry, organizer replay access, partial analytics regression tests.

## Apply

Exit your existing launcher (`0`), then from the **FarmCraft repository root**:

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\FarmCraft_Replay_Analytics_Recovery.zip" -DestinationPath . -Force
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-50-Team-Test.ps1
```

Choose **7 — Resume sandboxes**. This runs **read-only** wave-1 monitoring and replay analytics. It will not start wave 2 unless all 50 replay checks succeed, and it separately requires typing `START WAVE 2` to approve the new wave of evaluations.

Immediately before the wave-2 POSTs, it verifies all 50 original participant sessions. For each actually missing/expired QA session, it requires additional explicit confirmation to issue an organizer recovery, preserving the team, bot, submission ID, and previous game results. This changes only affected QA sessions. The 50 wave-2 POSTs begin only after all original sessions are valid.

## If HTTP 500/502 persists

Stop. The issue is in the live replay API/server/hosting environment, not merely this script. Inspect Render API logs around the UTC failure time (especially out-of-memory events, exceptions loading replay JSON, storage object retrieval and `/replays/...` timeouts). Do not submit duplicate sandbox jobs.

No client-side patch can guarantee replay endpoints will work if their server keeps failing. 50/50 completed jobs is an evaluation success metric, not a replay/UI success metric. Browser 10x playback must still be verified separately.
