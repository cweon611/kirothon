[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$ListenAddress = '127.0.0.1',
    # Persistent data folder OUTSIDE the code folder, so replacing/redeploying code never touches the DB.
    [string]$DataDir = (Join-Path $HOME 'kirothon-data'),
    [switch]$SkipBuild
)
# Production-style single process: builds frontend/dist and serves it from the API on the same origin
# (KIROTHON_FRONTEND_DIST), so the built app's relative /api/... calls work without the Vite dev proxy.
# No --reload. Support programs refresh on their own schedule inside this process
# (KIROTHON_BENEFIT_SYNC_MODE=on); tourism/festivals are refreshed by prepare-data.ps1 on a schedule
# (see README), never on every start.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run setup-local.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend\node_modules') -PathType Container)) { throw 'Run setup-local.ps1 first.' }
if (-not $SkipBuild) {
    Push-Location (Join-Path $root 'frontend')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
}
$dist = Join-Path $root 'frontend\dist'
if (-not (Test-Path -LiteralPath (Join-Path $dist 'index.html') -PathType Leaf)) { throw 'frontend/dist is missing; run without -SkipBuild.' }
. (Join-Path $PSScriptRoot 'local-env.ps1')
$null = New-Item -ItemType Directory -Path $DataDir -Force
$names = 'KIROTHON_DB_PATH','KIROTHON_FRONTEND_DIST','KIROTHON_AI_MODE','KIROTHON_BENEFIT_SYNC_MODE','PYTHONIOENCODING'
$saved = @{}; foreach ($n in $names) { $saved[$n] = [Environment]::GetEnvironmentVariable($n, 'Process') }
$localEnv = Import-LocalEnv (Join-Path $root 'backend\.env')
Push-Location (Join-Path $root 'backend')
try {
    $env:KIROTHON_DB_PATH = Join-Path $DataDir 'records.sqlite3'
    $env:KIROTHON_FRONTEND_DIST = $dist
    # Local machines have no AWS role: keep mock unless the environment already chose a mode.
    if (-not $env:KIROTHON_AI_MODE) { $env:KIROTHON_AI_MODE = 'mock' }
    if (-not $env:KIROTHON_BENEFIT_SYNC_MODE) { $env:KIROTHON_BENEFIT_SYNC_MODE = 'on' }
    $env:PYTHONIOENCODING = 'utf-8'
    Write-Output "DB: $env:KIROTHON_DB_PATH"
    Write-Output "App: http://${ListenAddress}:$Port  (AI mode: $env:KIROTHON_AI_MODE)"
    & $python -m uvicorn app.main:app --host $ListenAddress --port $Port --workers 1
    if ($LASTEXITCODE -ne 0) { throw 'API stopped with an error.' }
} finally {
    foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $saved[$n], 'Process') }
    Restore-LocalEnv $localEnv
    Pop-Location
}
