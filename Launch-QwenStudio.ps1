[CmdletBinding()]
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Python = Join-Path $Root 'ComfyUI\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run .\Setup-QwenImage21.ps1 first.' }

if (-not (Test-NetConnection 127.0.0.1 -Port 8188 -InformationLevel Quiet)) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Root 'Launch-QwenImage21.ps1'), '-NoBrowser' -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:7860' }
Write-Host 'Qwenian is running at http://127.0.0.1:7860' -ForegroundColor Green
& $Python (Join-Path $Root 'studio.py')
