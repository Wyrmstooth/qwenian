[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 8188,
    [switch]$NormalVram,
    [switch]$Previews,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Comfy = Join-Path $Root 'ComfyUI'
$Python = Join-Path $Comfy '.venv\\Scripts\\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'ComfyUI is not installed yet. Run .\\Setup-QwenImage21.ps1 first.'
}

$PreviewMethod = if ($Previews) { 'auto' } else { 'none' }
$Arguments = @('main.py', '--listen', '127.0.0.1', '--port', $Port, '--preview-method', $PreviewMethod)
if (-not $NormalVram) { $Arguments += '--lowvram' }

Write-Host "Starting Qwen Image 2.1 at http://127.0.0.1:$Port" -ForegroundColor Green
if (-not $NormalVram) { Write-Host 'Low-VRAM mode is enabled for the 8 GB GPU.' -ForegroundColor Yellow }
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }

Push-Location $Comfy
try { & $Python @Arguments } finally { Pop-Location }
