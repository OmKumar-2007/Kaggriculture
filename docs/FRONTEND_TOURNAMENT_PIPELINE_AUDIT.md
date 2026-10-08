# FarmCraft frontend, tournament and evaluation audit

8 October 2026. This report covers the local laptop deployment and an isolated rehearsal stack on port 18000. It records implemented changes and observed behavior, not a proposed design.

## A. Frontend review and changes

The participant experience uses a voxel farm visual theme while keeping the controls and results readable. The landing page, sign-in, Bot Lab, strategy path, sandbox, analytics, submission history, leaderboard, tournament section, guide, and admin views were inspected in the browser. Viewport checks at 390, 768, 1024, 1366 and 1920 pixels showed no page-level horizontal overflow. The admin job table scrolls within its own container on small screens.

The tournament entry area now shows the authenticated team, current bot version, official evaluation status and rating, with direct links to Bot Lab, submission history and leaderboard. Duplicate roster registration shows a clear rejection and does not create another bot version. Bot Lab and tournament uploads reject empty files, invalid names and files over 256 KB before submission; the API enforces the same limits. Submission history keeps the official score visible on a narrow screen. Failure and cancellation wording distinguishes contestant code errors from organizer stops.

The replay viewer uses actual recorded frames. Playback waits for the current frame request, scales interval by speed, cancels stale frame requests on seek or replay change, shows score and turn count, and pauses while seeking. Match history and live tournament rows link to persisted replay IDs. These controls change presentation only; they do not alter match outcomes. Existing image assets and lightweight CSS transitions retain the farming arena theme. Reduced-motion rules are in the frontend stylesheet.

## B. Tournament audit

The existing tournament is a **head-to-head single-elimination bracket**. `tournament.py` selects a random bye when a round has an odd number of players, shuffles remaining players, pairs adjacent contestants, and advances winners. The worker invokes it with pairing RNG seed `42` and game seed `20260929` (`backend/jobs.py`). Ordinary rounds run one 720-turn game per pair. The final runs two games with sides swapped and sums each team's money. Ties replay with incremented seeds up to the configured tie limit. If all ten replays remain exact ties, the bracket's seeded RNG selects a winner; the match records `tieBreak: seeded_lot`, and participant/admin results label the decision. This gives a reproducible and disclosed resolution rather than leaving the bracket stuck. The official leaderboard is a separate benchmark path; tournament wins do not overwrite its rating.

The audit found that an aborted tournament could return an error object that the queue worker then marked **completed**. The worker now treats that object as a failure. A progress callback persistence failure also used to be swallowed; it now stops the tournament so the saved bracket cannot silently diverge from execution. Match callbacks and public status omit host source paths. Docker-backed tournament matches persist replay data in shared object storage, and the match history records the relevant replay IDs. A live check on 8 October found an earlier two-team bracket already in `error` after ten tied replays; its historical state was retained for organizer review. The new tie rule applies to newly started brackets.

Tests cover deterministic pairings, byes, tie replays, side-to-team reward mapping, final side swaps, error propagation, and a real Docker match with a retrievable replay. Scoring formulas and bracket format were preserved. A remaining fairness property should be understood before an event: **ordinary rounds use one side assignment**, so any first-player advantage can affect elimination even though the final swaps sides. Changing those rounds to two legs would change the tournament format and running time; this audit did not silently make that change.

## C. Actual `main.py` execution path

1. `frontend/src/Lab.jsx` and `frontend/src/App.jsx` validate the selected Python file and send it with the authenticated team session (`frontend/src/participantApi.js`).
2. `backend/main.py` checks the team, CSRF and event policy, validates the name, size, UTF-8 and source, stores a UUID-keyed object, and creates a versioned submission row. Registration and Bot Lab share the same team identity. An already registered team is rejected before creating a new version; a roster admission race discards the unused version and object.
3. `/botlab/{team}/sandbox`, `/botlab/{team}/submit` or `/register` creates a persistent job in `backend/services/storage.py`, then dispatches it through `backend/services/queueing.py`. The job ID remains the correlation key for timeline events.
4. `backend/worker.py` claims jobs, records its identity and heartbeat, and calls `backend/jobs.py`. The current submission's stored source is loaded for that job. A running job has atomic status transitions; cancelled jobs cannot commit a late result.
5. `backend/services/sandbox.py` launches a restricted Docker evaluator with no network, bounded CPU, RAM, process count, a read-only root and a wall-clock deadline. `run_match.py` imports the project environment, calls `kaggle_environments.make(...)`, passes wrapped Python agent functions to `env.run(...)`, extracts final rewards and writes a replay. The API process never imports or runs contestant code.
6. `backend/services/evaluation.py` performs the official eight-game plan: two private baselines, two fixed seeds and both player sides, then aggregates via `backend/services/scoring.py`. The contestant score is mapped back from the actual side on every game.
7. `backend/services/storage.py` commits the job result, evaluation row and active submission score in one transaction. The leaderboard reads these committed scores. `backend/main.py` exposes job progress and replay frames for participant polling.

Source syntax errors are reported at upload. Runtime contestant failures have a distinct category, fail the official job and leave the previous rating intact. Missing baselines, Docker failures, timeouts and storage failures are operational errors rather than fabricated zero scores. Organizer cancellation stops the specific evaluator container, records a terminal cancellation event and prevents late leaderboard writes.

## D. Admin visibility and controls

**Evaluation Pipeline** shows real counts, queue and runtime averages, recent errors, a timestamp-derived received/finished trend, filters, search, sorting, current stage and worker. Opening a job shows its recorded pipeline events, time, result, error kind and message. Available controls call backend endpoints to cancel a queued/running job, retry eligible infrastructure failures, re-evaluate a submission, download sanitized logs, and open a replay. It does not show invented sub-stages for actions the evaluator cannot observe independently.

**Tournament & Matches** shows the bracket's planned, running and completed rows, seeds, participants, rewards/winner and replay links. Its stop action uses the same underlying job cancellation path. Overview highlights online teams, workers, queue, host status and recent organizer actions. Teams & Sessions exposes session state and participant controls. Worker/device and system views are backed by stored heartbeats and host telemetry; the UI cannot measure contestant device CPU or RAM.

## E. Validation and limits

Automated tests and isolated end-to-end results are recorded in `VALIDATION_REPORT.md`. Browser visual checks used real rendered pages at the requested breakpoints. The isolated flow includes successful and invalid uploads, real Kaggle matches, an eight-game official score, a contestant runtime failure, cancellation of an infinite-loop bot, leaderboard preservation and evaluator cleanup.

The local laptop's 100-user fake load exercise measures HTTP and queue behavior, not 100 simultaneous real matches. A second device on the event LAN was unavailable for this audit. The ordinary-round side limitation above remains a tournament policy decision.

## F. Laptop deployment

See `LOCAL_HOSTING.md` for exact startup, health-check and shutdown commands. Docker Desktop and the pinned Python/Node dependencies in the project are required. The service and worker configuration use the same PostgreSQL, Redis and object storage paths. Database schema additions initialize on start; existing production volumes must be preserved. `start-server.ps1` creates local secrets on first start. No paid service is required.
