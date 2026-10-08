$pidFile = Join-Path $PSScriptRoot 'data/worker.pid'
if (Test-Path -LiteralPath $pidFile) {
    $workerId = [int](Get-Content -LiteralPath $pidFile -Raw)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$workerId" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -match 'backend\.worker') {
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$workerId" -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $workerId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile
}
