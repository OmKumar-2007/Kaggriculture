#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Start','Status','Stop')]
    [string]$Action = 'Status',
    [string]$ExpectedSubscriptionName = 'Azure for Students'
)

$ErrorActionPreference = 'Stop'
$rg = 'rg-farmcraft-evaluators-20261012'
$vms = @('farmcraft-eval-02', 'farmcraft-eval-03')
$base = 'https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
$expectedVersion = '2026.10.12'
$expectedHash = 'dd37e57c78ef19d8ae0b60a3dbd3aa038a2892d919dbc57238a126a678f684c1'

function Invoke-AzureCli {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)
    & az.cmd @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed (exit $LASTEXITCODE): az $($Arguments -join ' ')"
    }
}

function Assert-Account {
    $subscription = (& az.cmd account show --query name -o tsv).Trim()
    if ($LASTEXITCODE -ne 0 -or $subscription -ne $ExpectedSubscriptionName) {
        throw "Expected Azure subscription '$ExpectedSubscriptionName'; got '$subscription'. Check az account show."
    }
    foreach ($vm in $vms) {
        $id = & az.cmd vm show -g $rg -n $vm --query id -o tsv
        if ($LASTEXITCODE -ne 0 -or -not $id) {
            throw "Expected VM $vm not found in resource group $rg."
        }
    }
    Write-Host "Confirmed subscription: $subscription" -ForegroundColor Green
}

function Show-PowerState {
    foreach ($vm in $vms) {
        $state = & az.cmd vm get-instance-view -g $rg -n $vm --query "instanceView.statuses[?starts_with(code,'PowerState/')].displayStatus | [0]" -o tsv
        if ($LASTEXITCODE -ne 0) { throw "Cannot retrieve power state for $vm" }
        Write-Host "$vm : $state"
    }
}

function Assert-Api {
    $ready = Invoke-RestMethod -Uri "$base/ready" -TimeoutSec 30
    $version = Invoke-RestMethod -Uri "$base/api/remote-workers/version" -TimeoutSec 30
    if ($ready.status -ne 'ready') { throw 'Staging API is not ready.' }
    if ($version.evaluatorVersion -ne $expectedVersion) {
        throw "Evaluator version mismatch: $($version.evaluatorVersion)"
    }
    $hash = $version.evaluationConfigSha256
    if (-not $hash) { $hash = $version.configSha256 }
    if ($hash -ne $expectedHash) { throw "Config hash mismatch/absent: $hash" }
    Write-Host "Staging API ready; evaluator version/hash verified." -ForegroundColor Green
}

try {
    if (-not (Get-Command az.cmd -ErrorAction SilentlyContinue)) {
        throw 'Azure CLI az.cmd not found. Install Azure CLI or reopen PowerShell after installation.'
    }
    Assert-Account
    switch ($Action) {
        'Start' {
            foreach ($vm in $vms) {
                Write-Host "Starting $vm ..." -ForegroundColor Cyan
                Invoke-AzureCli -Arguments @('vm','start','-g',$rg,'-n',$vm,'--output','none')
            }
            Show-PowerState
            Assert-Api
            foreach ($vm in $vms) {
                Write-Host "Checking systemd worker slots on $vm ..." -ForegroundColor Cyan
                $check = 'systemctl is-enabled farmcraft-staging-worker@01.service farmcraft-staging-worker@02.service; systemctl is-active farmcraft-staging-worker@01.service farmcraft-staging-worker@02.service'
                Invoke-AzureCli -Arguments @('vm','run-command','invoke','-g',$rg,'-n',$vm,'--command-id','RunShellScript','--scripts',$check,'--query','value[0].message','-o','tsv')
            }
            Write-Host 'VMs started. Confirm FOUR FRESH worker heartbeats and 4 idle slots in Admin before running tests.' -ForegroundColor Yellow
            Write-Host "$base/admin"
        }
        'Status' {
            Show-PowerState
            try { Assert-Api } catch { Write-Warning $_.Exception.Message }
            Write-Host "Admin: $base/admin"
        }
        'Stop' {
            Write-Host 'In Admin: disable submissions, drain all four workers, and verify no queued/running jobs.' -ForegroundColor Yellow
            $answer = Read-Host 'Type DRAINED after verifying ZERO queued/running jobs'
            if ($answer -cne 'DRAINED') { throw 'Deallocation cancelled.' }
            foreach ($vm in $vms) {
                Write-Host "Deallocating $vm ..." -ForegroundColor Cyan
                Invoke-AzureCli -Arguments @('vm','deallocate','-g',$rg,'-n',$vm,'--output','none')
            }
            Show-PowerState
            Write-Host 'Compute deallocated. Disks/static public IPs may still incur charges.' -ForegroundColor Green
        }
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
