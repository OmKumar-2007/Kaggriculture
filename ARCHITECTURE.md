# Neural Coliseum Architecture

This document records the repository layout before the contestant platform is
expanded. It distinguishes the active tournament path from reusable legacy
components so later phases can be implemented without breaking the game.

## Implementation order

1. Stabilize startup, interpreter discovery, Docker evaluation, and one-match execution.
2. Add a beginner starter bot, strategy guide, and shared validation service.
3. Add sandbox opponents, structured results, and clear error reporting.
4. Add the Bot Lab workflow and persistent submission history.
5. Add optional replay capture, reliable analytics, and lightweight charts.
6. Add configurable hidden multi-seed, multi-opponent, side-swapped evaluation.
7. Connect leaderboard qualification to the existing live knockout tournament.

All seven phases are now connected. Sandbox and official evaluation use isolated
Docker execution by default. `NEURAL_COLISEUM_TRUSTED_LOCAL=1` enables the local
subprocess runner only for trusted development.

## Active live tournament path

```text
frontend/src/App.jsx
    -> HTTP requests to http://127.0.0.1:8000
backend/main.py
    -> stores one canonical players/<username>/agent.py
    -> starts tournament.py in a background task
tournament.py
    -> pairs players, handles BYEs and tie replays
    -> starts run_match.py as a local subprocess
run_match.py
    -> kaggle_environments.make(<upstream engine identifier>)
    -> env.run([agent_a, agent_b])
    -> emits one JSON result
```

The backend progress callback turns tournament events into the state polled by
the React interface. The root path currently executes contestant code locally
and is suitable only for trusted development.

## Contestant execution path

The canonical contestant artifact is `agent.py`. Bot Lab validates source,
stores immutable versions in `submissions/<team>/vN/agent.py`, records metadata
in SQLite, and copies the evaluated active version to
`players/<username>/agent.py` for tournament compatibility.

Provided starter infrastructure will parse observations, scan farms, format
actions, discover basic jobs, and provide movement and market helpers. Strategy
hooks and deliberately untuned parameters remain contestant-owned.

## Sandbox execution path

`backend/services/sandbox.py` runs configurable public seeds against modest
public opponents. It captures development replays under `data/replays/` and
derives analytics through `backend/services/analytics.py`. Official and live
tournament matches do not serialize replays.

## Official evaluation path

The active official evaluator is:

```text
config/evaluation.json
backend/services/evaluation.py
backend/services/scoring.py
backend/private_benchmarks/
NITW_Farm_AI_Challenge_v1/docker/sandbox_worker.py
```

It evaluates multiple private baselines and seeds from both player positions.
Only aggregate rating, win rate, average money, game count, and submission
version are exposed by `/leaderboard`. Private seeds and baseline code are not
returned by the API.

The older reusable isolated evaluator lives in:

```text
NITW_Farm_AI_Challenge_v1/
    competition/engine.py
    competition/validator.py
    docker/worker.py
    Dockerfile
```

It already supplies no-network execution, a read-only filesystem, CPU, memory,
process, and timeout limits. Its Docker image defines
`ENTRYPOINT ["python", "/app/worker.py"]`; host invocations must pass only worker
arguments. The duplicated `/app/worker.py` argument was removed in Phase 1.

The duplicate under `NITW_Farm_AI_Challenge_v2_Web/NITW_Farm_AI_Challenge_v1`
contains the same evaluator and a separate Jinja/FastAPI upload site. Its Docker
invocation was already corrected. It remains legacy reference code rather than
the active React application.

## Live tournament path

`tournament.py` owns random pairing, one random BYE for odd rounds, deterministic
seeded test mode, tie replay seeds, progression, and champion selection. Finals
aggregate an A-vs-B and B-vs-A series. A single contestant error is a recorded
loss; ambiguous or infrastructure errors stop the match for organizer review.
Leaderboard qualifiers can be loaded without deleting non-qualifying bots.

## Frontend and backend interaction

The active Vite application is `frontend/`. It currently calls:

- `GET /players`
- `POST /register`
- `POST /players/clear`
- `POST /demo/populate-sample-players`
- `POST /start-tournament`
- `GET /tournament/status`
- `POST /tournament/reset`

The Neural Coliseum interface includes Bot Lab, Strategy Path, Sandbox,
Analytics and replay, Submissions, Leaderboard, Tournament, and Guide views
alongside the preserved live bracket. `frontend/src/strategyMissions.js` holds
the branching curriculum and copyable prompt missions. Capability badges use
conservative syntax structure checks plus recorded match behavior; diagnostic
findings come only from replay telemetry.

## Deployment

`render.yaml` describes the public React static site and FastAPI web service.
The frontend receives `VITE_API_BASE` at build time. Render's free filesystem is
ephemeral, so event deployments that need durable submissions, SQLite state,
and replays must attach persistent storage or migrate the storage service to a
managed database. Secure contestant execution still requires the isolated
Docker evaluator; the public web service does not enable trusted local execution.

## Component status

### Active

- `backend/main.py`: current FastAPI application and tournament state bridge.
- `frontend/`: current React/Vite interface.
- `players/`: active registered agents.
- `tournament.py`: active knockout coordinator.
- `run_match.py`: active trusted local match runner.
- `py_env.py`: required interpreter resolver; now tracked.

### Legacy but reusable

- `NITW_Farm_AI_Challenge_v1/competition/validator.py`: validation concepts.
- `NITW_Farm_AI_Challenge_v1/competition/engine.py`: Docker isolation design.
- `NITW_Farm_AI_Challenge_v1/docker/worker.py` and `Dockerfile`: isolated worker.
- `NITW_Farm_AI_Challenge_v1/examples/`: baseline opponent candidates.
- `NITW_Farm_AI_Challenge_v2_Web/...`: corrected copy and historical web flow.

### Duplicate or stale

- `tournament.js` and `test_1v1.js`: alternate JavaScript experiments, not used by the active backend.
- Vite starter assets (`react.svg`, `vite.svg`) and earlier generated visual variants are unused by the active build.
- The two nested challenge directories substantially duplicate evaluator and web code.

No duplicate or legacy component is removed yet. Removal should happen only
after the replacement contestant platform is working and references are checked.

## Phase 1 verification targets

- A clean checkout contains `py_env.py`.
- The Docker worker receives each argument once.
- `run_match.py` completes a real two-agent match and emits valid JSON.
- Existing tournament BYE and tie behavior remains available.
- FastAPI and the Vite frontend still start successfully.
