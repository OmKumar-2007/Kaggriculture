$ErrorActionPreference = 'Stop'
$package = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $package '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup-windows.ps1 first.' }
& $python (Join-Path $package 'app\worker.py')
