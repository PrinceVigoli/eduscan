param(
  [string]$SigningThumbprint,
  [string]$TimestampUrl='http://timestamp.digicert.com',
  [switch]$RequireSignature
)
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path -Parent $PSScriptRoot
$python=Join-Path $sourceRoot 'backend\.venv\Scripts\python.exe'
$dist=Join-Path $sourceRoot 'release\EduScan-Windows-0.4.0'
$installer=Join-Path $sourceRoot 'release\EduScan-Teacher-Setup-0.4.0.exe'
$work=Join-Path $sourceRoot 'build\enterprise'
$spec=Join-Path $sourceRoot 'build\EduScan-Teacher.spec'

function Invoke-CodeSigning([string]$FilePath){
  if(-not $SigningThumbprint){
    if($RequireSignature){throw 'A code-signing certificate thumbprint is required.'}
    Write-Warning "Unsigned build: $FilePath"
    return
  }
  $certificate=Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object {$_.Thumbprint -eq $SigningThumbprint -and $_.HasPrivateKey} | Select-Object -First 1
  if(-not $certificate){throw "No usable CurrentUser code-signing certificate was found for thumbprint $SigningThumbprint."}
  if($certificate.NotAfter -le (Get-Date)){throw "The code-signing certificate expired on $($certificate.NotAfter)."}
  $signTool=Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue | Where-Object {$_.FullName -match '\\x64\\signtool\.exe$'} | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
  if(-not $signTool){throw 'Windows SDK SignTool was not found.'}
  & $signTool sign /sha1 $SigningThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $FilePath
  if($LASTEXITCODE-ne 0){throw "Signing failed: $FilePath"}
  & $signTool verify /pa /v $FilePath
  if($LASTEXITCODE-ne 0){throw "Signature verification failed: $FilePath"}
}
foreach($target in @($dist,$installer,$work,$spec)){if(Test-Path -LiteralPath $target){throw "Build target already exists: $target"}}
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name EduScan-Teacher `
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
  --collect-all alembic --collect-all pwdlib --collect-all pystray `
  --distpath $dist --workpath $work --specpath (Join-Path $sourceRoot 'build') `
  (Join-Path $PSScriptRoot 'desktop_launcher.py')
if($LASTEXITCODE-ne 0){throw 'Graphical application build failed.'}
Invoke-CodeSigning (Join-Path $dist 'EduScan-Teacher.exe')
$iscc=Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
if(-not(Test-Path -LiteralPath $iscc)){throw 'Inno Setup compiler was not found.'}
& $iscc (Join-Path $PSScriptRoot 'EduScan-Installer.iss')
if($LASTEXITCODE-ne 0){throw 'Installer build failed.'}
Invoke-CodeSigning $installer
Write-Host "Installer created: $installer" -ForegroundColor Green
