$ErrorActionPreference = 'Stop'
$az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
$subscription = 'edcb16c2-9bcf-4533-8ca0-d182aaac9b70'
$group = 'rg-farmcraft-evaluators-20261012'
$vm = 'farmcraft-eval-03'
$log = Join-Path $PSScriptRoot 'stop-indonesia-worker-vm.log'
try {
    & $az vm deallocate --subscription $subscription --resource-group $group --name $vm --only-show-errors --output none
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI exit code $LASTEXITCODE" }
    "$(Get-Date -Format o) deallocated $vm" | Add-Content -LiteralPath $log
} catch {
    "$(Get-Date -Format o) failed to deallocate ${vm}: $($_.Exception.Message)" | Add-Content -LiteralPath $log
    throw
}
