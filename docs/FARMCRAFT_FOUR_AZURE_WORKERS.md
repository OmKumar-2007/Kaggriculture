# Start and stop the four FarmCraft Azure evaluators

The staging evaluator cluster has **four worker slots on two existing VMs**:

| Azure VM | Registered workers |
| --- | --- |
| `farmcraft-eval-02` | `farmcraft-kr-01`, `farmcraft-kr-02` |
| `farmcraft-eval-03` | `farmcraft-id-01`, `farmcraft-id-02` |

The VMs are in `rg-farmcraft-evaluators-20261012` under the `Azure for Students` subscription. Use a PowerShell terminal in `D:\kaggriculture\Kaggriculture`. The script starts only these two VMs and checks their systemd services. It does not start the older `farmcraft-eval-01`.

## Start

```powershell
az account show --query "{name:name,id:id,state:state}" -o table
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Manage-FarmCraftWorkers-FIXED.ps1 -Action Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Manage-FarmCraftWorkers-FIXED.ps1 -Action Start
```

In [staging Admin](https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/admin), open **Workers & Devices**. Wait for all four names above to show fresh heartbeats, `idle` status, and one available slot each. A running job temporarily consumes a slot. Confirm [API readiness](https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io/ready) shows database, sessions, and storage ready. The startup script checks evaluator version `2026.10.12` and configuration SHA256 `dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1`.

If fewer than four workers appear, inspect each VM's two systemd services through Azure Run Command or Azure Portal before opening submissions. The services are `farmcraft-staging-worker@01.service` and `farmcraft-staging-worker@02.service` on each VM. Do not create new worker identities to hide an unhealthy slot.

If a registration remains in `draining` or `paused` mode from a prior shutdown, use **Resume** for that exact identity in Admin after confirming the VM is running. Wait for its next heartbeat to show `idle` before enabling submissions.

## Stop after jobs drain

1. In Admin, disable registration, upload, sandbox, official, and tournament gates.
2. Drain the four workers and wait until the queue and running job counts are both zero. Check that the last result and replay are persisted.
3. Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Manage-FarmCraftWorkers-FIXED.ps1 -Action Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Manage-FarmCraftWorkers-FIXED.ps1 -Action Status
```

The stop script asks you to type `DRAINED` and deallocates both VMs. Verify Azure reports `VM deallocated` for each. Compute charges stop on deallocation; managed disks and reserved public IP resources may still incur charges. Keep the VMs on only for the evaluation window.

For this 50-team rehearsal, the four registrations were resumed after deallocation. Their heartbeat status is now `offline`; they are ready to become `idle` on the next VM start without issuing new credentials.
