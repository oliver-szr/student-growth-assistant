param([switch]$Reset,[switch]$OpenBrowser,[string]$AiModel)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$runtime=Join-Path $PSScriptRoot '.runtime'
$state=Join-Path $runtime 'demo-processes.json'
$dbRecord=Join-Path $runtime 'demo-database.txt'
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
$node=(Get-Command node).Source
$vite=Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
function Test-Port([int]$Port){
    $c=[System.Net.Sockets.TcpClient]::new()
    try{$c.Connect('127.0.0.1',$Port);return $true}catch{return $false}finally{$c.Dispose()}
}
if(Test-Path -LiteralPath $state){
    if($Reset){ & (Join-Path $PSScriptRoot '停止演示版.ps1') }
    else{
        $entries=@(Get-Content -LiteralPath $state -Raw | ConvertFrom-Json)
        $running=$entries.Count -eq 2
        foreach($e in $entries){$p=Get-Process -Id $e.Id -ErrorAction SilentlyContinue;if(!$p -or $p.StartTime.ToUniversalTime().Ticks.ToString() -ne $e.StartTicks -or $p.Path -ne $e.Executable){$running=$false}}
        if($running -and (Test-Port 8001) -and (Test-Port 5174)){
            Write-Output '演示版已在运行：http://localhost:5174'
            if($AiModel){Write-Output '当前实例沿用原模型；要应用新的 AiModel，请停止并重新启动，或使用 -Reset。'}
            if($OpenBrowser){Start-Process 'http://localhost:5174'}
            return
        }
        & (Join-Path $PSScriptRoot '停止演示版.ps1')
    }
}
foreach($port in @(8001,5174)){if(Test-Port $port){throw "端口 $port 被其他进程占用；此脚本不会停止未知进程。"}}
if(!$Reset -and (Test-Path -LiteralPath $dbRecord)){$database=(Get-Content -LiteralPath $dbRecord -Raw).Trim()}
else{$database=Join-Path $runtime ('demo-mvp-'+[guid]::NewGuid().ToString()+'.db')}
$argsInit=@((Join-Path $PSScriptRoot 'demo_init.py'),'--database',$database)
$source=Join-Path $PSScriptRoot '.local\基础课表.json'
if(Test-Path -LiteralPath $source){$argsInit+=@('--source',$source)}
& $python @argsInit
if($LASTEXITCODE -ne 0){throw '演示数据初始化失败。'}
$database | Set-Content -LiteralPath $dbRecord -Encoding UTF8
$saved=@{SGA_DEMO=$env:SGA_DEMO;SGA_DEMO_NOW=$env:SGA_DEMO_NOW;SGA_DATABASE_PATH=$env:SGA_DATABASE_PATH;VITE_API_BASE_URL=$env:VITE_API_BASE_URL;PYTHONIOENCODING=$env:PYTHONIOENCODING;CLAUDE_MODEL=$env:CLAUDE_MODEL}
$started=@()
try{
    $env:SGA_DEMO='1';$env:SGA_DEMO_NOW='2026-10-07T18:00:00+08:00';$env:SGA_DATABASE_PATH=$database;$env:PYTHONIOENCODING='utf-8'
    if($AiModel){$env:CLAUDE_MODEL=$AiModel}
    $back=Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port','8001') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'demo-backend.out.log') -RedirectStandardError (Join-Path $runtime 'demo-backend.err.log') -PassThru
    $started+=$back
    $env:VITE_API_BASE_URL='http://127.0.0.1:8001'
    $front=Start-Process -FilePath $node -ArgumentList @(('"{0}"' -f $vite),'--host','127.0.0.1','--port','5174','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'demo-frontend.out.log') -RedirectStandardError (Join-Path $runtime 'demo-frontend.err.log') -PassThru
    $started+=$front
    $deadline=(Get-Date).AddSeconds(30)
    while(!(Test-Port 8001) -or !(Test-Port 5174)){
        foreach($p in $started){if($p.HasExited){throw '演示进程退出，请检查 .runtime 日志。'}}
        if((Get-Date) -gt $deadline){throw '演示服务启动超时。'}
        Start-Sleep -Milliseconds 200
    }
    @($started | ForEach-Object { @{Id=$_.Id;StartTicks=$_.StartTime.ToUniversalTime().Ticks.ToString();Executable=$_.Path} }) | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
    Write-Output '演示版：http://localhost:5174；模拟时间 2026-10-07 18:00，北京时间。'
    if($AiModel){Write-Output "演示实例使用模型：$AiModel；backend/.env 未改动。"}
    if($OpenBrowser){Start-Process 'http://localhost:5174'}
}catch{foreach($p in $started){if(!$p.HasExited){$p.Kill()}};throw}
finally{foreach($name in $saved.Keys){[Environment]::SetEnvironmentVariable($name,$saved[$name],'Process')}}
