$package = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
[System.IO.File]::WriteAllText((Join-Path $package '.stop'), 'stop')
Write-Host 'Graceful stop requested. Active containers are being cancelled.'
