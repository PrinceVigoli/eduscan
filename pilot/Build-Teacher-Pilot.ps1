$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $sourceRoot 'release'
$releaseName = 'EduScan-Teacher-Pilot-0.2.0'
$destination = Join-Path $releaseRoot $releaseName
$zipPath = Join-Path $releaseRoot "$releaseName.zip"
if ((Test-Path -LiteralPath $destination) -or (Test-Path -LiteralPath $zipPath)) { throw "Release $releaseName already exists. Remove or rename it intentionally before rebuilding." }
New-Item -ItemType Directory -Path $destination | Out-Null
New-Item -ItemType Directory -Path (Join-Path $destination 'backend') | Out-Null

foreach ($file in @('index.html','styles.css','app.js','offline-db.js','sw.js','manifest.webmanifest')) { Copy-Item -LiteralPath (Join-Path $sourceRoot $file) -Destination $destination }
foreach ($folder in @('icons','vendor')) { Copy-Item -LiteralPath (Join-Path $sourceRoot $folder) -Destination $destination -Recurse }
foreach ($file in @('requirements.txt','alembic.ini')) { Copy-Item -LiteralPath (Join-Path $sourceRoot "backend\$file") -Destination (Join-Path $destination 'backend') }
foreach ($folder in @('app','migrations')) { Copy-Item -LiteralPath (Join-Path $sourceRoot "backend\$folder") -Destination (Join-Path $destination 'backend') -Recurse }
foreach ($file in @('Setup-EduScan.ps1','Start-EduScan.ps1','Stop-EduScan.ps1','Backup-EduScan.ps1','SETUP EDUSCAN.cmd','START EDUSCAN.cmd','STOP EDUSCAN.cmd','BACKUP EDUSCAN.cmd','TEACHER PILOT GUIDE.txt','RELEASE NOTES.txt')) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $destination }
Compress-Archive -LiteralPath $destination -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "Release created: $zipPath" -ForegroundColor Green
