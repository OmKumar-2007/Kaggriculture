# FarmCraft two-round competition

Round 1 evaluates each team's **one** official submission against an organizer-selected, frozen pool of **5 or 10** reference bots. The configured seed list is applied to every reference, from both player positions (20 or 40 games with the default two seeds). The completed official rating determines its preliminary rank. Ratings keep full stored precision; the order is rating, win rate, average money differential, average final money, then case-insensitive team name. That last rule is the published deterministic exact-tie fallback.

Round 2 uses the finalized Round 1 rank as its seed. The organizer chooses any cutoff from 2 through registration capacity, and must lower it before finalization if fewer eligible teams qualify. The bracket expands to the next power of two, assigns BYEs to the highest seeds, and never creates fake teams. Each real pairing plays both sides with the same seed. Final money is summed by team identity. Exact aggregate ties use up to the configured number of new two-leg series; if still tied, the higher qualification seed advances. BYEs require no game. There are exactly `qualifiers - 1` real pairings, plus optional tiebreak legs.

## Organizer sequence

1. Configure **Competition Setup**: registration capacity, numeric Round 2 cutoff, reference count, seed count, and tie replay limit. Every team has exactly one official submission. The cutoff may change until Round 1 finalization; all other competition settings freeze when Round 1 opens.
2. In **Reference Bots**, upload `agent.py` or `main.py`, run its real sandbox test, and select exactly 5 or 10 passing versions. Uploading a replacement creates a new version and does not alter an active qualification snapshot. Source and object keys remain organizer or worker only.
3. Click **Start Round 1**. The app freezes reference IDs, source hashes, evaluator version, seeds, sides and scoring rules. Teams may register, upload multiple versions, and run sandbox tests. One irreversible official submission freezes its version and source hash. A transactional unique claim blocks duplicate and concurrent submissions, including after contestant failure. Infrastructure retry requeues the same frozen job.
4. Click **Close submissions**. Existing official jobs continue. Retry infrastructure failures from the jobs view. During closing, a terminal infrastructure failure may be excluded with an explicit recorded adjudication and reason. Finalization refuses unresolved jobs.
5. Click **Finalize Round 1**. Rankings, selected submission IDs and source hashes are persisted. The leaderboard cannot change after this point. If eligible teams are fewer than the cutoff, lower the cutoff before finalizing; no fake teams or silent truncation are used.
6. Review **Round 2 Bracket**, click **Lock bracket**, then **Start Round 2**. The tournament loads exact frozen submission versions, not each team's latest upload. Each finished leg is persisted immediately. If an infrastructure error stops a pairing, resolve it and use **Resume failed bracket**; completed pairings and individual legs are reused.

## Running locally

Use `start-server.ps1` in the repository root. The script builds the Docker evaluator and starts API, PostgreSQL, Redis, frontend and the host worker. `health-check.ps1` confirms readiness. Existing PostgreSQL and Redis volumes are retained on ordinary restarts. Keep `LOAD_TEST_FAKE_SIMULATION` unset for competition work. The portable evaluator checkout must use the same repository revision as the API; it receives frozen reference source only after an authenticated job claim.

## Capacity and rehearsal

- 60 teams with 5 references, 2 seeds and both sides: **1,200 qualification games**.
- 60 teams with 10 references: **2,400 qualification games**.
- A 16-team Round 2 requires 15 real pairings and at least 30 games.
- A 60-team Round 2 requires 59 real pairings and at least 118 games.

Do a full rehearsal only with a separate PostgreSQL database, Redis namespace and object-storage root. The prior 5-game Docker benchmark on this 8 GB laptop completed in 67.49 seconds with one worker and recorded 96.9% RAM use. A linear estimate for 1,200 games is about 4.5 hours at one worker; actual qualification can differ. Four concurrent workers are unsafe on the measured memory headroom. The full 60-team two-stage run has **not** been executed on this machine. The bracket mathematics and persistence checks are covered by `tests/test_two_round_competition.py`; those tests do not substitute for the real engine rehearsal.
