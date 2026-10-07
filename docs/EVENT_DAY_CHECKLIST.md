# Event-day checklist

## Before opening the event

- [ ] Confirm the API is healthy at `/health` and ready at `/ready` (Postgres, Redis, object storage).
- [ ] Confirm the Control Room login works at `/admin` and the admin session cookie is HttpOnly.
- [ ] Check the worker table for the expected worker count, fresh heartbeats, and idle capacity.
- [ ] Upload a known valid bot, run one sandbox match, then check its result and replay/analytics.
- [ ] Submit one official test bot and confirm evaluation progress, completion, and leaderboard update.
- [ ] Verify tournament status, qualifier selection, a short tournament run, and champion state.
- [ ] Check each queue's depth, oldest wait, and paused state; inspect recent failures and audit history.
- [ ] Confirm R2/S3 storage is reachable and bot/replay artifacts can be read back.
- [ ] Take a database backup and verify the restore procedure is known to the on-call organizer.
- [ ] Set the intended event mode and confirm enabled contestant actions in the public UI.
- [ ] Confirm fake simulation is disabled and `APP_ENV=production` on production services.
- [ ] Run rehearsal population/reset before the event if needed; ensure rehearsal data is not on the public leaderboard.

## During the event

- Watch queue depth and oldest wait, worker heartbeat, API p95 latency, job failure rate, and readiness.
- Use Control Room filters to separate contestant failures from infrastructure failures.
- Pause sandbox or official queue if it is consuming capacity needed for active tournament work; running games finish normally.
- Retry only classified infrastructure failures after checking the underlying dependency/worker issue.
- Switch event mode to `MAINTENANCE` if uploads and evaluation must stop while organizers investigate.
- Record major interventions in the audit log and announce the contestant-facing operational status.

## Recovery actions

1. **Queue backlog:** pause lower-priority work, inspect oldest wait and active workers, then resume once capacity recovers.
2. **Worker offline:** verify the worker service and Redis/Postgres connectivity, restore the worker, confirm a fresh heartbeat, then retry eligible infrastructure failures.
3. **Redis unavailable:** use Maintenance mode if requests cannot be queued; restore Redis and verify `/ready` before resuming queues.
4. **Postgres unavailable:** use Maintenance mode; do not accept new submissions until `/ready` reports healthy.
5. **Storage unavailable:** use Maintenance mode for uploads and verify object reads after recovering storage.
6. **Bad bot storm:** leave contestant errors non-retryable, isolate affected teams/jobs, and preserve the queue for valid work.
7. **Tournament issue:** pause sandbox/official queues as needed; inspect persisted tournament status before any reset. Do not reset an active tournament.
