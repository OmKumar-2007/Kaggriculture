param(
    [ValidateSet('BuildDeploy','Verify','Rollback')][string]$Action = 'Verify',
    [string]$ExpectedCurrentDigest = '',
    [string]$RollbackDigest = '',
    [string]$Tag = 'multiworker-20261012'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$group = 'rg-farmcraft-azure-staging-20261012'
$app = 'farmcraft-staging-api'
$registry = 'fcstg6chsyox4t2zfa'
$repository = "$registry.azurecr.io/farmcraft"
$base = 'https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
$subscription = 'edcb16c2-9bcf-4533-8ca0-d182aaac9b70'

function Current-App {
    $item = & az containerapp show -g $group -n $app --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $item.properties.provisioningState -ne 'Succeeded') {
        throw 'Staging Container App inventory failed.'
    }
    return $item
}
function Assert-Ready([string]$digest) {
    $deadline = (Get-Date).AddMinutes(5)
    do {
        Start-Sleep -Seconds 8
        $item = Current-App
        $revision = $item.properties.latestReadyRevisionName
        if ($item.properties.template.containers[0].image -eq "$repository@$digest" -and
            $revision -and $revision -eq $item.properties.latestRevisionName) {
            $revisions = & az containerapp revision list -g $group -n $app --output json | ConvertFrom-Json
            $ready = $revisions | Where-Object name -eq $revision | Select-Object -First 1
            if ($ready.properties.template.containers[0].image -eq "$repository@$digest" -and
                $ready.properties.healthState -eq 'Healthy' -and $ready.properties.runningState -eq 'Running') {
                $response = Invoke-RestMethod "$base/ready" -TimeoutSec 45
                $version = Invoke-RestMethod "$base/api/remote-workers/version" -TimeoutSec 45
                $hash = (Get-FileHash (Join-Path $root 'config/evaluation.json') -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($response.status -eq 'ready' -and $response.checks.database -and
                    $response.checks.storage -and $response.checks.sessions -and
                    $version.evaluatorVersion -eq '2026.10.12' -and
                    $version.evaluationConfigSha256 -eq $hash -and $version.evaluatorMode -eq 'LOCAL') {
                    return $revision
                }
            }
        }
    } while ((Get-Date) -lt $deadline)
    throw "Staging revision did not pass readiness for $digest."
}
function Assert-Closed {
    $file = Join-Path $root 'config/local-profiles/phase4-admin.dpapi'
    $secure = Get-Content -LiteralPath $file | ConvertTo-SecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $null = Invoke-RestMethod -Method Post -Uri "$base/api/admin/login" -Body (@{password=$password}|ConvertTo-Json) `
            -ContentType application/json -WebSession $session -TimeoutSec 45
        $event = Invoke-RestMethod "$base/api/admin/event" -WebSession $session -TimeoutSec 45
        if ($event.mode -ne 'MAINTENANCE' -or $event.registrationsEnabled -or $event.uploadsEnabled -or
            $event.sandboxEnabled -or $event.officialEnabled -or $event.tournamentEnabled) {
            throw 'Staging participant gates are open; stop before deployment.'
        }
    } finally {
        $password = $null
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        $secure.Dispose()
    }
}

$account = & az account show --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $account.id -ne $subscription -or $account.state -ne 'Enabled') {
    throw 'Select the reviewed Azure for Students subscription.'
}
if ((& az group exists -n $group).Trim() -ne 'true') { throw 'Approved staging group is absent.' }
$before = Current-App
$oldImage = $before.properties.template.containers[0].image
$oldDigest = $oldImage.Split('@')[-1]
if ($oldImage -notlike "$repository@sha256:*") { throw 'Staging image is not pinned to a registry digest.' }

switch ($Action) {
    'Verify' {
        Assert-Closed
        $revision = Assert-Ready $oldDigest
        Write-Host "AZURE STAGING ready: revision=$revision image=$oldDigest publicGates=closed"
    }
    'Rollback' {
        if ($RollbackDigest -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Supply an inspected rollback digest.' }
        Assert-Closed
        & az containerapp update -g $group -n $app --image "$repository@$RollbackDigest" --output none
        if ($LASTEXITCODE -ne 0) { throw 'Rollback update failed; inspect staging revisions.' }
        $revision = Assert-Ready $RollbackDigest
        Assert-Closed
        Write-Host "AZURE STAGING rollback ready: revision=$revision image=$RollbackDigest"
    }
    'BuildDeploy' {
        if ($ExpectedCurrentDigest -notmatch '^sha256:[a-f0-9]{64}$' -or $ExpectedCurrentDigest -ne $oldDigest) {
            throw 'ExpectedCurrentDigest must match the inspected current staging digest.'
        }
        if ($Tag -notmatch '^[a-z0-9][a-z0-9._-]{1,60}$') { throw 'Invalid immutable image tag.' }
        Assert-Closed
        Push-Location $root
        try {
            & docker build -f azure/Dockerfile -t "${repository}:$Tag" .
            if ($LASTEXITCODE -ne 0) { throw 'Image build failed.' }
            $hash = (Get-FileHash 'config/evaluation.json' -Algorithm SHA256).Hash.ToLowerInvariant()
            $check = & docker run --rm --entrypoint python "${repository}:$Tag" -c `
                "from pathlib import Path; import hashlib; p=Path('/app/config/evaluation.json'); print(hashlib.sha256(p.read_bytes()).hexdigest()); print(Path('/app/config/local-profiles').exists())"
            if ($LASTEXITCODE -ne 0 -or $check[0] -ne $hash -or $check[1] -ne 'False') {
                throw 'Image configuration or secret exclusion check failed.'
            }
            & az acr login -n $registry --output none
            if ($LASTEXITCODE -ne 0) { throw 'ACR login failed.' }
            & docker push "${repository}:$Tag"
            if ($LASTEXITCODE -ne 0) { throw 'ACR push failed.' }
            $manifest = & az acr manifest show-metadata -r $registry -n "farmcraft:$Tag" --output json | ConvertFrom-Json
            $digest = $manifest.digest
            if ($LASTEXITCODE -ne 0 -or $digest -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Registry digest could not be verified.' }
            if ((Current-App).properties.template.containers[0].image -ne $oldImage) {
                throw 'Staging changed during build; inspect before deployment.'
            }
            try {
                & az containerapp update -g $group -n $app --image "$repository@$digest" --output none
                if ($LASTEXITCODE -ne 0) { throw 'Staging image update failed.' }
                $revision = Assert-Ready $digest
                Assert-Closed
                Write-Host "AZURE STAGING deployed: revision=$revision image=$digest rollback=$oldDigest"
            } catch {
                Write-Warning "Staging verification failed; restoring prior image $oldDigest."
                & az containerapp update -g $group -n $app --image $oldImage --output none
                if ($LASTEXITCODE -ne 0) { throw 'Automatic rollback command failed; inspect staging immediately.' }
                $null = Assert-Ready $oldDigest
                throw
            }
        } finally { Pop-Location }
    }
}
