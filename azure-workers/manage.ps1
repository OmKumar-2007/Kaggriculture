param(
    [ValidateSet('Plan','Provision','Register','AddWorker','Status','Start','Drain','Deallocate','Cost')]
    [string]$Action = 'Status',
    [string]$Name = 'farmcraft-eval-01',
    [string]$Region = 'koreacentral',
    [string]$Size = 'Standard_D2as_v4',
    [string]$ResourceGroup = 'rg-farmcraft-staging',
    [string]$ApiUrl = 'https://farmcraft-free-api.onrender.com',
    [string]$GitRef = '',
    [ValidateRange(2,4)][int]$Slot = 2,
    [string]$SshPublicKeyPath = ''
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $root 'azure/cli.ps1')

function Invoke-Az([string[]]$Arguments) {
    $result = & $AzCommand @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: $($Arguments[0]) $($Arguments[1])" }
    return $result
}
function Assert-Account {
    $account = (Invoke-Az @('account','show','--output','json')) | ConvertFrom-Json
    if ($account.state -ne 'Enabled' -or $account.name -notmatch 'Student') { throw 'Select the enabled Azure for Students subscription first.' }
    $exists = (Invoke-Az @('group','exists','--name',$ResourceGroup,'--output','tsv')).Trim()
    if ($exists -ne 'true') { throw "Resource group $ResourceGroup does not exist." }
    $resources = @(Invoke-Az @('resource','list','--resource-group',$ResourceGroup,'--query','[].{name:name,type:type}','--output','json') | ConvertFrom-Json | Where-Object { $_ })
    $foreign = @($resources | Where-Object { $_.name -notlike "$Name*" })
    if ($foreign.Count) { Write-Warning "$($foreign.Count) other resources exist in $ResourceGroup; this script will not touch them." }
    Write-Host "Subscription: $($account.name) | Group: $ResourceGroup | Region: $Region"
}
function Get-VM {
    $items = Invoke-Az @('vm','list','--resource-group',$ResourceGroup,'--show-details','--output','json') | ConvertFrom-Json
    return ($items | Where-Object { $_.name -eq $Name } | Select-Object -First 1)
}
function Assert-RemoteCompatibility {
    $remote = Invoke-RestMethod -Uri "$ApiUrl/api/remote-workers/version" -TimeoutSec 45
    $localVersion = (Get-Content -LiteralPath (Join-Path $root 'farmcraft-evaluator/VERSION') -Raw).Trim()
    $localHash = (Get-FileHash -LiteralPath (Join-Path $root 'config/evaluation.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($remote.evaluatorVersion -ne $localVersion -or $remote.evaluationConfigSha256 -ne $localHash) {
        throw 'Render evaluator version/configuration differs from this checkout. Deploy matching code before provisioning.'
    }
    if ($remote.evaluatorMode -ne 'LOCAL') { throw 'Render remote worker claim mode is not LOCAL.' }
    $ready = Invoke-RestMethod -Uri "$ApiUrl/ready" -TimeoutSec 45
    if ($ready.status -ne 'ready' -or -not $ready.checks.database -or -not $ready.checks.storage -or -not $ready.checks.redis) {
        throw 'Render API, database, object storage, or Redis is not ready.'
    }
}
function Invoke-Run([string]$Script) {
    $response = Invoke-Az @('vm','run-command','invoke','-g',$ResourceGroup,'-n',$Name,'--command-id','RunShellScript','--scripts',("@$Script"),'--output','json')
    $item = $response | ConvertFrom-Json
    foreach ($message in $item.value) { if ($message.message) { Write-Host $message.message } }
}
if ($Name -notmatch '^farmcraft-eval-[a-z0-9-]{2,35}$') { throw 'Worker VM name must start with farmcraft-eval-.' }
if ($Region -notin @('uaenorth','koreacentral','polandcentral','malaysiawest','indonesiacentral')) { throw 'Region is not in the approved student-region list.' }
Assert-Account

switch ($Action) {
    'Status' {
        $vm = Get-VM
        if (-not $vm) { Write-Host "VM ${Name}: not provisioned"; break }
        Write-Host "VM ${Name}: $($vm.powerState) | $($vm.hardwareProfile.vmSize) | $($vm.location)"
        if ($vm.powerState -match 'deallocated|stopped') { Write-Host 'Guest diagnostics unavailable while VM is stopped.' }
        else { Invoke-Run (Join-Path $PSScriptRoot 'status.sh') }
    }
    'Plan' {
        if (Get-VM) { throw "VM $Name already exists; no duplicate deployment." }
        if (-not $GitRef) { $GitRef = (git -C $root rev-parse HEAD).Trim() }
        if ($GitRef -notmatch '^[a-fA-F0-9]{40}$') { throw 'GitRef must be a pushed 40-character Git commit.' }
        if ($ApiUrl -notmatch '^https://[a-zA-Z0-9.-]+(?::443)?$') { throw 'ApiUrl must be an HTTPS origin without a path.' }
        if (-not $SshPublicKeyPath) { $SshPublicKeyPath = Join-Path $root 'config/local-profiles/azure-worker-admin.pub' }
        if (-not (Test-Path -LiteralPath $SshPublicKeyPath)) { throw "SSH public key missing: $SshPublicKeyPath" }
        $key = (Get-Content -LiteralPath $SshPublicKeyPath -Raw).Trim()
        if ($key -notmatch '^ssh-(ed25519|rsa) [A-Za-z0-9+/=]+') { throw 'Invalid SSH public key.' }
        $cloud = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'cloud-init.yaml') -Raw
        $cloud = $cloud.Replace('__GIT_REF__',$GitRef).Replace('__API_URL__',$ApiUrl).Replace('__WORKER_NAME__',$Name)
        Write-Host "Previewing one $Size VM with Standard HDD, public egress IP and no inbound NSG rules. No secrets in custom data."
        Invoke-Az @('deployment','group','what-if','-g',$ResourceGroup,'-f',(Join-Path $PSScriptRoot 'worker.bicep'),
            '-p',"location=$Region","name=$Name","vmSize=$Size","adminSshPublicKey=$key","cloudInit=$cloud",'--output','table') | Out-Host
        if ($Action -eq 'Plan') { break }
    }
    'Provision' {
        if (Get-VM) { throw "VM $Name already exists; refusing duplicate provisioning." }
        if (-not $GitRef) { throw 'Supply the pushed Git commit with -GitRef. Local uncommitted code cannot boot on Azure.' }
        if ($GitRef -notmatch '^[a-fA-F0-9]{40}$') { throw 'GitRef must be a pushed 40-character Git commit.' }
        if ($ApiUrl -notmatch '^https://[a-zA-Z0-9.-]+(?::443)?$') { throw 'ApiUrl must be an HTTPS origin without a path.' }
        Assert-RemoteCompatibility
        $remoteHeads = @(git -C $root ls-remote --heads origin)
        if ($LASTEXITCODE -ne 0 -or -not @($remoteHeads | Where-Object { $_ -match "^$GitRef\s" }).Count) {
            throw 'GitRef is not a pushed branch tip on origin. Push and deploy the matching Render code first.'
        }
        $sku = @(Invoke-Az @('vm','list-skus','--location',$Region,'--size',$Size,'--all','--output','json') | ConvertFrom-Json |
            Where-Object { $_.name -eq $Size })
        if (-not $sku.Count -or @($sku[0].restrictions).Count) { throw "VM SKU $Size is restricted for this subscription in $Region." }
        if (-not $SshPublicKeyPath) { $SshPublicKeyPath = Join-Path $root 'config/local-profiles/azure-worker-admin.pub' }
        $key = (Get-Content -LiteralPath $SshPublicKeyPath -Raw).Trim()
        $cloud = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'cloud-init.yaml') -Raw).Replace('__GIT_REF__',$GitRef).Replace('__API_URL__',$ApiUrl).Replace('__WORKER_NAME__',$Name)
        if ((Read-Host "This creates billable VM, disk and public IP in $Region. Type PROVISION $Name") -ne "PROVISION $Name") { throw 'Provision cancelled.' }
        Invoke-Az @('deployment','group','create','-g',$ResourceGroup,'-f',(Join-Path $PSScriptRoot 'worker.bicep'),
            '-p',"location=$Region","name=$Name","vmSize=$Size","adminSshPublicKey=$key","cloudInit=$cloud",'--output','none') | Out-Null
        Write-Host 'Provisioned. Wait for cloud-init, then issue a single-use token in Admin -> Workers and run Register.'
    }
    'Register' {
        if (-not (Get-VM)) { throw 'VM is absent.' }
        Assert-RemoteCompatibility
        $secure = Read-Host 'Single-use token from Render Admin -> Workers' -AsSecureString
        $handle = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($handle)
            if (-not $token) { throw 'Token is empty.' }
            $runName = 'farmcraft-register-once'
            try {
                Invoke-Az @('vm','run-command','create','-g',$ResourceGroup,'--vm-name',$Name,'--run-command-name',$runName,
                    '--location',$Region,'--script',('@' + (Join-Path $PSScriptRoot 'register.sh')),
                    '--protected-parameters',("registrationToken=$token"),'--output','none') | Out-Null
            } finally {
                $token = $null
                & $AzCommand vm run-command delete -g $ResourceGroup --vm-name $Name --run-command-name $runName --yes --output none 2>$null
            }
        } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($handle) }
        Write-Host 'Registration command submitted. Check Status and Admin heartbeat.'
    }
    'AddWorker' {
        if (-not (Get-VM)) { throw 'VM is absent.' }
        if ($Slot -ne 2) { throw 'The current VM benchmark supports one additional slot only.' }
        Assert-RemoteCompatibility
        $secure = Read-Host "Single-use token for worker slot $Slot from Render Admin -> Workers" -AsSecureString
        $handle = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($handle)
            if (-not $token) { throw 'Token is empty.' }
            $runName = "farmcraft-register-slot-$Slot"
            try {
                Invoke-Az @('vm','run-command','create','-g',$ResourceGroup,'--vm-name',$Name,
                    '--run-command-name',$runName,'--location',$Region,
                    '--script',('@' + (Join-Path $PSScriptRoot 'register-slot.sh')),
                    '--parameters',("slot=$Slot"),'--protected-parameters',("registrationToken=$token"),
                    '--output','none') | Out-Null
            } finally {
                $token = $null
                & $AzCommand vm run-command delete -g $ResourceGroup --vm-name $Name --run-command-name $runName --yes --output none 2>$null
            }
        } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($handle) }
        Write-Host "Worker slot $Slot registration submitted. Verify both heartbeats in Render Admin."
    }
    'Start' {
        if (-not (Get-VM)) { throw 'VM is absent.' }
        Invoke-Az @('vm','start','-g',$ResourceGroup,'-n',$Name,'--output','none') | Out-Null
        Invoke-Run (Join-Path $PSScriptRoot 'start.sh')
    }
    'Drain' {
        if (-not (Get-VM)) { throw 'VM is absent.' }
        Invoke-Run (Join-Path $PSScriptRoot 'drain.sh')
        Write-Host 'New claims stopped. Wait for current jobs to finish, then deallocate.'
    }
    'Deallocate' {
        $vm = Get-VM
        if (-not $vm) { throw 'VM is absent.' }
        if ($vm.powerState -notmatch 'deallocated|stopped') {
            $check = Invoke-Az @('vm','run-command','invoke','-g',$ResourceGroup,'-n',$Name,'--command-id','RunShellScript',
                '--scripts',('@' + (Join-Path $PSScriptRoot 'deallocate-check.sh')),'--output','json')
            if (($check | Out-String) -notmatch 'SAFE_TO_DEALLOCATE') { throw 'Worker service is still active or status is unknown. Drain and check again.' }
        }
        if ((Read-Host "Type DEALLOCATE $Name after draining active jobs") -ne "DEALLOCATE $Name") { throw 'Deallocation cancelled.' }
        Invoke-Az @('vm','deallocate','-g',$ResourceGroup,'-n',$Name,'--output','none') | Out-Null
        Write-Host 'Compute deallocated. OS disk and static public IP can still accrue charges.'
    }
    'Cost' {
        Write-Host 'Cost approval requires the current Retail Prices API VM, disk and IP rates and Azure student balance.'
        Write-Host 'No Azure resource is created by Cost. See docs/HYBRID_RENDER_AZURE_PROGRESS.md.'
    }
}
