param([int]$Port=8002)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtime=Join-Path $PSScriptRoot '.runtime'
$evidence=Join-Path $PSScriptRoot 'evidence'
New-Item -ItemType Directory -Path $runtime,$evidence -Force | Out-Null
$connection=[System.Net.Sockets.TcpClient]::new()
try{$connection.Connect('127.0.0.1',$Port);throw "测试端口 $Port 已被占用，不停止其他服务。"}
catch [System.Net.Sockets.SocketException]{}
finally{$connection.Dispose()}
$database=Join-Path $runtime ('demo-deepseek-test-'+[guid]::NewGuid().ToString()+'.db')
$scenarioJson=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'demo_scenario.json') -Raw
$demoNowMatch=[regex]::Match($scenarioJson,'"now"\s*:\s*"([^"]+)"')
if(!$demoNowMatch.Success){throw 'demo_scenario.json 必须包含 ISO-8601 格式的 now。'}
$demoNow=$demoNowMatch.Groups[1].Value
$initArgs=@((Join-Path $PSScriptRoot 'demo_init.py'),'--database',$database)
& $python @initArgs
if($LASTEXITCODE -ne 0){throw '测试数据初始化失败。'}
$saved=@{SGA_DEMO=$env:SGA_DEMO;SGA_DEMO_NOW=$env:SGA_DEMO_NOW;SGA_DATABASE_PATH=$env:SGA_DATABASE_PATH;PYTHONIOENCODING=$env:PYTHONIOENCODING}
$server=$null;$testExit=1
try{
    $env:SGA_DEMO='1';$env:SGA_DEMO_NOW=$demoNow;$env:SGA_DATABASE_PATH=$database;$env:PYTHONIOENCODING='utf-8'
    $server=Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'deepseek-test.out.log') -RedirectStandardError (Join-Path $runtime 'deepseek-test.err.log') -PassThru
    $deadline=(Get-Date).AddSeconds(30)
    while($true){
        if($server.HasExited){throw '测试服务启动失败，请查看 .runtime 日志。'}
        try{$ready=Invoke-RestMethod "http://127.0.0.1:$Port/api/assistant/settings" -TimeoutSec 1;if($ready.demo){break}}catch{}
        if((Get-Date) -gt $deadline){throw '测试服务启动超时。'}
        Start-Sleep -Milliseconds 200
    }
    & $python (Join-Path $PSScriptRoot 'live_ai_acceptance.py') --api-url "http://127.0.0.1:$Port" --output-tag deepseek-openai | Tee-Object -FilePath (Join-Path $evidence 'deepseek-openai-live.log')
    $testExit=$LASTEXITCODE
}finally{
    if($server -and !$server.HasExited){$server.Kill();$server.WaitForExit(5000) | Out-Null}
    foreach($name in $saved.Keys){[Environment]::SetEnvironmentVariable($name,$saved[$name],'Process')}
}
exit $testExit
