param(
  [Parameter(Mandatory=$true)][string]$SigningThumbprint,
  [string]$TimestampUrl='http://timestamp.digicert.com'
)

$ErrorActionPreference='Stop'
$sourceRoot=Split-Path -Parent $PSScriptRoot
$files=@(
  (Join-Path $sourceRoot 'release\EduScan-Windows-0.4.0\EduScan-Teacher.exe'),
  (Join-Path $sourceRoot 'release\EduScan-Teacher-Setup-0.4.0.exe')
)
$certificate=Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object {$_.Thumbprint -eq $SigningThumbprint -and $_.HasPrivateKey} | Select-Object -First 1
if(-not $certificate){throw "No usable CurrentUser code-signing certificate was found for thumbprint $SigningThumbprint."}
if($certificate.NotAfter -le (Get-Date)){throw "The code-signing certificate expired on $($certificate.NotAfter)."}
$signTool=Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue | Where-Object {$_.FullName -match '\\x64\\signtool\.exe$'} | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if(-not $signTool){throw 'Windows SDK SignTool was not found.'}
foreach($file in $files){
  if(-not(Test-Path -LiteralPath $file)){throw "Release file was not found: $file"}
  & $signTool sign /sha1 $SigningThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $file
  if($LASTEXITCODE-ne 0){throw "Signing failed: $file"}
  & $signTool verify /pa /v $file
  if($LASTEXITCODE-ne 0){throw "Signature verification failed: $file"}
}
Write-Host 'EduScan application and installer were signed and verified.' -ForegroundColor Green
