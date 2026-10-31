[CmdletBinding()]
param(
    [switch]$SkipFestivals,
    [switch]$SkipBenefits
)
# Kept for existing instructions. It now runs the common data preparation (prepare-data.ps1), so course
# spots/food/stay are collected together with festivals and support programs. Previously this script
# collected only festivals, which left course recommendation without any places.
# -SkipFestivals skips the whole tourism collection (places and festivals come from the same sync).
$ErrorActionPreference = 'Stop'
$forward = @{}
if ($SkipFestivals) { $forward['SkipTourism'] = $true }
if ($SkipBenefits) { $forward['SkipBenefits'] = $true }
& (Join-Path $PSScriptRoot 'prepare-data.ps1') @forward
exit $LASTEXITCODE
