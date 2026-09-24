"""Validated settings and native Qwen Image 2.1 workflows."""
from __future__ import annotations

import math
import secrets
from pathlib import Path
from PIL import Image

GGUF = "qwen-image-2.1-UC-Q4_K_M.gguf"
CLIP = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "qwen_image_2.1_vae_bf16.safetensors"
MAX_SEED = 2**53 - 1
SIZES = {"square": (1024, 1024), "portrait": (896, 1152), "tall": (768, 1344),
         "landscape": (1152, 896), "wide": (1344, 768)}
QUALITY_STEPS = {"draft": 24, "balanced": 40, "detailed": 50}
RESOLUTIONS = {"standard": 1024, "large": 1280, "high": 1440}
MODES = {
    "create": {"label": "Image", "brief": "A clear focal point, coherent spatial relationships, and consistent lighting and perspective."},
    "ui": {"label": "UI / Web", "brief": "A straight-on interface design aligned to a consistent grid. Clear hierarchy, generous spacing, consistent components, and deliberate contrast. Use short, large labels in the language of the requested copy; avoid invented filler text. Render the interface edge to edge unless a device mockup is requested."},
    "graphics": {"label": "Graphics", "brief": "A polished graphic composition with intentional hierarchy, crisp shapes, balanced negative space, aligned elements, and a cohesive palette."},
    "product": {"label": "Product", "brief": "A coherent product design with consistent geometry, plausible materials, clean edges, and physically consistent lighting and shadows."},
    "illustration": {"label": "Illustration", "brief": "A cohesive illustration with intentional silhouettes, clear subject separation, consistent visual style, and a balanced composition."},
    "edit": {"label": "Edit", "brief": "Apply the requested edits to image 1. Preserve the identity, structure, composition, and details that the instruction does not ask to change."},
    "design": {"label": "Design Match", "brief": "Image 1 is the master reference. Preserve its layout hierarchy, proportions, visual style, material cues, palette relationships, and art direction. Limit changes to the user's instruction."},
}
STYLES = {
    "auto": "", "photo": "Photographic rendering with plausible textures and natural light.",
    "minimal": "Minimal visual style, restrained details, and generous negative space.",
    "editorial": "Refined editorial art direction with deliberate framing and a cohesive palette.",
    "3d": "Polished three-dimensional rendering with coherent materials and lighting.",
    "flat": "Flat graphic illustration with clean shapes and consistent line weights.",
    "cinematic": "Cinematic composition with controlled contrast and atmospheric lighting.",
}
REQUIRED_NODES = {"UnetLoaderGGUF", "CLIPLoader", "VAELoader", "EmptyLatentImage",
                  "TextEncodeQwenImage21", "QwenImage21Cache", "KSampler", "VAEDecode", "SaveImage", "LoadImage"}


def choice(data, key, choices, default):
    value = str(data.get(key, default))
    if value not in choices:
        raise ValueError(f"Invalid {key.replace('_', ' ')}.")
    return value


def integer(data, key, default, minimum, maximum):
    try:
        value = int(str(data.get(key, default)))
    except (ValueError, TypeError):
        raise ValueError(f"{key.replace('_', ' ').capitalize()} must be a whole number.") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} must be between {minimum} and {maximum}.")
    return value


def boolean(data, key, default=False):
    value = str(data.get(key, str(default))).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"Invalid {key.replace('_', ' ')}.")
    return value == "true"


