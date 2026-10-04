param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $PSScriptRoot '.runtime'
$statePath = Join-Path $runtime 'v2-browser-check.json'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$scenarioJson = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'demo_scenario.json') -Raw
$scenario = $scenarioJson | ConvertFrom-Json
# Windows PowerShell may coerce JSON ISO timestamps into DateTime and stringify
# them using the machine's locale (for example, 2026/10/14 18:00:00). Keep the
# configured value as its original ISO-8601 string for Python's fromisoformat.
$demoNowMatch = [regex]::Match($scenarioJson, '"now"\s*:\s*"([^"]+)"')
if (!$demoNowMatch.Success) { throw 'demo_scenario.json must define an ISO-8601 now value.' }
$demoNow = $demoNowMatch.Groups[1].Value
$demoWeekMatch = [regex]::Match($scenarioJson, '"week_start"\s*:\s*"([^"]+)"')
if (!$demoWeekMatch.Success) { throw 'demo_scenario.json must define week_start.' }
$demoWeek = $demoWeekMatch.Groups[1].Value
$node = (Get-Command node).Source
$vite = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$backendPort = 8002
$frontendPort = 5175
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

function Test-Port([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try { $client.Connect('127.0.0.1', $Port); return $true }
    catch { return $false }
    finally { $client.Dispose() }
}

function Test-DemoApi([string]$ExpectedNow, [string]$ExpectedWeek) {
    try {
        $settings = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/assistant/settings" -TimeoutSec 1
        return $settings.demo -and $settings.now -eq $ExpectedNow -and $settings.week_start -eq $ExpectedWeek
    } catch { return $false }
}

if (Test-Path -LiteralPath $statePath) { throw 'V2 browser-check instance already recorded; run the stop script first.' }
foreach ($port in @($backendPort, $frontendPort)) { if (Test-Port $port) { throw "Port $port is occupied; no unknown process will be stopped." } }

$database = Join-Path $runtime ("demo-v2-browser-{0}.db" -f [guid]::NewGuid().ToString('N'))
& $python (Join-Path $PSScriptRoot 'demo_init.py') --database $database
if ($LASTEXITCODE -ne 0) { throw 'Isolated demo database initialization failed.' }

$saved = @{
    SGA_DEMO = $env:SGA_DEMO
    SGA_DEMO_NOW = $env:SGA_DEMO_NOW
    SGA_DATABASE_PATH = $env:SGA_DATABASE_PATH
    VITE_API_BASE_URL = $env:VITE_API_BASE_URL
    PYTHONIOENCODING = $env:PYTHONIOENCODING
}
$started = @()
try {
    $env:SGA_DEMO = '1'
    $env:SGA_DEMO_NOW = $demoNow
    $env:SGA_DATABASE_PATH = $database
    $env:PYTHONIOENCODING = 'utf-8'
    $backend = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port',"$backendPort") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'v2-browser-backend.out.log') -RedirectStandardError (Join-Path $runtime 'v2-browser-backend.err.log') -PassThru
    $started += $backend
    $env:VITE_API_BASE_URL = "http://127.0.0.1:$backendPort"
    $frontend = Start-Process -FilePath $node -ArgumentList @(('"{0}"' -f $vite),'--host','127.0.0.1','--port',"$frontendPort",'--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'v2-browser-frontend.out.log') -RedirectStandardError (Join-Path $runtime 'v2-browser-frontend.err.log') -PassThru
    $started += $frontend
    $deadline = (Get-Date).AddSeconds(35)
    while (!(Test-Port $backendPort) -or !(Test-Port $frontendPort) -or !(Test-DemoApi $demoNow $demoWeek)) {
        foreach ($process in $started) { if ($process.HasExited) { throw 'A preview process exited; inspect .runtime/v2-browser-*.log.' } }
        if ((Get-Date) -gt $deadline) { throw 'Local preview startup timed out.' }
        Start-Sleep -Milliseconds 250
    }
    $state = @($started | ForEach-Object { @{ Id = $_.Id; StartTicks = $_.StartTime.ToUniversalTime().Ticks.ToString(); Executable = $_.Path } })
    @{ processes = $state; database = $database; backendPort = $backendPort; frontendPort = $frontendPort } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-Output "Isolated preview: http://localhost:$frontendPort; backend port $backendPort; database: $database"
}
catch {
    foreach ($process in $started) { if (!$process.HasExited) { Stop-Process -Id $process.Id -Force } }
    throw
}
finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
