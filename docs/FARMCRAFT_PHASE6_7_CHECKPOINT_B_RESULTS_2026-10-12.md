# FarmCraft Phase 6/7 — Checkpoint B staging result

Checkpoint B was separately approved and executed against the isolated Azure staging app on 2026-10-12 (Asia/Calcutta). No Render service, Neon project, existing evaluator VM, production DNS, Git remote, or production competition record was changed.

## Deployment

- Rebuilt `azure/Dockerfile` with the guarded staging fixture route. Local image ID and ACR manifest digest: `sha256:0b4df9ae016dcca47226c3fbd94026eb1b48c307e03e60381eba5e0a8a095c28`.
- Verified image configuration SHA256 `dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1`; it matched the local worker and staging server. The image excluded `config/local-profiles`.
- Deployed only `farmcraft-staging-api` as revision `--0000003` with the staging fixture flag enabled, then disabled the flag as revision `--0000004`. Revision `--0000004` is Healthy, ready, receives 100% traffic, and `/ready` returns 200 with database, sessions, and storage true.
- Authenticated POST to the fixture route returns 404 after flag removal. The fixture code remains in the image but is disabled.

## Real evaluator run

The staging database initially had no jobs, reference bots, or registered workers and was in `SETUP`. The event stayed in `MAINTENANCE` with registration, upload, sandbox, official, and tournament actions closed.

One local Docker-backed worker was registered at concurrency one, used, drained, stopped, and revoked. Three different reference bots were uploaded and each passed a real remote-worker sandbox test. The three references were selected, the staging competition was configured for one seed and both sides, and one validated fixture submission was uploaded through the guarded organizer route. Qualification started with `openAccess=false`; public event controls remained closed.

| Item | Observed result |
| --- | --- |
| Reference tests | 3 completed, passed |
| Fixture | `phase67_fixture_20261012`, submission 1 |
| Official job | `3208bf06-e7b8-4703-93b1-6e6c72839c4c`, completed on its first attempt |
| Job timing | Created 02:15:50, started 02:15:57, completed 02:16:34 IST |
| Games | 6: each of `ref_1`, `ref_2`, `ref_3` played on sides 0 and 1 |
| Outcome | 4 wins, 0 losses, 2 ties; rating 787.6583333333333 |
| Replays | 6 distinct IDs; all six authenticated analytics reads returned HTTP 200 |
| Admin visibility | 4 completed jobs: 3 reference tests and 1 official fixture |
| Worker | Revoked; local process stopped |

The fixture tests the actual PostgreSQL queue, remote worker claim and heartbeat, Docker evaluator, frozen source hashes, six games, replay uploads, result storage, and Admin job visibility. It does not test the public participant registration/upload path because those controls stayed closed as requested.

## Final state and cleanup

Staging remains in `MAINTENANCE`, with all five participant actions false and the public leaderboard hidden. The competition phase is `QUALIFICATION_OPEN` with three frozen references and one seed; changing that phase back to `SETUP` was not part of the approved test and would need a reviewed cleanup. Test references, fixture submission, completed jobs, and replay objects remain in the isolated staging database and private container for inspection. The worker registration setting was originally enabled and was not changed.

The staging worker credential was saved locally with a restricted Windows ACL and is now revoked. An automatic policy check rejected removal of that local credential file, so it remains under ignored `config/local-profiles/`; its value was not printed or committed. The local staging worker profile and logs also remain. No source commit or push was made.

Existing staging PostgreSQL, ACR, Blob, Container Apps, and local Docker resources were used; no new fixed-price Azure service was created. Extra image storage, container execution, Blob operations and network usage may incur usage charges. Actual billed usage for this short run was not yet available from Azure Cost Management. The staging app is ready, and read-only checks of the Render frontend and API both returned HTTP 200.

## Recovery

If a later staging regression appears, restore the previous immutable staging image `sha256:e06ac8f8ad38b9ab470931d45ebce83f2870075850c7c4e82e435bff175d8129` on `farmcraft-staging-api` only, leaving production untouched. Do not reuse the revoked local worker credential; register a new staging-only worker if another test is separately authorized.