def settings_from(data):
    prompt = str(data.get("prompt", "")).strip()
    if not prompt or len(prompt) > 12000:
        raise ValueError("Describe your image in 1–12,000 characters.")
    quality = choice(data, "quality", QUALITY_STEPS, "balanced")
    seed_text = str(data.get("seed", "")).strip()
    seed = secrets.randbelow(MAX_SEED - 8) if seed_text in {"", "-1"} else integer(data, "seed", 0, 0, MAX_SEED - 8)
    try:
        cfg = float(data.get("cfg", 1))
    except (ValueError, TypeError):
        raise ValueError("Guidance must be a number between 1 and 5.") from None
    if not math.isfinite(cfg) or not 1 <= cfg <= 5:
        raise ValueError("Guidance must be between 1 and 5.")
    negative = str(data.get("negative_prompt", "")).strip()
    if len(negative) > 4000:
        raise ValueError("Negative prompt is limited to 4,000 characters.")
    if negative and cfg == 1:
        raise ValueError("Negative prompts need guidance above 1. This also increases generation time.")
    s = {"prompt": prompt, "seed": seed,
         "mode": choice(data, "mode", MODES, "create"),
         "shape": choice(data, "shape", SIZES, "square"),
         "quality": quality, "resolution": choice(data, "resolution", RESOLUTIONS, "standard"),
         "style": choice(data, "style", STYLES, "auto"),
         "count": integer(data, "count", 1, 1, 8),
         "steps": integer(data, "steps", QUALITY_STEPS[quality], 20, 80) if str(data.get("steps", "")).strip() else QUALITY_STEPS[quality],
         "cfg": cfg, "negative_prompt": negative,
         "enhance": boolean(data, "enhance", True), "transparent": boolean(data, "transparent"),
         "anatomy": boolean(data, "anatomy"),
         "match_size": boolean(data, "match_size", True),
         "exact_text": str(data.get("exact_text", "")).strip(), "palette": str(data.get("palette", "")).strip(),
         "design_focus": choice(data, "design_focus", {"packaging", "poster", "product", "branding", "interface"}, "packaging")}
    if len(s["exact_text"]) > 1000 or len(s["palette"]) > 300:
        raise ValueError("Keep exact text below 1,000 characters and the palette below 300.")
    s["effective_prompt"] = compose_prompt(s)
    return s


def compose_prompt(s):
    parts = [s["prompt"]]
    if s["enhance"]:
        parts += ["Art direction (follow the user's explicit instructions first): " + MODES[s["mode"]]["brief"]]
        if s["mode"] == "design":
            parts += [f"Design focus: {s['design_focus']}."]
    if STYLES[s["style"]]:
        parts += [STYLES[s["style"]]]
    if s["palette"]:
        parts += ["Requested color palette: " + s["palette"]]
    if s["exact_text"]:
        parts += ["Render this exact text, preserving spelling and capitalization:\n" + s["exact_text"] + "\nUse legible typography and a clear reading order."]
    if s["transparent"]:
        parts += ["This is an RGBA image with transparency. The background is transparent, with a real alpha channel and clean subject edges."]
    if s.get("anatomy"):
        parts += ["For human subjects: natural anatomical proportions, coherent joints, clearly separated hands and fingers, and physically plausible poses. Preserve the requested number of subjects and their intended poses."]
    return "\n\n".join(parts)


def dimensions(s, refs, input_dir):
    resolution = RESOLUTIONS[s["resolution"]]
    width, height = SIZES[s["shape"]]
    if refs:
        # Match the encoder's AREA-based resize, not an independent longest-side resize.
        ratios = []
        for filename in refs:
            with Image.open(Path(input_dir) / filename) as image:
                ratios.append(image.width / image.height)
        max_ratio = max(max(r, 1 / r) for r in ratios)
        resolution = min(resolution, int(2048 / math.sqrt(max_ratio) / 32) * 32)
        if s["match_size"]:
            ratio = ratios[0]
            return (max(32, round(resolution * math.sqrt(ratio) / 32) * 32),
                    max(32, round(resolution / math.sqrt(ratio) / 32) * 32), resolution)
    factor = RESOLUTIONS[s["resolution"]] / 1024
    return round(width * factor / 32) * 32, round(height * factor / 32) * 32, resolution


def build_workflow(s, seed, refs, input_dir, prefix="QwenStudio", client_id="qwen-studio"):
    width, height, resolution = dimensions(s, refs, input_dir)
    graph = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": GGUF}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "vae": ["3", 0],
              "prompt": s["effective_prompt"], "negative_prompt": s["negative_prompt"], "resolution": resolution}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["9", 0], "seed": seed, "steps": s["steps"], "cfg": s["cfg"],
              "sampler_name": "euler", "scheduler": "simple", "positive": ["5", 0], "negative": ["5", 1],
              "latent_image": ["5", 2] if refs and s["match_size"] else ["4", 0], "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["7", 0]}},
        "9": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
    }
    for index, filename in enumerate(refs, 1):
        node_id = str(100 + index)
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": f"qwen_studio/{filename}"}}
        graph["5"]["inputs"][f"images.image_{index}"] = [node_id, 0]
    return {"prompt": graph, "client_id": client_id, "extra_data": {"studio": {**s, "seed": seed, "width": width, "height": height}}}
