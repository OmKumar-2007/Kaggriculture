$AzCommand = (Get-Command az -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $AzCommand) {
    $candidate = Join-Path ${env:ProgramFiles} 'Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
    if (Test-Path -LiteralPath $candidate) { $AzCommand = $candidate }
}
if (-not $AzCommand) { throw 'Azure CLI is not installed or discoverable. Install Azure CLI and run az login.' }
