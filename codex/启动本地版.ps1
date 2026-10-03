param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $PSScriptRoot '.runtime'
$stateFile = Join-Path $runtimeDir 'local-processes.json'
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$nodeExe = (Get-Command node -ErrorAction Stop).Source
$viteFile = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
if (!(Test-Path -LiteralPath $pythonExe) -or !(Test-Path -LiteralPath $viteFile)) {
    throw '缺少项目依赖，请先按本地使用说明安装。'
}
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Test-Port([int]$Port) {
    $connection = [System.Net.Sockets.TcpClient]::new()
    try { $connection.Connect('127.0.0.1', $Port); return $true }
    catch { return $false }
    finally { $connection.Dispose() }
}

if (Test-Path -LiteralPath $stateFile) {
    $entries = @(Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json)
    $allRunning = $entries.Count -eq 2
    foreach ($entry in $entries) {
        $process = Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
        if (!$process -or $process.StartTime.ToUniversalTime().Ticks.ToString() -ne $entry.StartTicks -or $process.Path -ne $entry.Executable) { $allRunning = $false }
    }
    if ($allRunning -and (Test-Port 8000) -and (Test-Port 5173)) {
        Write-Output '本地服务已在运行：http://localhost:5173'
        if ($OpenBrowser) { Start-Process 'http://localhost:5173' }
        return
    }
    & (Join-Path $PSScriptRoot '停止本地版.ps1')
}
foreach ($port in @(8000, 5173)) {
    if (Test-Port $port) { throw "端口 $port 已被其他服务占用，请先处理占用。此脚本不会停止其他服务。" }
}

$started = @()
$previousApiBase = $env:VITE_API_BASE_URL
try {
    $backendProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'backend.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'backend.stderr.log') -PassThru
    $started += $backendProcess
    $env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
    $frontendProcess = Start-Process -FilePath $nodeExe -ArgumentList @(('"{0}"' -f $viteFile), '--host', '127.0.0.1') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.stderr.log') -PassThru
    $started += $frontendProcess
    $deadline = (Get-Date).AddSeconds(30)
    while (!(Test-Port 8000) -or !(Test-Port 5173)) {
        foreach ($process in $started) {
            if ($process.HasExited) { throw '服务启动失败，请查看 codex/.runtime 中的日志。' }
        }
        if ((Get-Date) -gt $deadline) { throw '服务启动超时，请查看 codex/.runtime 中的日志。' }
        Start-Sleep -Milliseconds 200
    }
    $records = @($started | ForEach-Object { @{ Id = $_.Id; StartTicks = $_.StartTime.ToUniversalTime().Ticks.ToString(); Executable = $_.Path } })
    $records | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
    Write-Output '已启动：前端 http://localhost:5173；后端 http://127.0.0.1:8000'
    if ($OpenBrowser) { Start-Process 'http://localhost:5173' }
} catch {
    foreach ($process in $started) { if (!$process.HasExited) { $process.Kill() } }
    throw
} finally {
    $env:VITE_API_BASE_URL = $previousApiBase
}
