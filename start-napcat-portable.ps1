$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$portableRoot = Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'data\napcat-portable\installer') -Directory -Filter 'NapCat.*.Shell' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (!$portableRoot) { throw 'Portable NapCat runtime not prepared.' }
$launcher = Join-Path $portableRoot.FullName 'NapCatWinBootMain.exe'
$process = Start-Process -FilePath $launcher -WorkingDirectory $portableRoot.FullName -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data\napcat-portable\stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data\napcat-portable\stderr.log') -PassThru
$process.Id | Set-Content (Join-Path $PSScriptRoot 'data\napcat-portable\launcher.pid')
Write-Host 'Portable NapCat started; WebUI: http://127.0.0.1:6099/webui/'
