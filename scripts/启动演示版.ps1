param([switch]$Reset,[switch]$OpenBrowser,[switch]$MockIntegration,[string]$AiModel,[string]$CourseSource,[int]$BackendPort=8001,[int]$FrontendPort=5174)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$runtime=Join-Path $PSScriptRoot '.runtime'
$state=Join-Path $runtime 'demo-processes.json'
$dbRecord=Join-Path $runtime 'demo-database.txt'
$node=(Get-Command node -ErrorAction Stop).Source
$vite=Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
if (!(Test-Path -LiteralPath $vite)) { throw '请先运行 npm --prefix frontend ci。' }
# Resolve only the existing app_env, including its activated PATH.
Get-Command conda -ErrorAction Stop | Out-Null
$runtimeText=& conda run -n app_env python -c 'import json,os,sys; print(json.dumps(dict(python=sys.executable,path=os.pathsep.join(os.get_exec_path()),prefix=sys.prefix,name=os.path.basename(sys.prefix))))'
if ($LASTEXITCODE -ne 0) { throw '无法使用已有 Conda app_env；请检查 conda env list。' }
$pythonRuntime=($runtimeText -join "`n").Trim() | ConvertFrom-Json
if ($pythonRuntime.name -ne 'app_env' -or !(Test-Path -LiteralPath $pythonRuntime.python)) { throw '必须使用已有 app_env。' }
$python=$pythonRuntime.python
$scenarioJson=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'demo_scenario.json') -Encoding UTF8 -Raw
# Preserve ISO strings in Windows PowerShell 5.1 and PowerShell 7.
$demoNowMatch=[regex]::Match($scenarioJson,'"now"\s*:\s*"([^"]+)"')
$demoWeekMatch=[regex]::Match($scenarioJson,'"week_start"\s*:\s*"([^"]+)"')
if (!$demoNowMatch.Success -or !$demoWeekMatch.Success) { throw '演示场景缺少 now 或 week_start。' }
$demoNow=$demoNowMatch.Groups[1].Value
$demoWeek=$demoWeekMatch.Groups[1].Value
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
function Test-Port([int]$Port) {
    $connection=[System.Net.Sockets.TcpClient]::new()
    try { $connection.Connect('127.0.0.1',$Port); return $true }
    catch { return $false }
    finally { $connection.Dispose() }
}
function Test-DemoApi {
    try {
        $health=Invoke-WebRequest "http://127.0.0.1:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 1
        $isMock=$health.Headers['X-SGA-Integration-Mock'] -eq '1'
        if ([bool]$isMock -ne [bool]$MockIntegration) { return $false }
        $settings=Invoke-RestMethod "http://127.0.0.1:$BackendPort/api/assistant/settings" -TimeoutSec 1
        return $settings.demo -and $settings.now -eq $demoNow -and $settings.week_start -eq $demoWeek
    } catch { return $false }
}
if (Test-Path -LiteralPath $state) {
    $entries=@(Get-Content -LiteralPath $state -Encoding UTF8 -Raw | ConvertFrom-Json)
    $running=$entries.Count -eq 2
    foreach ($entry in $entries) {
        $process=Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
        if (!$process -or $process.StartTime.ToUniversalTime().Ticks.ToString() -ne $entry.StartTicks -or $process.Path -ne $entry.Executable) { $running=$false }
    }
    if (!$Reset -and !$MockIntegration -and $running -and (Test-Port $FrontendPort) -and (Test-DemoApi)) {
        Write-Output "演示版已在运行：http://127.0.0.1:$FrontendPort"
        if ($OpenBrowser) { Start-Process "http://127.0.0.1:$FrontendPort" }
        return
    }
    & (Join-Path $PSScriptRoot '停止演示版.ps1')
}
foreach ($port in @($BackendPort,$FrontendPort)) {
    if (Test-Port $port) { throw "端口 $port 已被占用；不会停止未知进程。" }
}
if (!$Reset -and !$MockIntegration -and (Test-Path -LiteralPath $dbRecord)) { $database=(Get-Content -LiteralPath $dbRecord -Encoding UTF8 -Raw).Trim() }
else { $database=Join-Path $runtime ('demo-'+[guid]::NewGuid().ToString('N')+'.db') }
$argsInit=@((Join-Path $PSScriptRoot 'demo_init.py'),'--database',$database)
if ($CourseSource) { $argsInit+=@('--source',(Resolve-Path -LiteralPath $CourseSource).Path) }
$saved=@{}
foreach ($name in @('PATH','CONDA_PREFIX','CONDA_DEFAULT_ENV','SGA_DEMO','SGA_DEMO_NOW','SGA_DATABASE_PATH','SGA_AUTO_BACKUP','SGA_BACKUP_DIR','VITE_API_BASE_URL','PYTHONIOENCODING','CLAUDE_MODEL','OPENAI_MODEL')) { $saved[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }
$started=@()
try {
    $env:PATH=$pythonRuntime.path
    $env:CONDA_PREFIX=$pythonRuntime.prefix
    $env:CONDA_DEFAULT_ENV='app_env'
    $env:SGA_DEMO='1'
    $env:SGA_DEMO_NOW=$demoNow
    $env:SGA_DATABASE_PATH=$database
    $env:SGA_AUTO_BACKUP='0'
    $env:SGA_BACKUP_DIR=Join-Path $runtime 'backups'
    $env:PYTHONIOENCODING='utf-8'
    if ($AiModel) { $env:CLAUDE_MODEL=$AiModel; $env:OPENAI_MODEL=$AiModel }
    if ($MockIntegration) {
        # integration_demo owns a fresh UUID database and blocks live AI.
        $backendArgs=@('scripts/integration_demo.py','--serve','--port',"$BackendPort")
    } else {
        & $python @argsInit
        if ($LASTEXITCODE -ne 0) { throw '演示数据初始化失败，未启动服务。' }
        $database | Set-Content -LiteralPath $dbRecord -Encoding UTF8
        $backendArgs=@('-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port',"$BackendPort")
    }
    $back=Start-Process -FilePath $python -ArgumentList $backendArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'demo-backend.out.log') -RedirectStandardError (Join-Path $runtime 'demo-backend.err.log') -PassThru
    $started+=$back
    $env:VITE_API_BASE_URL="http://127.0.0.1:$BackendPort"
    $front=Start-Process -FilePath $node -ArgumentList @(('"{0}"' -f $vite),'--host','127.0.0.1','--port',"$FrontendPort",'--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'demo-frontend.out.log') -RedirectStandardError (Join-Path $runtime 'demo-frontend.err.log') -PassThru
    $started+=$front
    $deadline=(Get-Date).AddSeconds(40)
    while (!(Test-Port $FrontendPort) -or !(Test-DemoApi)) {
        foreach ($process in $started) { if ($process.HasExited) { throw '演示服务退出，请检查 scripts/.runtime 中的日志。' } }
        if ((Get-Date) -gt $deadline) { throw '演示服务启动超时。' }
        Start-Sleep -Milliseconds 200
    }
    @($started | ForEach-Object { @{Id=$_.Id; StartTicks=$_.StartTime.ToUniversalTime().Ticks.ToString(); Executable=$_.Path} }) | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
    Write-Output "演示版：http://127.0.0.1:$FrontendPort；API：http://127.0.0.1:$BackendPort；app_env；北京时间 $demoNow。"
    if ($OpenBrowser) { Start-Process "http://127.0.0.1:$FrontendPort" }
} catch {
    foreach ($process in $started) { if (!$process.HasExited) { $process.Kill() } }
    throw
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
}
