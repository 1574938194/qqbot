$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv\Scripts\python.exe')) { throw '请先运行 install.ps1。' }
& '.venv\Scripts\python.exe' bot.py
exit $LASTEXITCODE
