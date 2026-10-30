[CmdletBinding()]
param(
    [switch]$SkipFestivals,
    [switch]$SkipBenefits
)
# Prepares the local DB used by dev-backend.ps1 for POST /api/team/date-recommendations.
# Keys are read from the environment only (never written or printed):
#   TOURAPI_SERVICE_KEY or KIROTHON_DATA_GO_KR_SERVICE_KEY  -> festivals (KorService2) and gov24 benefits
# The 반값여행 현황 page (kto_tour50) needs no key.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run setup-local.ps1 first.' }
$data = Join-Path $root '.local-data'
$null = New-Item -ItemType Directory -Path $data -Force
$oldMode = $env:KIROTHON_AI_MODE
$oldDatabase = $env:KIROTHON_DB_PATH
Push-Location (Join-Path $root 'backend')
$failed = @()
try {
    $env:KIROTHON_AI_MODE = 'mock'
    $env:KIROTHON_DB_PATH = Join-Path $data 'records.sqlite3'
    if (-not $SkipFestivals) {
        if (-not ($env:TOURAPI_SERVICE_KEY -or $env:KIROTHON_DATA_GO_KR_SERVICE_KEY)) {
            Write-Warning 'TourAPI key not set: festival sync will be recorded as failed (missing key).'
        }
        Write-Output '== festivals (KorService2 searchFestival2) =='
        & $python -m app.team.sync_tourism --steps codes,festivals
        if ($LASTEXITCODE -ne 0) { $failed += 'festivals' }
    }
    if (-not $SkipBenefits) {
        Write-Output '== benefits (반값여행 현황 + 공공서비스 API) =='
        & $python -m app.team.benefits.cli sync
        if ($LASTEXITCODE -ne 0) { $failed += 'benefits' }
    }
} finally {
    $env:KIROTHON_AI_MODE = $oldMode
    $env:KIROTHON_DB_PATH = $oldDatabase
    Pop-Location
}
if ($failed) { Write-Warning ("Some sources failed or are not configured: " + ($failed -join ', ') + ". The API reports this in data_status.") }
else { Write-Output 'PREPARE_OK' }
