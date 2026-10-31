[CmdletBinding()]
param(
    [switch]$SkipTourism,
    [switch]$SkipBenefits,
    [string]$TourismSteps = '',
    # Default: the dev DB used by dev-backend.ps1. For run-production.ps1 pass the same -DataDir it uses
    # (default there: $HOME\kirothon-data).
    [string]$DataDir = ''
)
# One command for all local data used by the app, in order, into the same DB as dev-backend.ps1:
#   1. tourism (app.team.sync_tourism): codes, places, std, festivals, hubs, related, match, details
#      -> course recommendation (spots/food/stay) and festivals
#   2. support programs (app.team.benefits.cli sync): 반값여행 현황 page + 공공서비스 API
#   3. readiness report (app.team.data_readiness): what each feature can actually use
# Existing data is never deleted; a failed source keeps its previous rows.
# Keys come from the environment or backend/.env (values are never printed):
#   TOURAPI_SERVICE_KEY (or KIROTHON_DATA_GO_KR_SERVICE_KEY), KIROTHON_DATA_GO_KR_SERVICE_KEY
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run setup-local.ps1 first.' }
. (Join-Path $PSScriptRoot 'local-env.ps1')
$data = if ($DataDir) { $DataDir } else { Join-Path $root '.local-data' }
$null = New-Item -ItemType Directory -Path $data -Force
$saved = @{ KIROTHON_AI_MODE = $env:KIROTHON_AI_MODE; KIROTHON_DB_PATH = $env:KIROTHON_DB_PATH; PYTHONIOENCODING = $env:PYTHONIOENCODING }
$localEnv = Import-LocalEnv (Join-Path $root 'backend\.env')
$results = [ordered]@{}
Push-Location (Join-Path $root 'backend')
try {
    $env:KIROTHON_AI_MODE = 'mock'
    $env:KIROTHON_DB_PATH = Join-Path $data 'records.sqlite3'
    $env:PYTHONIOENCODING = 'utf-8'
    Write-Output "DB: $env:KIROTHON_DB_PATH"
    if (-not ($env:TOURAPI_SERVICE_KEY -or $env:KIROTHON_DATA_GO_KR_SERVICE_KEY)) {
        Write-Warning 'TourAPI key not set: tourism/festival steps will be recorded as failed (missing key).'
    }
    if ($SkipTourism) { $results['tourism'] = 'skipped' } else {
        Write-Output '== 1/3 tourism: places, festivals, hubs, related (app.team.sync_tourism) =='
        $tourArgs = @(); if ($TourismSteps) { $tourArgs = @('--steps', $TourismSteps) }
        & $python -m app.team.sync_tourism @tourArgs
        $results['tourism'] = if ($LASTEXITCODE -eq 0) { 'ok' } else { "failed(exit $LASTEXITCODE)" }
    }
    if ($SkipBenefits) { $results['benefits'] = 'skipped' } else {
        Write-Output '== 2/3 support programs: kto_tour50 page + gov24 API (app.team.benefits.cli sync) =='
        & $python -m app.team.benefits.cli sync
        $results['benefits'] = if ($LASTEXITCODE -eq 0) { 'ok' } else { "partial_or_failed(exit $LASTEXITCODE)" }
    }
    Write-Output '== 3/3 readiness (app.team.data_readiness) =='
    & $python -m app.team.data_readiness
    $results['course_data'] = if ($LASTEXITCODE -eq 0) { 'ready(all 27 regions have spots)' } else { 'NOT READY(see regions_without_spots)' }
} finally {
    foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process') }
    Restore-LocalEnv $localEnv
    Pop-Location
}
Write-Output '== summary =='
$results.GetEnumerator() | ForEach-Object { Write-Output ("{0,-12} {1}" -f $_.Key, $_.Value) }
if ($results.Values | Where-Object { $_ -notmatch '^(ok|skipped|ready)' }) {
    Write-Warning 'Some steps failed or data is incomplete. The API reports this in data_status / tourism_data.'
    exit 1
}
Write-Output 'PREPARE_OK'
