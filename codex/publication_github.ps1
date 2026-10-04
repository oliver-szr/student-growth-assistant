param([Parameter(Mandatory=$true)][string[]]$GithubArgs)
$ErrorActionPreference = 'Stop'
$ghCommand = Get-Command gh -ErrorAction SilentlyContinue
$gh = if ($ghCommand) { $ghCommand.Source } else { Join-Path $PSScriptRoot '.local/publication/gh/bin/gh.exe' }
if (!(Test-Path -LiteralPath $gh)) { throw '请先安装 GitHub 官方 CLI。' }
$savedToken = $env:GH_TOKEN
$savedPrompt = $env:GIT_TERMINAL_PROMPT
$savedInteractive = $env:GCM_INTERACTIVE
try {
    if (!$env:GH_TOKEN) {
        $tokenResult = & $gh auth token 2>$null
        if ($LASTEXITCODE -eq 0 -and $tokenResult) { $env:GH_TOKEN = ($tokenResult -join '').Trim() }
        else {
            $env:GIT_TERMINAL_PROMPT = '0'; $env:GCM_INTERACTIVE = 'never'
            $credentialLines = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null
            if ($LASTEXITCODE -ne 0) { throw '没有可用的 GitHub 登录，请先运行 gh auth login。' }
            foreach ($line in $credentialLines) {
                if ($line.StartsWith('password=')) { $env:GH_TOKEN = $line.Substring(9) }
            }
        }
    }
    if (!$env:GH_TOKEN) { throw 'GitHub 凭据不可用，请先运行 gh auth login。' }
    $login = (& $gh api user --jq .login) -join ''
    if ($LASTEXITCODE -ne 0 -or $login.Trim() -ne 'szt1107') { throw '发布账号校验失败；必须登录 szt1107。' }
    & $gh @GithubArgs
    if ($LASTEXITCODE -ne 0) { throw "GitHub 命令失败（退出码 $LASTEXITCODE）。" }
} finally {
    $env:GH_TOKEN = $savedToken
    $env:GIT_TERMINAL_PROMPT = $savedPrompt
    $env:GCM_INTERACTIVE = $savedInteractive
}
