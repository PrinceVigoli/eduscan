$ErrorActionPreference = 'Stop'
$releaseRoot = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'backend')) { $PSScriptRoot } else { Split-Path -Parent $PSScriptRoot }
$backendRoot = Join-Path $releaseRoot 'backend'
$venvPython = Join-Path $backendRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run EduScan setup first.' }
Push-Location $backendRoot
try { & $venvPython -m app.backup } finally { Pop-Location }
Write-Host 'Copy the newest ZIP from backend\backups to a USB drive or another protected location.' -ForegroundColor Green
Read-Host 'Press Enter to close'
