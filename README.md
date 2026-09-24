# Qwenian

Qwenian is a polished local image-generation app for Qwen Image 2.1. It wraps ComfyUI in a focused browser interface for image creation, UI mockups, graphics, product imagery, illustration, reference editing, and design matching.

Everything runs on your machine. The web server binds to `127.0.0.1`, images remain local, and ComfyUI handles inference in the background.

## Features

- Seven creation modes: Image, UI / Web, Graphics, Product, Illustration, Edit, and Design Match
- Batches of 1–8 seeded variations with live progress and scoped cancellation
- Up to ten ordered reference images with aligned edit sizing
- Draft, Balanced, and Detailed quality presets plus advanced step and guidance controls
- Standard, Large, and High resolutions with five aspect ratios
- Style, palette, exact-text, transparency, and optional anatomy guidance
- Persistent jobs across page reloads, reusable settings, and reference-based follow-up edits
- Clearable generation history; prompt drafts are not retained in browser storage
- Individual PNG downloads, clipboard copy, and batch ZIP downloads
- Responsive desktop and mobile interface
- Model-stage caching between compatible variations

## Requirements

The included setup is currently designed for Windows and NVIDIA GPUs.

- Windows 10 or 11
- PowerShell 5.1 or newer
- Git, Python, and `curl.exe` available on `PATH`
- NVIDIA GPU with current drivers; 8 GB VRAM is the tested minimum
- Around 25 GB of free disk space for ComfyUI, Python packages, and model weights
- 16 GB system RAM minimum; 32 GB recommended

Qwenian was developed and tested on an RTX 5060 Laptop GPU with 8 GB VRAM. Larger resolutions need more time and may exceed the available memory on smaller GPUs.

## Quick setup

```powershell
git clone https://github.com/Wyrmstooth/qwenian.git
cd qwenian
Set-ExecutionPolicy -Scope Process Bypass
.\Setup-Qwenian.ps1
```

The installer clones ComfyUI, creates `ComfyUI/.venv/`, installs CUDA PyTorch and dependencies, installs ComfyUI-GGUF, downloads all three model files with resume support, and adapts the official workflows. It starts Qwenian unless `-NoLaunch` is supplied.

The initial setup downloads roughly 14.6 GB of model weights and can take a while.

## Start Qwenian

```powershell
.\Launch-Qwenian.ps1
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860). The launcher starts ComfyUI automatically when port `8188` is not already active.

```powershell
# Start without opening a browser
.\Launch-Qwenian.ps1 -NoBrowser

# Run the ComfyUI engine directly with intermediate previews
.\Launch-QwenImage21.ps1 -Previews

# Try normal-VRAM mode instead of the tested low-VRAM default
.\Launch-QwenImage21.ps1 -NormalVram
```

Intermediate previews are disabled by default to avoid spending GPU time on frames that are not saved. This does not change final-image quality.

## Model downloads

The setup script downloads these files automatically:

| Component | File | Approx. size | Destination | Source |
| --- | --- | ---: | --- | --- |
| Diffusion model | `qwen-image-2.1-UC-Q4_K_M.gguf` | 4.29 GiB | `ComfyUI/models/diffusion_models/` | [Hugging Face](https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF/resolve/main/qwen-image-2.1-UC-Q4_K_M.gguf) |
| Text/vision encoder | `qwen3vl_8b_int8_convrot.safetensors` | 8.71 GiB | `ComfyUI/models/text_encoders/` | [Hugging Face](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors) |
| VAE | `qwen_image_2.1_vae_bf16.safetensors` | 644 MiB | `ComfyUI/models/vae/` | [Hugging Face](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors) |

Related upstream projects:

- [Qwen Image 2.1](https://github.com/QwenLM/Qwen-Image-2.1)
- [Official compatible ComfyUI models](https://huggingface.co/Comfy-Org/Qwen-Image-2.1)
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)
- [ComfyUI-GGUF](https://github.com/leejet/ComfyUI-GGUF)
- [Official workflow templates](https://github.com/Comfy-Org/workflow_templates/tree/main/templates)

For a manual model installation, put the files in the destinations above and run:

```powershell
.\Setup-Qwenian.ps1 -SkipModels
```

## Using Qwenian

Choose the mode closest to the desired output, write a focused brief, and select the number of variations. Balanced uses the 40-step quality baseline and is the recommended default. Draft uses fewer steps for exploration. Detailed adds sampling time and does not guarantee a better result for every seed.

For reference edits, upload the edit target as image 1. Additional references are numbered left to right. Refer to them explicitly, for example: `Keep the person from image 1 and use the jacket from image 2.` Leave **Match image 1’s proportions** enabled when preserving composition.

For text, put required copy in **Exact text**, keep it short, and describe its position and hierarchy. Image models can still misspell small or dense text, so review lettering before using an output.

No diffusion model can guarantee perfect anatomy, text, or geometry on every seed. Purpose-specific guidance and the anatomy option reduce common failures; generating several variations and reviewing the result remains useful.

## Updating

```powershell
git pull --ff-only
.\Update-Qwenian.ps1
```

This updates ComfyUI, its dependencies, ComfyUI-GGUF, and the bundled workflow JSON files. It does not overwrite Qwenian job history or generated images.

## Tests

Backend and workflow tests do not use the GPU:

```powershell
.\ComfyUI\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The browser test uses installed Chrome and a fake inference engine:

```powershell
.\ComfyUI\.venv\Scripts\python.exe -m pip install playwright
.\ComfyUI\.venv\Scripts\python.exe tests\browser_check.py
```

The opt-in smoke test creates a real image and can take several minutes:

```powershell
.\ComfyUI\.venv\Scripts\python.exe tools\smoke_generation.py --run
```

## Project layout

```text
static/                 Browser interface
tests/                  Unit, integration, and browser tests
tools/                  Workflow preparation and smoke-test utilities
workflows/              Adapted official ComfyUI workflows
studio.py               HTTP API, persistence, uploads, and engine bridge
studio_core.py          Validation, prompt composition, sizing, and workflow graph
Setup-Qwenian.ps1       User-facing installer
Launch-Qwenian.ps1      User-facing launcher
Update-Qwenian.ps1      User-facing updater
```

Runtime state is stored in `.studio/`; references and outputs live under `ComfyUI/`. These directories, model files, and generated media are intentionally excluded from Git.

**Clear history** removes completed, cancelled, and failed job records from Qwenian while keeping active jobs and generated image files. Qwenian remembers non-prompt UI preferences locally, but it does not restore or retain the last prompt in browser storage.

## Security and privacy

Qwenian and ComfyUI listen on loopback only by default. Do not expose them publicly without authentication and a review of upload and proxy behavior. Uploaded references are normalized before inference, file paths are constrained to expected directories, and cancellation targets only Qwenian-owned prompt IDs.

## Licenses and responsible use

Qwenian depends on independently licensed third-party software and model weights. Review the licenses and terms on the linked Qwen, ComfyUI, ComfyUI-GGUF, and Hugging Face repositories before redistribution or commercial use. Generated content remains your responsibility; respect consent, privacy, intellectual property, and applicable law.
