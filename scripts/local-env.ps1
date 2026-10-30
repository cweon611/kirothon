# Dot-source only. Loads backend/.env (git-ignored KEY=VALUE lines) into this process.
# Variables already set in the environment win. Values are never printed.
function Import-LocalEnv([string]$Path) {
    $saved = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $saved }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith('#') -or -not $text.Contains('=')) { continue }
        $name, $value = $text.Split('=', 2)
        $name, $value = $name.Trim(), $value.Trim()
        if (-not $value -or [Environment]::GetEnvironmentVariable($name, 'Process')) { continue }
        $saved[$name] = $null
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
    if ($saved.Count) { Write-Host ('Loaded from backend/.env: ' + (($saved.Keys | Sort-Object) -join ', ')) }
    return $saved
}

function Restore-LocalEnv($Saved) {
    foreach ($name in $Saved.Keys) { [Environment]::SetEnvironmentVariable($name, $Saved[$name], 'Process') }
}
