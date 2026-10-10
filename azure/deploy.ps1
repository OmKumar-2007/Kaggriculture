param([switch]$PreviewOnly, [switch]$LegacyFullAzure)
$ErrorActionPreference = 'Stop'
if (-not $LegacyFullAzure) {
    throw 'Archived full-Azure control-plane deployment. FarmCraft now keeps Render and uses azure-workers/manage.ps1 for Azure evaluator VMs. Pass -LegacyFullAzure only for an explicitly approved legacy review.'
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'cli.ps1')
$profile = Join-Path $repo 'config\local-profiles\azure-site.json'
& (Join-Path $PSScriptRoot 'preflight.ps1')
if (-not (Test-Path -LiteralPath $profile)) { throw 'Run First-Time Setup and edit azure-site.json first.' }
$site = Get-Content -LiteralPath $profile -Raw | ConvertFrom-Json
if (-not $site.resourceGroup -or -not $site.region) { throw 'Azure resourceGroup and region are required.' }
Write-Host 'Bill of materials for the control-plane preview:'
Write-Host ' - Azure Storage account and private Blob container'
Write-Host ' - Azure Container Apps environment (Consumption profile)'
Write-Host ' - Virtual network, delegated subnets, private DNS zone and link'
Write-Host ' - Azure Container Registry Standard and managed pull identity'
Write-Host ' - Built React frontend served from the FastAPI Container App (same origin)'
Write-Host ' - Managed PostgreSQL, API image, and cloud evaluations are NOT provisioned by this preview.'
Write-Host 'Azure for Students credit is finite. Budget alerts are not a hard cap.'
Write-Host 'The Azure website is not operational until database, API deployment, Blob identity, and frontend image are configured.'
$existing = & $AzCommand group exists --name $site.resourceGroup --output tsv
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the Azure resource group.' }
if ($existing -ne 'true') {
    if ($PreviewOnly) { throw "Resource group $($site.resourceGroup) does not exist; create it before previewing." }
    if ((Read-Host "Type CREATE GROUP to create $($site.resourceGroup) in $($site.region)") -ne 'CREATE GROUP') {
        Write-Host 'Resource group creation cancelled.'; return
    }
    & $AzCommand group create --name $site.resourceGroup --location $site.region --tags app=FarmCraft managedBy=bicep purpose=competition-control-plane --output none
    if ($LASTEXITCODE -ne 0) { throw 'Resource group creation failed.' }
}
$previewJson = & $AzCommand deployment group what-if --resource-group $site.resourceGroup --template-file (Join-Path $PSScriptRoot 'control-plane.bicep') --parameters ("location=" + [string]$site.region) --output json
if ($LASTEXITCODE -ne 0) { throw 'Azure what-if validation failed; no deployment was made.' }
$preview = $previewJson | ConvertFrom-Json
Write-Host 'Azure what-if changes (resource identifiers withheld):'
foreach ($change in $preview.properties.changes) {
    $after = $change.after
    Write-Host " - $($change.changeType): $($after.type) $($after.name) $($after.location)"
}
if ($PreviewOnly) { return }
if ((Read-Host 'Type DEPLOY BASE to provision the previewed Azure base resources') -ne 'DEPLOY BASE') {
    Write-Host 'Deployment cancelled.'; return
}
& $AzCommand deployment group create --resource-group $site.resourceGroup --template-file (Join-Path $PSScriptRoot 'control-plane.bicep') --parameters ("location=" + [string]$site.region)
if ($LASTEXITCODE -ne 0) { throw 'Azure base resource deployment failed. Inspect the Azure deployment operation.' }
Write-Host 'Base Azure resources deployed. Application and cloud evaluations remain disabled; see azure/README.md.'
