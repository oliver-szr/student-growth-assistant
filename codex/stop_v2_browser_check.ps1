param()
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.runtime'
$statePath = Join-Path $runtime 'v2-browser-check.json'
if (!(Test-Path -LiteralPath $statePath)) { Write-Output 'No V2 browser-check instance is recorded.'; return }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
foreach ($entry in $state.processes) {
    $process = Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
    if (!$process) { continue }
    $ticks = $process.StartTime.ToUniversalTime().Ticks.ToString()
    $path = $process.Path
    if ($ticks -ne $entry.StartTicks -or $path -ne $entry.Executable) {
        throw "Process $($entry.Id) does not match the recorded identity; refusing to stop it."
    }
    Stop-Process -Id $entry.Id -Force
}
Remove-Item -LiteralPath $statePath -Force
Write-Output "Stopped preview services. Isolated demo database retained at: $($state.database)"
