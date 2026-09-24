# AGENTS.md

This file gives coding agents the repository-specific context needed to change Qwenian safely.

## Product intent

Qwenian is a local-first browser UI for Qwen Image 2.1. ComfyUI runs at `127.0.0.1:8188`; Qwenian runs at `127.0.0.1:7860`. The tested target is an NVIDIA RTX 5060 Laptop GPU with 8 GB VRAM.

Preserve these principles:

- Keep generation local by default.
- Present a simple creative workflow instead of ComfyUI node concepts.
- Make long work visible, cancellable, and recoverable after reloads.
- Do not promise perfect anatomy, spelling, geometry, or composition.
- Keep 40 steps, CFG 1, Euler/simple as the quality default unless verified evidence supports a change.
- Queue variations as separate images so an 8 GB GPU never needs a large latent batch.

## Repository map

- `studio.py`: aiohttp app, persistent batches, ComfyUI HTTP/WebSocket integration, upload normalization, secure file serving, cancellation, and ZIP exports.
- `studio_core.py`: validation, mode prompts, sizing, and ComfyUI workflow construction.
- `static/index.html`: application markup.
- `static/studio.css`: responsive styles. It is compact; avoid reformatting unrelated CSS.
- `static/studio.js`: browser state, forms, polling, gallery, downloads, and reference reuse.
- `tests/test_studio.py`: unit and integration tests with an isolated fake ComfyUI engine.
- `tests/browser_check.py`: browser workflow against temporary servers and a fake engine.
- `tools/prepare_workflows.py`: downloads official workflows and adapts loaders to GGUF.
- `tools/smoke_generation.py`: opt-in real-GPU test. Never run it implicitly.
- `Setup-QwenImage21.ps1`, `Launch-QwenImage21.ps1`, `Update-QwenImage21.ps1`: engine-level compatibility and troubleshooting scripts.
- `Setup-Qwenian.ps1`, `Launch-Qwenian.ps1`, `Update-Qwenian.ps1`: user-facing entry points.

`ComfyUI/`, `.studio/`, weights, uploads, generated images, caches, and virtual environments are local runtime data. Never commit them.

## Architecture and invariants

### Generation flow

1. The browser submits multipart data to `POST /api/generate`.
2. `settings_from()` validates every client-controlled setting.
3. References are decoded, orientation-corrected, bounded, normalized to PNG, and deduplicated by hash.
4. A batch is persisted before prompt submission.
5. Every variation gets a consecutive seed and explicit UUID before submission.
6. ComfyUI executes one prompt per variation and caches compatible nodes.
7. WebSocket events provide live progress; polling reconciles queue and history state.
8. State is written atomically to `.studio/jobs/` and restored after reload or restart.

Do not replace per-image jobs with `batch_size > 1` without proving 8 GB memory safety and retaining per-result seeds, progress, cancellation, and partial-failure recovery.

### Reference sizing

`TextEncodeQwenImage21` treats `resolution` as an area-based pixel budget and emits a latent matched to image 1. With `match_size` enabled, sampling must use node 5 output 2. An independently sized empty latent can shift or distort edits. Keep dimensions on multiples of 32 and preserve the aspect ratio.

References are limited to 20 MB, 32 megapixels, and a 1:4–4:1 aspect ratio. Changing these limits requires a security and GPU-memory review.

### Prompt behavior

Mode guidance must be relevant. Never add human anatomy instructions automatically to UI, graphics, products, or abstract images. Anatomy guidance is explicit and optional. User text stays first and takes priority.

Negative prompts require CFG above 1, which adds computation. Preserve the validation and UI explanation.

### Job safety

- Assign prompt UUIDs before POSTing so lost responses can be reconciled without duplicates.
- Preserve `submitting` and `checking`; queue snapshots can race submission and completion.
- Cancel through the prompt-ID-scoped endpoint. Never globally interrupt ComfyUI.
- Keep completed images when another variation fails.
- Persist every meaningful transition.
- Return active jobs even when history passes the normal display limit.

### File safety

- Resolve outputs against the configured output root.
- Check expected prefixes and extensions before serving or archiving files.
- Saved references must be content hashes ending in `.png`.
- Never trust client paths, filenames, MIME types, prompt IDs, enums, or numeric bounds.
- Keep same-origin checks on mutating routes.

## Development workflow

The workspace may have active Qwenian and ComfyUI processes. Static files update live. Python changes need a Qwenian restart; engine flags need a ComfyUI restart.

Do not restart either service without explicit user authorization. A user request to run, launch, or restart the app grants authorization for the applicable service.

Use `apply_patch` for hand edits, preserve unrelated work, and never delete outputs, job history, references, weights, or the local ComfyUI installation as cleanup.

## Validation

For Python or workflow changes:

```powershell
.\ComfyUI\.venv\Scripts\python.exe -m py_compile studio.py studio_core.py
.\ComfyUI\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For browser JavaScript changes:

```powershell
node --check static\studio.js
```

For UI behavior or layout changes, run when Playwright is available:

```powershell
.\ComfyUI\.venv\Scripts\python.exe tests\browser_check.py
```

The browser suite must remain GPU-independent. Only run the real generation smoke test with explicit authorization because it uses the GPU and writes an output:

```powershell
.\ComfyUI\.venv\Scripts\python.exe tools\smoke_generation.py --run
```

After launching, verify `/api/health` on port 7860 and `/system_stats` on port 8188.

Update or add tests when changing validation, workflow connections, model names, reference sizing, submission/recovery/cancellation, persistence, partial failures, upload safety, downloads, reuse, or reload recovery. Avoid tests for cosmetic wording or reversible CSS unless they protect accessibility or responsive behavior.

## UI conventions

- Use “Qwenian” for the app and “Qwen Image 2.1” for the model.
- Preserve keyboard access, labels, visible focus, dialogs, and `aria-pressed`/`aria-expanded` state.
- The collection is collapsed by default; the bottom control and top Gallery action expand it.
- Check approximately 390 px mobile, 700–1150 px compact/tablet, and 1440 px desktop widths.
- Keep implementation details out of the main creative flow.
- UI and graphic outputs are raster images. Do not imply functional HTML, components, or vector export.

## Performance

- Preserve low-VRAM mode as the 8 GB default.
- Intermediate previews remain off by default because they do not affect saved quality.
- Keep lossless Qwen Image 2.1 KV-cache precision by default. Lossy caches and accelerated samplers must be clearly opt-in unless visual regression testing shows equivalent output.
- Keep normalized reference filenames stable for ComfyUI cache reuse.
- Prefer streamed `FileResponse` output over loading large files into server memory.

## Documentation and releases

Update `README.md` when changing setup, models, ports, scripts, modes, limits, or defaults. Keep direct model links and destinations accurate.

Before every push, inspect the staged file list and staged diff. Never commit weights, outputs, screenshots, job JSON, the nested ComfyUI checkout, secrets, tokens, or machine-specific paths.

Third-party projects and weights have separate licenses. Do not add a repository license or claim redistribution rights without the owner's explicit choice.
