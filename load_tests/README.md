# Event load tests

The default host is local. Public production Neural Coliseum hosts are always refused. Other remote targets require `ALLOW_REMOTE_LOAD_TEST=1` and an exact hostname in `LOAD_TEST_STAGING_HOSTS` (or a hostname containing `staging`).

```powershell
$env:APP_ENV="development"
$env:LOAD_TEST_FAKE_SIMULATION="1"
docker compose up -d --build
$env:LOAD_PROFILE="mixed"
locust -f load_tests/locustfile.py --headless -u 100 -r 10 -t 10m --host http://127.0.0.1:8000 --html load-report.html --csv load_tests/results/mixed
```

The two Locust user classes are `ContestantUser` and `SpectatorUser`. Profiles: `spectators`, `contestants`, `sandbox`, `official`, and `mixed`.
Use fake simulation for queue and database stress. Remove that flag and run `python load_tests/benchmark_simulations.py --levels 1,2,4,8 --games 8` separately for real engine capacity. Fake simulation is refused unless `APP_ENV` is local/development/staging/test; it sleeps 2–8 seconds by default.

`agent.py` is the valid Locust upload fixture. `bad_agents.py` includes valid, syntax, runtime, timeout, invalid-action, and slow source variants; run `python load_tests/verify_bad_agents.py` on a local machine with the isolated evaluator Docker image to verify fault containment.

The mixed Locust profile exercises public contestant and spectator routes. It does not log into the organizer UI or generate 100 concurrent official submissions; use the authenticated Control Room separately for operational checks.
