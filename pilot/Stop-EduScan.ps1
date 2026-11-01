$ErrorActionPreference = 'Stop'
$releaseRoot = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'backend')) { $PSScriptRoot } else { Split-Path -Parent $PSScriptRoot }
$runtimePath = Join-Path $releaseRoot '.eduscan-runtime.json'
if (-not (Test-Path -LiteralPath $runtimePath)) { Write-Host 'EduScan is not running.'; exit }
$runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
foreach ($processId in @($runtime.api_pid,$runtime.web_pid)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if ($process -and ($process.CommandLine -match 'uvicorn|http\.server') -and $process.CommandLine.Contains($releaseRoot)) {
        Stop-Process -Id $processId -Force
    }
}
Remove-Item -LiteralPath $runtimePath -Force
Write-Host 'EduScan stopped safely.'
