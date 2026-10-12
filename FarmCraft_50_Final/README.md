# FarmCraft 50-bot load-test package

Generated against the repository's public contestant interface: `agent(obs)` returning `farmer`, `hands`, `market`.

Contents:
- `bots/LOAD50_20261013_001/main.py` through `050/main.py` — 50 concrete source files across 10 strategy families and 5 policy variants each.
- `manifest.json` — SHA256 and policy settings for every bot.
- `generate_50_bots.py` — reproducible generator and syntax/basic shape smoke-check.
- `run_50_live.py` — 50-session upload and synchronized 50-request submission burst, live monitoring, Round 1 replay check, optional Round 2.

## Important

The generator smoke test validates Python syntax and basic `agent(obs)` response shape with a synthetic observation. It does NOT certify every game action or runtime in the real engine; run real sandbox verification before treating these bots as competition-safe.

**LIVE EXECUTION WAS NOT PERFORMED IN THIS PACKAGE CREATION.** The script requires the actual Azure staging Admin credentials, four active workers, `SETUP` phase, `MAINTENANCE` mode, and no existing contestants. It changes staging data and MUST NOT be pointed at production. Its endpoint is pinned to the given staging Azure URL.

`run_50_live.py` uses the live API routes read from the existing repository `azure-primary/run-load30.py` and `frontend/src/Lab.jsx`. The live deployed revision can differ; preflight and inspect errors before retesting. No automated destructive data reset is included.

## Commands (PowerShell)

Unzip to `D:\kaggriculture\Kaggriculture\FarmCraft_50_Final`.

```
cd D:\kaggriculture\Kaggriculture\FarmCraft_50_Final
py -m pip install requests
py generate_50_bots.py
py run_50_live.py
```

Start both evaluator VMs and confirm four fresh idle heartbeats in Admin. Keep public gates closed and competition freshly reset to SETUP.

In an isolated terminal provide the staging Admin password to the process environment using a securely prompted variable (do not put the password in the CLI command or shell history). For example:

```
$secure = Read-Host 'Staging Admin password' -AsSecureString
$bstr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $env:FARMCRAFT_STAGING_ADMIN_PASSWORD=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr); py run_50_live.py --execute --round2 }
finally { Remove-Item Env:\FARMCRAFT_STAGING_ADMIN_PASSWORD -ErrorAction SilentlyContinue; [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
```

Open `https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/admin` while running.

If a run is interrupted, `private-evidence/load50_state.json` records the progress; do NOT run again blindly or create duplicate teams. Review/resume using Admin API.

When complete: independently reconcile standings, tournament champion, and replay scores; capture reports; back up staging; run the **reviewed** staging reset; confirm empty contestants and phase SETUP; then drain workers and deallocate both new VMs. This package NEVER deletes the database, reset state, or starts/stops VMs automatically.
