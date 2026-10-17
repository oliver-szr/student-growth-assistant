$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $PSScriptRoot '.runtime\demo-processes.json'
if (!(Test-Path -LiteralPath $stateFile)) { Write-Output '没有此启动脚本记录的运行服务。'; return }
$entries = @(Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json)
foreach ($entry in $entries) {
    $process = Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $entry.StartTicks -and $process.Path -eq $entry.Executable) {
        Stop-Process -Id $entry.Id
    }
}
Remove-Item -LiteralPath $stateFile
Write-Output '已停止演示启动脚本记录的服务。'
