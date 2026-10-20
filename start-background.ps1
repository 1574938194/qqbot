$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run install.ps1 first.' }
New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot 'data') | Out-Null
$pidFile = Join-Path $PSScriptRoot 'data\bot.pid'
if (Test-Path -LiteralPath $pidFile) {
    $previousId = 0
    if ([int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$previousId)) {
        $previous = Get-CimInstance Win32_Process -Filter "ProcessId=$previousId" -ErrorAction SilentlyContinue
        if ($previous -and $previous.CommandLine -match 'bot\.py') {
            throw ('Bot process ' + $previousId + ' is already running. Stop that instance before starting again.')
        }
    }
}
$process = Start-Process -FilePath $python -ArgumentList @('-u', 'bot.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data\bot.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data\bot.stderr.log') -PassThru
Start-Sleep -Seconds 2
if ($process.HasExited) { throw 'Bot failed to start; check data/bot.stderr.log and data/bot.stdout.log.' }
$process.Id | Set-Content -LiteralPath $pidFile
Write-Host ('Bot started in background, process ' + $process.Id + '.')
