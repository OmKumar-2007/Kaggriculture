param([switch]$NoClear)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$worker = Join-Path $repo 'azure-workers/manage.ps1'
$laptop = Join-Path $PSScriptRoot 'launcher.ps1'
$web = 'https://neural-coliseum.onrender.com'
$api = 'https://neural-coliseum-api.onrender.com'

function Azure([string]$action) {
    & $worker -Action $action -ApiUrl $api
    if ($LASTEXITCODE -ne 0) { throw "Azure $action failed." }
}
function Laptop([string]$action) {
    & $laptop -Action $action
    if ($LASTEXITCODE -ne 0) { throw "Laptop $action failed." }
}
function Read-Cloud {
    foreach ($item in @(@('Frontend',$web),@('API',$api))) {
        try {
            $uri = if ($item[0] -eq 'API') { $item[1] + '/ready' } else { $item[1] }
            $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 20
            Write-Host "$($item[0]): HTTP $($response.StatusCode) $uri"
            if ($item[0] -eq 'API') { Write-Host "Readiness: $($response.Content)" }
        } catch { Write-Warning "$($item[0]) unverified: $($_.Exception.Message)" }
    }
}
function Menu {
    if (-not $NoClear) { Clear-Host }
    Write-Host '========================================='
    Write-Host '       FARMCRAFT CONTROL CENTER'
    Write-Host '========================================='
    Write-Host '[1] RENDER + AZURE WORKERS'
    Write-Host '[2] RENDER + LOCAL LAPTOP WORKERS'
    Write-Host '[3] AZURE WORKERS + LAPTOP OVERFLOW'
    Write-Host '[4] LOCAL DEVELOPMENT'
    Write-Host '[5] DEPLOY / UPDATE AZURE WORKERS'
    Write-Host '[6] START / STOP / DRAIN WORKERS'
    Write-Host '[7] WORKER STATUS AND DIAGNOSTICS'
    Write-Host '[8] REAL MATCH BENCHMARK'
    Write-Host '[9] 100-USER LOAD TEST (ISOLATED ONLY)'
    Write-Host '[10] OPEN RENDER WEBSITE / ADMIN'
    Write-Host '[11] AZURE RESOURCE AND COST STATUS'
    Write-Host '[12] EXIT'
}
while ($true) {
    Menu
    $choice = (Read-Host 'Choice').Trim()
    try {
        switch ($choice) {
            '1' { Read-Cloud; Azure 'Status'; Write-Host 'Azure VM must be registered and active before it can claim Render jobs.' }
            '2' { Read-Cloud; Laptop 'Start' }
            '3' { Read-Cloud; Azure 'Status'; Laptop 'Start'; Write-Host 'Both workers use the same server-owned claim and lease protocol.' }
            '4' { & (Join-Path $repo 'run-app.bat') }
            '5' {
                Write-Host 'Preview first. Provisioning requires an approved budget, pushed commit and explicit confirmation.'
                $action = (Read-Host 'P=preview, V=provision, R=register first worker, W=add worker 2, Enter=back').Trim().ToUpperInvariant()
                if ($action -eq 'P') { & $worker -Action Plan -ApiUrl $api }
                if ($action -eq 'V') {
                    $ref = (Read-Host 'Pushed 40-character Git commit').Trim()
                    & $worker -Action Provision -ApiUrl $api -GitRef $ref
                }
                if ($action -eq 'R') { Azure 'Register' }
                if ($action -eq 'W') { & $worker -Action AddWorker -Slot 2 -ApiUrl $api }
            }
            '6' {
                $action = (Read-Host 'A=start Azure, D=drain Azure, X=deallocate Azure, L=start laptop, S=stop laptop').Trim().ToUpperInvariant()
                switch ($action) {
                    'A' { Azure 'Start' }
                    'D' { Azure 'Drain' }
                    'X' { Azure 'Deallocate' }
                    'L' { Laptop 'Start' }
                    'S' { Laptop 'Stop' }
                }
            }
            '7' { Azure 'Status'; Laptop 'Health' }
            '8' { Laptop 'Benchmark' }
            '9' {
                $url = 'http://127.0.0.1:18000'
                $ready = Invoke-RestMethod -Uri "$url/ready" -TimeoutSec 8
                if ($ready.status -ne 'ready') { throw 'Isolated API on port 18000 is not ready.' }
                if ((Read-Host 'This creates 100 isolated test users. Type RUN ISOLATED LOAD') -ne 'RUN ISOLATED LOAD') { throw 'Load test cancelled.' }
                $env:LOAD_TEST_ISOLATED = '1'
                $env:LOAD_PROFILE = 'contestants'
                New-Item -ItemType Directory -Force -Path (Join-Path $repo 'load_tests/data') | Out-Null
                & locust -f (Join-Path $repo 'load_tests/locustfile.py') --headless -u 100 -r 10 -t 5m --host $url --csv (Join-Path $repo 'load_tests/data/contestants')
                if ($LASTEXITCODE -ne 0) { throw 'Isolated Locust load test failed.' }
            }
            '10' { Start-Process -FilePath $web; Start-Process -FilePath "$web/admin" }
            '11' { Azure 'Status'; Azure 'Cost' }
            '12' { exit 0 }
            default { Write-Host 'Choose 1-12.' }
        }
    } catch { Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red }
    $null = Read-Host 'Press Enter to continue'
}
