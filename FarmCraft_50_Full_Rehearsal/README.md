# FarmCraft — 50-Team Full Competition Rehearsal

## Important: what is / is not already done

- Included: **50 standalone bots**, 10 real decision-family policies × 5 variants, 50 unique account names, auth/CSRF upload code, sandbox wave submission and polling, authenticated analytics/replay fetches, optional **real Playwright UI checks**, official Round 1 submission and monitoring, Round 2 admin observer, CSV and Markdown reports, and guarded 20-old-QA cleanup.
- **Already tested locally:** 50 Python sources passed static action tests across 2,700 synthetic observations. A *three-team MOCK HTTP* rehearsal passed from registration through official and tournament observer. The mock is not a game benchmark.
- **NOT yet done:** live account creation, cleanup, real 720-turn evaluations, verifying bot win rates, or the production competition. The five reference bot sources remain untouched.
- **Automation is not self-healing**: failures are logged for engineering triage; it will never silently change scoring, reference bots, competition phases or production infrastructure.
- **Do not run during a real contest.** These are 50 real registration records on the target API and 100 genuine sandbox job submissions.
- The protected contestant account is **`temp`**. Its submission is never uploaded or officially submitted by this suite.

## PowerShell installation

Extract `FarmCraft_50_Full_Rehearsal.zip` into `D:\kaggriculture\Kaggriculture`, or another location. Open PowerShell in the extracted folder:

```powershell
cd 'D:\kaggriculture\Kaggriculture\FarmCraft_50_Full_Rehearsal'
py -3 .\validate_agents.py
py -3 -m unittest discover -s tests -v
```

The test kit itself requires Python 3.10+ for the HTTP runner; your Kaggriculture evaluator needs its normal game dependencies. To benchmark using the project's existing Kaggriculture Python environment, pass the path to that interpreter:

```powershell
.\Run-Rehearsal.ps1 -Step benchmark -RepoRoot 'D:\kaggriculture\Kaggriculture' -GamePython 'D:\kaggriculture\Kaggriculture\.venv\Scripts\python.exe'
```

If your game environment uses a different interpreter, replace `-GamePython`. This runs **50 × 2 seeds × 2 player positions = 200 REAL full-length games** against the **public** starter agent. It will take time. By default bots must achieve ≥50% win rate in this seed sample to pass. Fix and re-benchmark failed bots; do not assume they are all strong based on synthetic tests.

To test a few first:

```powershell
py -3 .\benchmark_bots.py --repo-root 'D:\kaggriculture\Kaggriculture' --python 'D:\kaggriculture\Kaggriculture\.venv\Scripts\python.exe' --limit 2
```

**No production writes happen during benchmark.** A full benchmark result for 50 bots, and static validation, are required for live provisioning by default. `-PermitUnbenchmarked` is an explicit opt-out only if you knowingly accept unverified bot quality.

## 0. Preflight and safe old-account cleanup

Before cleanup, run:

```powershell
.\Run-Rehearsal.ps1 -Step preflight
```

Enter the admin password when prompted. This is a **read-only** request to the actual Control Center API. The script refuses provisioning unless it detects team `temp` and at least five existing reference-bot records. Inspect `runtime\preflight.json`; do not proceed if this does not match your intended protected objects.

**Old QA cleanup requires direct Neon PostgreSQL access; the production admin API does not offer scoped deletion of real teams.** This kit does not bypass organizer authentication. Only old `QA26_B2C9C5_01` to `_20` are eligible; `temp`, the five references, and all other identities are protected.

If you have permission to access Neon directly, load `DATABASE_URL` into your PowerShell session using your organization's **secure secrets procedure**, without printing it or placing the credential in shell history. The cleanup tool refuses to run if the variable is unset or points to SQLite. Install the PostgreSQL client and have an independently verified `pg_dump --format=custom` backup before executing destructive changes.

Verify that `$env:DATABASE_URL` points to the intended database, then run:

```powershell
.\Run-Rehearsal.ps1 -Step cleanup-plan
# Read plan, its SHA-256 and every candidate. Do not proceed if any unexpected team appears.
# Use your organization's authorized pg_dump procedure to create and verify a backup first.
.\Run-Rehearsal.ps1 -Step cleanup-execute -PlanSha '<exact-planSha256-from-output>' -BackupFile 'D:\secure-backups\farmcraft-before-cleanup.dump'
```

`cleanup-execute` demands the exact plan hash, a nonempty backup and a typed confirmation. **Only run after personally approving the deletion list**. It refuses deletion when the competition phase is not SETUP, an eligible QA job is active, old QA accounts have official claims/tournament records, `temp` is absent or fewer than five reference bot versions exist.

It cleans PostgreSQL team-related records transactionally; **object-storage blobs for old test submissions/replays are deliberately retained** for separate review to avoid accidental reference/source deletion. You can review orphan keys printed in the cleanup plan later. No automated blanket cloud wipe is performed.

**If you don't have a verified backup and PostgreSQL access, do not run deletion.** Obtain a maintenance window and a database administrator, or have Claude add a separate scoped admin cleanup endpoint with backup, authorization and tests.

After cleanup, rerun preflight to confirm the protected team and five reference bots are unchanged.

## 1. Create all 50 teams and upload bots

Ensure registration is enabled, you have ≥50 free competition slots, and all bots passed real benchmarks.

