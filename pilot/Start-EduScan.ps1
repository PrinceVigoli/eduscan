$ErrorActionPreference = 'Stop'
$releaseRoot = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'backend')) { $PSScriptRoot } else { Split-Path -Parent $PSScriptRoot }
$backendRoot = Join-Path $releaseRoot 'backend'
$venvPython = Join-Path $backendRoot '.venv\Scripts\python.exe'
$runtimePath = Join-Path $releaseRoot '.eduscan-runtime.json'
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'EduScan is not set up. Run SETUP EDUSCAN.cmd first.' }

if (Test-Path -LiteralPath $runtimePath) {
    try {
        $existing = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
        if ((Get-Process -Id $existing.api_pid -ErrorAction SilentlyContinue) -and (Get-Process -Id $existing.web_pid -ErrorAction SilentlyContinue)) {
            Start-Process 'http://localhost:8080'
            exit
        }
    } catch {}
}

$api = Start-Process -FilePath $venvPython -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru
$web = Start-Process -FilePath $venvPython -ArgumentList @('-m','http.server','8080','--bind','127.0.0.1') -WorkingDirectory $releaseRoot -WindowStyle Hidden -PassThru
@{ api_pid=$api.Id; web_pid=$web.Id; release_root=$releaseRoot; started_at=(Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $runtimePath -Encoding UTF8

$ready = $false
for ($attempt=0; $attempt -lt 30; $attempt++) {
    try { $health=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2; if ($health.StatusCode -eq 200) { $ready=$true; break } } catch {}
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw 'EduScan could not start. Run STOP EDUSCAN.cmd, then try again.' }
Start-Process 'http://localhost:8080'
