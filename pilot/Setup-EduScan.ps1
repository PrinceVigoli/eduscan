$ErrorActionPreference = 'Stop'
$releaseRoot = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'backend')) { $PSScriptRoot } else { Split-Path -Parent $PSScriptRoot }
$backendRoot = Join-Path $releaseRoot 'backend'
$venvPython = Join-Path $backendRoot '.venv\Scripts\python.exe'

Write-Host 'EduScan Teacher Pilot Setup' -ForegroundColor Green
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw 'Python 3.12 or newer is required. Install Python and enable Add Python to PATH.' }
$versionText = & $pythonCommand.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$versionParts = $versionText.Split('.')
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 12)) { throw "Python 3.12 or newer is required. Found $versionText." }

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creating the private EduScan Python environment...'
    & $pythonCommand.Source -m venv (Join-Path $backendRoot '.venv')
}
Write-Host 'Installing EduScan components. Internet is required for this first setup...'
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $backendRoot 'requirements.txt')

$envPath = Join-Path $backendRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    $randomBytes = New-Object byte[] 48
    $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $randomGenerator.GetBytes($randomBytes) } finally { $randomGenerator.Dispose() }
    $signingKey = [Convert]::ToBase64String($randomBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    $privateKeyLine = (& $venvPython -m app.generate_offline_key).Trim()
    @(
        'EDUSCAN_DATABASE_URL=sqlite:///./eduscan.db'
        'EDUSCAN_ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080'
        'EDUSCAN_SESSION_DAYS=7'
        'EDUSCAN_SECURE_COOKIES=false'
        "EDUSCAN_OFFLINE_SIGNING_KEY=$signingKey"
        $privateKeyLine
        'EDUSCAN_UPLOAD_DIR=uploads'
        'EDUSCAN_AUTO_CREATE_SCHEMA=false'
    ) | Set-Content -LiteralPath $envPath -Encoding UTF8
}

Push-Location $backendRoot
try {
    & $venvPython -m alembic upgrade head
    $adminCount = & $venvPython -c "from app.database import SessionLocal; from app.models import User,UserRole; db=SessionLocal(); print(db.query(User).filter(User.role==UserRole.administrator).count()); db.close()"
    if ([int]$adminCount -eq 0) {
        Write-Host 'Create the IT administrator account used for initial configuration.' -ForegroundColor Yellow
        & $venvPython -m app.seed_admin
    }
} finally { Pop-Location }

Write-Host ''
Write-Host 'Setup completed. Double-click START EDUSCAN.cmd.' -ForegroundColor Green
Read-Host 'Press Enter to close'
