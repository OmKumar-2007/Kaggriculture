# FarmCraft portable evaluator

This directory is the controller for a separate Windows 11 or Ubuntu evaluation laptop. It uses only outbound HTTPS to the FarmCraft API. Contestant Python runs in disposable Docker containers; the controller itself never imports contestant source.

## Windows 11

Install Python 3.11, Docker Desktop with WSL2, and Git. Start Docker Desktop. In the repository root run:

```powershell
.\farmcraft-evaluator\scripts\setup-windows.ps1
.\farmcraft-evaluator\scripts\start-worker.ps1
```

Setup asks for the public API URL, laptop name, and the single-use token from **Admin → Workers & Devices → Add Worker**. It creates an isolated venv, builds the pinned evaluator image, checks resources and cloud version, runs a real sample Docker match, then registers the laptop. The credential is saved only in ignored `farmcraft-evaluator/credentials.json`, with a restrictive Windows ACL. Keep that file out of backups shared with contestants.

## Ubuntu

Install Python 3.11 plus `python3.11-venv`, Docker Engine, and Git. Start Docker and give the organizer user access to its daemon. Docker access is effectively host administrator access; use a dedicated organizer account and laptop.

```bash
chmod +x farmcraft-evaluator/scripts/*.sh
./farmcraft-evaluator/scripts/setup-linux.sh
./farmcraft-evaluator/scripts/start-worker.sh
```

Setup writes credentials with mode `0600`. Neither setup script silently installs Docker, WSL, Python, or changes system security settings.

## Operation

- Change `WORKER_CONCURRENCY` in ignored `.env`, restart the controller, and set the matching maximum in the admin panel. Default is **2**, pending a benchmark of the actual laptop.
- On the actual laptop, run `.venv/Scripts/python.exe scripts/benchmark.py --levels 1,2,4,6,8 --games 8` (Ubuntu: `.venv/bin/python`) from this directory while the event is closed. It records real Docker runtimes, throughput, CPU, RAM, and failures in ignored `benchmark.json`. Pick the best stable concurrency; more workers can reduce throughput.
- Pause stops new claims; drain also stops new claims and lets active matches finish. Admin cancellation marks a job cancelled in PostgreSQL; the next worker heartbeat stops its Docker container. Heartbeat defaults to 15 seconds.
- Stop with `stop-worker.ps1` or `stop-worker.sh`. The stop file causes active containers to terminate and unfinished jobs to be recovered by the lease policy.
- For optional reboot startup, run `scripts/install-autostart-windows.ps1` or `scripts/install-autostart-linux.sh` **after** setup. The scripts create a user Task Scheduler task or systemd user service; setup never enables these automatically. Start Docker before the worker. Do not put credentials in the task or service definition.
- To migrate, revoke Laptop A in Admin, clone the repository on Laptop B, run setup with a fresh token and a new name, then start B. Queued jobs remain in Neon. Expired official/sandbox attempts retry within the configured budget; an interrupted tournament stops for organizer review.
- To rotate a credential, stop that laptop's controller, select **rotate** in Admin, and enter the displayed `workerId.credential` into `.venv/Scripts/python.exe app/worker.py --update-credential` on Windows (or `.venv/bin/python app/worker.py --update-credential` on Ubuntu) from this directory. The new credential is stored with restricted permissions. Restart the controller. If the laptop is lost, revoke it and use a new one-use registration token instead.
- Updating code or `config/evaluation.json` requires updating the `VERSION` file and Render's `FARMCRAFT_EVALUATOR_VERSION`, redeploying the API, rebuilding the image on the worker, and registering or restarting the worker. The doctor checks the actual configuration hash.

**Security limit:** Docker resource limits, no network, non-root user, read-only root filesystem, no Docker socket mount, and cleanup reduce risk, but a personal laptop's kernel and Docker daemon are still security boundaries. Run this on a dedicated, updated organizer machine. Worker credentials can submit results for assigned jobs and must be revoked if lost.
