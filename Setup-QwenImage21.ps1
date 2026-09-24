[CmdletBinding()]
param(
    [switch]$SkipModels,
    [switch]$SkipTorch,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = $PSScriptRoot
$Comfy = Join-Path $Root 'ComfyUI'
$Venv = Join-Path $Comfy '.venv'
$VenvPython = Join-Path $Venv 'Scripts\\python.exe'
$ModelDir = Join-Path $Comfy 'models'

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. Install it, then run this script again."
    }
}

function Download-Model([string]$Url, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        $size = (Get-Item -LiteralPath $Destination).Length
        if ($size -gt 100MB) {
            Write-Host "Already present: $(Split-Path $Destination -Leaf)" -ForegroundColor Green
            return
        }
    }

    Write-Host "Downloading $(Split-Path $Destination -Leaf). This is resumable; re-run this script if interrupted." -ForegroundColor Cyan
    & curl.exe --fail --location --continue-at - --output $Destination $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
}

Require-Command git
Require-Command python
Require-Command curl.exe

if (-not (Test-Path -LiteralPath $Comfy)) {
    Write-Host 'Cloning current ComfyUI...' -ForegroundColor Cyan
    & git clone --depth 1 https://github.com/Comfy-Org/ComfyUI.git $Comfy
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI clone failed.' }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host 'Creating isolated Python environment...' -ForegroundColor Cyan
    Push-Location $Comfy
    try { & python -m venv .venv } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed.' }

if (-not $SkipTorch) {
    Write-Host 'Installing CUDA-enabled PyTorch for the RTX 5060...' -ForegroundColor Cyan
    & $VenvPython -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu130
    if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch install failed.' }
}

Write-Host 'Installing ComfyUI requirements...' -ForegroundColor Cyan
& $VenvPython -m pip install -r (Join-Path $Comfy 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'ComfyUI requirements install failed.' }

$GGUFNode = Join-Path $Comfy 'custom_nodes\\ComfyUI-GGUF'
if (-not (Test-Path -LiteralPath $GGUFNode)) {
    Write-Host 'Installing the Qwen Image 2.1 GGUF loader...' -ForegroundColor Cyan
    & git clone --depth 1 https://github.com/leejet/ComfyUI-GGUF.git $GGUFNode
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI-GGUF clone failed.' }
}

$GGUFRequirements = Join-Path $GGUFNode 'requirements.txt'
if (Test-Path -LiteralPath $GGUFRequirements) {
    & $VenvPython -m pip install -r $GGUFRequirements
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI-GGUF requirements install failed.' }
}

New-Item -ItemType Directory -Force -Path (Join-Path $ModelDir 'diffusion_models'), (Join-Path $ModelDir 'text_encoders'), (Join-Path $ModelDir 'vae'), (Join-Path $Root 'workflows') | Out-Null

$GGUFName = 'qwen-image-2.1-UC-Q4_K_M.gguf'
$SourceGGUF = Join-Path $Root $GGUFName
$TargetGGUF = Join-Path (Join-Path $ModelDir 'diffusion_models') $GGUFName
if ((Test-Path -LiteralPath $SourceGGUF) -and -not (Test-Path -LiteralPath $TargetGGUF)) {
    Write-Host 'Moving your existing GGUF into ComfyUI models...' -ForegroundColor Cyan
    Move-Item -LiteralPath $SourceGGUF -Destination $TargetGGUF
}
if (-not $SkipModels) {
    Download-Model 'https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF/resolve/main/qwen-image-2.1-UC-Q4_K_M.gguf' $TargetGGUF
    Download-Model 'https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors' (Join-Path (Join-Path $ModelDir 'text_encoders') 'qwen3vl_8b_int8_convrot.safetensors')
    Download-Model 'https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors' (Join-Path (Join-Path $ModelDir 'vae') 'qwen_image_2.1_vae_bf16.safetensors')
}

if (-not (Test-Path -LiteralPath $TargetGGUF)) {
    throw "Missing $GGUFName. Re-run without -SkipModels or place it in '$TargetGGUF'."
}

Write-Host 'Fetching and adapting the official Qwen Image 2.1 workflows...' -ForegroundColor Cyan
& $VenvPython (Join-Path $Root 'tools\\prepare_workflows.py') --output (Join-Path $Root 'workflows')
if ($LASTEXITCODE -ne 0) { throw 'Workflow preparation failed.' }

Write-Host ''
Write-Host 'Setup complete.' -ForegroundColor Green
Write-Host 'Start Qwenian with: .\\Launch-Qwenian.ps1'

if (-not $NoLaunch) { & (Join-Path $Root 'Launch-Qwenian.ps1') }
