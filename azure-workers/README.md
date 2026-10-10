# FarmCraft dedicated Azure evaluator VMs

This is the active hybrid compute path. Render remains the website and API. The VM makes outbound HTTPS calls to Render, and the server owns claims, leases, frozen bot hashes, result commits, and tournament state. The VM has a static outbound public IP and an NSG with no inbound Internet allow rule. No PostgreSQL, Redis, or object-storage credentials are placed on the VM. The old full-Azure web deployment under `azure/` is archived.

## Current deployment gate

The live Render services inspected on 10 October 2026 still run an older `my-feature` commit. Their API returns 404 for `/ready` and `/api/remote-workers/version`. `manage.ps1 -Action Provision` and `-Action Register` require these endpoints and matching evaluator version and configuration hash. Update the existing Render services from a pushed, reviewed commit before provisioning. The current local branch has uncommitted changes and has not been deployed there.

No VM was provisioned while writing this guide. `Standard_D2as_v5` is restricted for this student subscription in UAE North; D2s v3 and B2ms what-if previews there returned `SkuNotAvailable`. D2as v4 in Poland Central was also capacity-blocked. A **Standard_D2as_v4 in Korea Central** read-only what-if passed and proposed the five intended resources. That size has 2 vCPUs and 8 GiB RAM, with a 4-vCPU family quota in the region. Capacity may change before deployment; verify it and current student credit again before approval.

## Preview and lifecycle

Use PowerShell in the repository root. The task-specific SSH key is ignored under `config/local-profiles/`; generate one with `ssh-keygen -t ed25519 -f config/local-profiles/azure-worker-admin` if absent. It is only an emergency access key; no SSH port is opened. Azure Run Command provides managed access.

```powershell
.\azure-workers\manage.ps1 -Action Plan -SshPublicKeyPath config/local-profiles/azure-worker-admin.pub
```

`Plan` uses Azure what-if and creates no resources. It can still fail if Azure reports SKU capacity or policy restrictions. Use the approved, pushed commit and actual updated Render API URL for provisioning:

```powershell
.\azure-workers\manage.ps1 -Action Provision -Size <approved-sku> -GitRef <pushed-40-character-commit> -ApiUrl https://<current-api>.onrender.com
```

The script checks the student subscription, resource group, existing VM, SKU restrictions, a pushed branch tip, Render readiness, evaluator version, and configuration hash. It requests an explicit local confirmation before the billable deployment. The VM boots Ubuntu 24.04, installs Docker and Python, checks out that exact commit, builds the evaluator image locally, and leaves the worker service disabled until registration. Cloud-init contains no registration token or credential.

In Render Admin → Workers & Devices, issue a 15-minute single-use worker token. Then run:

```powershell
.\azure-workers\manage.ps1 -Action Register -ApiUrl https://<current-api>.onrender.com
.\azure-workers\manage.ps1 -Action Status
```

Registration passes the token through a managed Azure Run Command protected parameter, stores the returned worker credential on the VM with restrictive file permissions, deletes the managed Run Command resource, and starts the systemd service. The token briefly appears in the organizer machine's Azure CLI process arguments; restrict local account access during registration. Never paste the token in chat, Git, or VM custom data. Revoke the worker from Admin if the credential is compromised.

The worker defaults to one concurrent game. Set server-side capacity in Admin before increasing local concurrency after a real benchmark. It reports CPU, RAM, disk, Docker health, heartbeat, job count, and current job to the existing Admin panel. Names prefixed `farmcraft-eval-` are shown as Azure VMs.

For event shutdown:

```powershell
.\azure-workers\manage.ps1 -Action Drain
.\azure-workers\manage.ps1 -Action Status
.\azure-workers\manage.ps1 -Action Deallocate
```

Drain prevents new claims and allows active matches to finish. Deallocation checks that the worker service is no longer active. The VM's compute charge stops after Azure confirms deallocation; the 32 GiB managed OS disk and static public IP remain chargeable. Restart with `-Action Start`, which clears the drain marker. For permanent teardown, list the VM, disk, NIC, IP, VNet, and NSG and delete only after separate data/credential review; this guide intentionally provides no destructive bulk-delete command.

## Isolation and limits

Each contestant match runs in a Docker container with no network, a read-only root, non-root UID, dropped capabilities, no new privileges, CPU/memory/process limits, a small tmpfs, timeouts, and read-only source mounts. The controller has Docker access, which effectively grants host control; use a dedicated VM and no other sensitive workloads. Container isolation shares the host kernel. The existing worker lease protocol handles a lost or restarted VM, but an interrupted tournament still requires organizer review before progression. The first cloud worker must pass real sandbox, official, cancellation, lease, crash, and Round 2 checks before scaling.

Azure Batch adds a second scheduler and pool lifecycle despite the server's existing durable queue. Container Apps Jobs do not allow privileged host-level containers, so the current Docker-based evaluator cannot run there unchanged. These alternatives can be revisited if a dedicated VM is unavailable under the student subscription. See [Azure Batch jobs](https://learn.microsoft.com/en-us/azure/batch/jobs-and-tasks) and [Container Apps container limitations](https://learn.microsoft.com/en-us/azure/container-apps/containers).
