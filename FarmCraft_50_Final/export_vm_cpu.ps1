# Read-only Azure Monitor CPU export for the two existing evaluation VMs.
$ErrorActionPreference = 'Stop'
$resourceGroup = 'rg-farmcraft-evaluators-20261012'
$names = @('farmcraft-eval-02', 'farmcraft-eval-03')
$rows = @()
foreach ($name in $names) {
    $id = & az.cmd vm show -g $resourceGroup -n $name --query id -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $id) { throw "Cannot resolve $name" }
    $json = & az.cmd monitor metrics list --resource $id --metric 'Percentage CPU' --interval PT1M --aggregation Average -o json
    if ($LASTEXITCODE -ne 0) { throw "Cannot read Azure Monitor for $name" }
    $payload = $json | ConvertFrom-Json
    foreach ($item in $payload.value[0].timeseries[0].data) {
        if ($null -ne $item.average) {
            $rows += [pscustomobject]@{vm=$name;timeStamp=$item.timeStamp;averageCpuPercent=$item.average}
        }
    }
}
$path = Join-Path (Split-Path $PSScriptRoot -Parent) 'reports/FARMCRAFT_LOAD50_AZURE_VM_CPU.csv'
$rows | Sort-Object vm,timeStamp | Export-Csv -LiteralPath $path -NoTypeInformation
Write-Host "Exported $($rows.Count) Azure Monitor CPU readings to $path"
