[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Comfy = Join-Path $Root 'ComfyUI'
$Python = Join-Path $Comfy '.venv\\Scripts\\python.exe'
$GGUFNode = Join-Path $Comfy 'custom_nodes\\ComfyUI-GGUF'

if (-not (Test-Path -LiteralPath $Python)) { throw 'Run .\\Setup-QwenImage21.ps1 first.' }

Push-Location $Comfy
try {
    & git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI update failed.' }
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI requirements update failed.' }
} finally { Pop-Location }

Push-Location $GGUFNode
try {
    & git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI-GGUF update failed.' }
    if (Test-Path -LiteralPath 'requirements.txt') { & $Python -m pip install -r requirements.txt }
} finally { Pop-Location }

& $Python (Join-Path $Root 'tools\\prepare_workflows.py') --output (Join-Path $Root 'workflows')
if ($LASTEXITCODE -ne 0) { throw 'Workflow update failed.' }
Write-Host 'Update complete.' -ForegroundColor Green