```powershell
.\Run-Rehearsal.ps1 -Step provision -ApproveLive
```

Saved team cookies and progress live in `runtime\`. **Keep `runtime\` private and never commit it to Git.** If a user name already exists and its session is lost, the script aborts that team rather than hijacking it or attempting a new registration.

Admin: **Overview**, **Teams & Sessions** → see the 50 `FC26_R50_...` teams and their uploads.

To keep 50 QA accounts online while a long run executes, optionally run in **another** PowerShell window (example: 6 hours). The job monitor also sends session heartbeats while polling:

```powershell
.\Run-Rehearsal.ps1 -Step heartbeat -ApproveLive -DurationMinutes 360
```

## 2. First 50 sandbox jobs and 50 analytics/replay checks

```powershell
.\Run-Rehearsal.ps1 -Step sandbox1 -ApproveLive
.\Run-Rehearsal.ps1 -Step wait1
.\Run-Rehearsal.ps1 -Step analytics1
```

Opponents: public `balanced` benchmark in wave 1. Each account uses a distinct seed. Jobs are submitted 1 second apart to avoid saturating Render with a sudden blast.

**Recommended browser check:**

```powershell
py -3 -m pip install playwright
py -3 -m playwright install chromium
.\Run-Rehearsal.ps1 -Step browser1
```

This navigates the actual participant UI with the QA sessions, clicks **analytics**, verifies fixed **10×** replay controls, and tests play/pause, next and seeking for up to 50 teams. A failure is recorded in `runtime\browser_wave_1.json`.

## 3. Second 50 sandbox jobs + analytics

```powershell
.\Run-Rehearsal.ps1 -Step sandbox2 -ApproveLive
.\Run-Rehearsal.ps1 -Step wait2
.\Run-Rehearsal.ps1 -Step analytics2
.\Run-Rehearsal.ps1 -Step browser2
.\Run-Rehearsal.ps1 -Step snapshot
.\Run-Rehearsal.ps1 -Step report
```

Opponent: public `animal` benchmark. The harness will **not** begin wave 2 until all 50 wave-1 server jobs have completed. If one job fails, investigate and re-run only after resolving that failed team or use `reconcile` for ambiguous 502 responses.

Admin visibility: **Submissions & Jobs**, **Evaluation Pipeline**, **Workers & Devices**.

## 4. Pause: YOU start Round 1 from Admin

Open <https://neural-coliseum.onrender.com/admin>. Verify reference selection (original five), qualification settings, and that event uploads/official actions are allowed. **You** start qualification using the actual admin UI.

After Round 1 is visibly open, run:

```powershell
.\Run-Rehearsal.ps1 -Step official -ApproveLive
.\Run-Rehearsal.ps1 -Step waitofficial
.\Run-Rehearsal.ps1 -Step snapshot
.\Run-Rehearsal.ps1 -Step report
```

**Your personal `temp` official attempt is never submitted by this kit.** Submit it yourself from the frontend while Round 1 is open. The simulator submits one official attempt each for its 50 test accounts. This might require 1,000+ genuine Kaggriculture games based on your qualification settings and VM throughput; keep the test phase open long enough.

An intermittent 502 during an official POST may mean the server *accepted* it but the response was lost. The suite marks such attempts **ambiguous** and does not retry. Use `reconcile` to inspect existing job history.

## 5. Pause: YOU finalize qualification and launch Round 2

In the admin page, review scores and failed jobs, close and finalize Round 1, preview and lock the bracket, then start Round 2. Leave actual competition transitions under your control.

Then run:

```powershell
.\Run-Rehearsal.ps1 -Step tournament
.\Run-Rehearsal.ps1 -Step snapshot
.\Run-Rehearsal.ps1 -Step report
```

The read-only tournament watcher polls the real admin API for the entire bracket and final champion. Inspect `runtime\tournament_latest.json`, `runtime\tournament_games.json`, and `reports\REPORT.md`.

## 6. Investigate 502s, interrupted runs and reports

```powershell
.\Run-Rehearsal.ps1 -Step reconcile
.\Run-Rehearsal.ps1 -Step snapshot
.\Run-Rehearsal.ps1 -Step report
```

Check `runtime\events.jsonl`, `runtime\state.json`, `reports\failures.csv`, `reports\jobs.csv`, `reports\teams.csv`. Error records are preserved, not silently erased on success. User-triggered code fixes should be documented in `reports\FIXES.md`. The suite **cannot directly patch/deploy the live FastAPI or Azure worker application**; root-cause corrections need review, code changes, regression tests and a controlled rollout.

## Safety / practical notes

- `-ApproveLive` is required for actual production writes. Read-only preflight/snapshot do not use it.
- Do NOT share `runtime\sessions`, admin password, Neon `DATABASE_URL`, or pg_dump with others.
- This package has no hidden reference-bot access and does not modify `temp`.
- APIs are checked for each replay, but the browser is checked only if you run `browser1` and `browser2` with Playwright.
- Heavy production tests need an approved maintenance/rehearsal window and monitoring. The user-controlled final tournament can take hours.
- A real single-player game benchmark proves only sample performance; no claim of winning the tournament can be made ahead of time.
- Leaving 50 QA accounts in production will occupy 50 registration slots until scoped cleanup. After the rehearsal, **do not automatically delete** the new test teams or results; preserve them for dashboard inspection and separately authorize post-rehearsal cleanup.
