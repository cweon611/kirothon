[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$SyncArgs)
# Local tourism collection into .local-data (same DB as dev-backend.ps1).
# Example: .\scripts\sync-tourism.ps1 --sigungu 46840 --base-ym 202504
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run setup-local.ps1 first.' }
. (Join-Path $PSScriptRoot 'local-env.ps1')
$data = Join-Path $root '.local-data'
$null = New-Item -ItemType Directory -Path $data -Force
$oldDatabase = $env:KIROTHON_DB_PATH
$oldEncoding = $env:PYTHONIOENCODING
$localEnv = Import-LocalEnv (Join-Path $root 'backend\.env')
Push-Location (Join-Path $root 'backend')
try {
    $env:KIROTHON_DB_PATH = Join-Path $data 'records.sqlite3'
    $env:PYTHONIOENCODING = 'utf-8'
    & $python -m app.team.sync_tourism @SyncArgs
    if ($LASTEXITCODE -ne 0) { throw 'Tourism sync failed (see the JSON summary above).' }
} finally {
    $env:KIROTHON_DB_PATH = $oldDatabase
    $env:PYTHONIOENCODING = $oldEncoding
    Restore-LocalEnv $localEnv
    Pop-Location
}
