$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $scriptPath = Join-Path $PSScriptRoot 'start-napcat.ps1'
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $scriptPath + '"')) -Verb RunAs -WindowStyle Hidden
    Write-Host 'Administrator launch requested. Complete the Windows UAC prompt if shown.'
    exit
}
$napcatRoot = Join-Path $PSScriptRoot 'data\napcat\package'
$qqExecutable = 'C:\Program Files\Tencent\QQNT\QQ.exe'
$versionedQQ = Get-ChildItem -LiteralPath 'C:\Program Files\Tencent\QQNT\versions' -Filter 'QQ.exe' -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($versionedQQ) { $qqExecutable = $versionedQQ.FullName }
if (!(Test-Path -LiteralPath $qqExecutable)) { throw 'QQNT executable not found. Install QQ first.' }
$launcher = Join-Path $napcatRoot 'NapCatWinBootMain.exe'
if (!(Test-Path -LiteralPath $launcher)) { throw 'Run python -m scripts.setup_napcat first.' }
$env:NAPCAT_PATCH_PACKAGE = Join-Path $napcatRoot 'qqnt.json'
$env:NAPCAT_LOAD_PATH = Join-Path $napcatRoot 'loadNapCat.js'
$env:NAPCAT_INJECT_PATH = Join-Path $napcatRoot 'NapCatWinBootHook.dll'
$env:NAPCAT_LAUNCHER_PATH = $launcher
$env:NAPCAT_MAIN_PATH = Join-Path $napcatRoot 'napcat.mjs'
$arguments = @(('"' + $qqExecutable + '"'), ('"' + $env:NAPCAT_INJECT_PATH + '"'))
$process = Start-Process -FilePath $launcher -ArgumentList $arguments -WorkingDirectory $napcatRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data\napcat\stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data\napcat\stderr.log') -PassThru
$process.Id | Set-Content (Join-Path $PSScriptRoot 'data\napcat\launcher.pid')
Write-Host 'NapCat started. Login at http://127.0.0.1:6099/webui/ ; credentials remain in local config.'
