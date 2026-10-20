$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw 'Python 命令失败，请检查上方输出。' } }
if (!(Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    Check-Exit
}
& '.venv\Scripts\python.exe' -m pip install -e '.[dev]'
Check-Exit
if (!(Test-Path '.env')) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $token = [BitConverter]::ToString($bytes).Replace('-', '')
    $content = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '.env.example')).Replace('replace-with-random-token', $token)
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env'), $content, (New-Object Text.UTF8Encoding $false))
}
Write-Host '安装完成。请将 .env 的 ONEBOT_ACCESS_TOKEN 填入 NapCat，然后运行 start.ps1。'
