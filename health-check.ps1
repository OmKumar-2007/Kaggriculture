Set-Location $PSScriptRoot
docker compose ps
$port = '8000'
if (Test-Path .env) { $line = Get-Content .env | Where-Object { $_ -like 'FARMCRAFT_PORT=*' } | Select-Object -First 1; if ($line) { $port = $line.Split('=',2)[1] } }
try { Invoke-RestMethod -Uri "http://127.0.0.1:$port/ready" -TimeoutSec 5 | ConvertTo-Json -Depth 5 } catch { Write-Error "Web/API health check failed: $_" }
if (Test-Path data/host-worker.pid) { $workerId = [int](Get-Content data/host-worker.pid -Raw); Get-Process -Id $workerId -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime }
