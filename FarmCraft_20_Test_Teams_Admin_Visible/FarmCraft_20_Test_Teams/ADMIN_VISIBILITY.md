# See QA test teams in your FarmCraft admin dashboard

The pre-existing `provision_test_teams.py` creates **real participant teams** through `/api/participants/session`, followed by an authenticated bot upload through `/botlab/upload`. Those teams are visible in the **same environment's** admin dashboard:

| Admin section | What changes after provisioning |
| --- | --- |
| Overview | Registered teams increases by up to 20; jobs show only if sandbox mode used |
| Teams & Sessions | 20 `QA26_...` teams with one bot version each; session information and status |
| Submissions & Jobs | Queued, running and finished jobs from `--mode sandbox` |
| Evaluation Pipeline | Worker, queue waiting time, runtime, status and failures for each test job |
| Workers & Devices | Actual worker registrations do not increase by creating contestant accounts; QA sessions appear as devices while online |
| Audit Logs | Participant sign-ins/uploads are not automatically organizer actions |

**Important:** The admin **Overview counts exclude special rehearsal-only teams**, but standard QA accounts made via participant sign-in count as real registered teams. This uses 20 of your registration slots. The existing `/api/admin/rehearsal/seed` endpoint creates rehearsal-only teams, but **all use the same starter bot** and they cannot sign in as contestants with the current code. To have 20 distinct bots with real login/session activity in the production dashboard, the normal registration path is required unless the backend is enhanced to support authenticatable rehearsal identities. Do not run this on a live event you cannot safely reset.

## A. Inspect what will be created (no side effects)

```powershell
py -3 provision_test_teams.py
```

## B. Populate your local/staging admin dashboard

Start the backend you wish to test. Use its matching admin page, not a dashboard connected to another database.

```powershell
py -3 provision_test_teams.py --execute --base-url http://127.0.0.1:8000
```

Optional: start up to **4** sandbox jobs, which will appear in the Admin Evaluation Pipeline:

```powershell
py -3 provision_test_teams.py --execute --mode sandbox --max-sandbox-jobs 4
```

This second run reuses the saved sessions and existing uploads, so it does not create 20 more accounts.

To keep the 20 sessions shown as online briefly, in a separate terminal:

```powershell
py -3 keep_teams_online.py --base-url http://127.0.0.1:8000 --execute --duration-seconds 120
```

Now refresh the **matching** admin page and inspect **Teams & Sessions**, **Submissions & Jobs** and **Workers & Devices**.

## C. Populate your LIVE Render admin page (explicitly changes competition data)

Do not run if actual signups/scoring have started, registrations are at capacity or you cannot dedicate 20 slots to QA. These are **real competition accounts**, even though their names start with QA.

```powershell
py -3 provision_test_teams.py --base-url https://neural-coliseum-api.onrender.com --execute --allow-production --acknowledge-competition-slots
```

Only after checking the 20 test registrations/uploads:

```powershell
py -3 provision_test_teams.py --base-url https://neural-coliseum-api.onrender.com --execute --allow-production --acknowledge-competition-slots --mode sandbox --max-sandbox-jobs 4
```

This queues real evaluations and consumes existing Azure worker capacity. Do not run during the live contest. You can initially use `--max-sandbox-jobs 1` to verify one job.

For a 2-minute admin online-presence display:

```powershell
py -3 keep_teams_online.py --base-url https://neural-coliseum-api.onrender.com --execute --allow-production --acknowledge-competition-slots --duration-seconds 120
```

Open your **production** organizer admin page (same production API) and inspect:

- **Overview**: registration count increased up to 20; active sessions increased during the heartbeat script.
- **Teams & Sessions**: find `QA26_` names; expect one bot version for each team.
- **Submissions & Jobs**: after sandbox runs, expect separate `sandbox` job IDs per team.
- **Evaluation Pipeline**: wait for `queued -> running -> completed/failed` and note worker IDs.
- **Workers & Devices**: QA browser sessions are *devices*, NOT additional evaluator workers.

### Safety and cleanup

Do not share `runtime/sessions/*.cookies.txt` or upload them to Git. They contain authenticated sessions. The `.gitignore` excludes `runtime/`. Session presence naturally expires; permanent account and submission cleanup requires an explicit organizer-approved deletion procedure. **Do not reset the production DB or delete records manually.** `--force-upload` uploads a new version, and therefore is not the right way to retry provisioning.

## D. Verify your application's admin implementation

The active repository defines:

- `GET /api/admin/contestants`: lists all teams, including `isRehearsal`, session count and online status.
- `GET /api/admin/metrics`: live contestant count excludes rehearsals.
- `GET /api/admin/pipeline`: returns jobs and queue status.
- `POST /api/admin/rehearsal/seed`: creates 2–100 rehearsal teams, but identical starter bots, not actual contestant sessions.
- `POST /api/admin/rehearsal/queue`: disabled in production; test-only fake simulation.

The QA kit does not alter this application code or require organizer credentials. It exercises the normal team API and those records are then visible to a logged-in admin.
