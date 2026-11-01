$ErrorActionPreference='Stop'
$sourceRoot=Split-Path -Parent $PSScriptRoot
$python=Join-Path $sourceRoot 'backend\.venv\Scripts\python.exe'
$outputRoot=Join-Path $sourceRoot 'release\EduScan-Standalone-0.3.0'
if(Test-Path -LiteralPath $outputRoot){throw 'Standalone 0.3.0 output already exists. Remove it intentionally before rebuilding.'}
& $python -m PyInstaller --noconfirm --clean --onefile --console --name EduScan-Teacher `
  --paths (Join-Path $sourceRoot 'backend') `
  --add-data "$(Join-Path $sourceRoot 'backend\migrations');backend\migrations" `
  --add-data "$(Join-Path $sourceRoot 'backend\app\templates');app\templates" `
  --add-data "$(Join-Path $sourceRoot 'backend\alembic.ini');backend" `
  --add-data "$(Join-Path $sourceRoot 'index.html');web" `
  --add-data "$(Join-Path $sourceRoot 'styles.css');web" `
  --add-data "$(Join-Path $sourceRoot 'app.js');web" `
  --add-data "$(Join-Path $sourceRoot 'offline-db.js');web" `
  --add-data "$(Join-Path $sourceRoot 'sw.js');web" `
  --add-data "$(Join-Path $sourceRoot 'manifest.webmanifest');web" `
  --add-data "$(Join-Path $sourceRoot 'icons');web\icons" `
  --add-data "$(Join-Path $sourceRoot 'vendor');web\vendor" `
  --collect-all alembic --collect-all pwdlib `
  --distpath $outputRoot --workpath (Join-Path $sourceRoot 'build\standalone') --specpath (Join-Path $sourceRoot 'build') `
  (Join-Path $PSScriptRoot 'desktop_launcher.py')
if($LASTEXITCODE-ne 0){throw 'PyInstaller build failed.'}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'STANDALONE GUIDE.txt') -Destination $outputRoot
Set-Content -LiteralPath (Join-Path $outputRoot 'BACKUP EDUSCAN.cmd') -Encoding ASCII -Value '@echo off', '"%~dp0EduScan-Teacher.exe" --backup', 'if errorlevel 1 pause'
Compress-Archive -LiteralPath $outputRoot -DestinationPath "$outputRoot.zip" -CompressionLevel Optimal
Write-Host "Standalone release created: $outputRoot.zip" -ForegroundColor Green
