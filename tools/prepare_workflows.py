"""Fetch the official Qwen Image 2.1 workflows and point them at the local GGUF."""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.request


BASE_URL = "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/"
GGUF_NAME = "qwen-image-2.1-UC-Q4_K_M.gguf"
WORKFLOWS = {
    "Qwen-Image-2.1-Text-to-Image-GGUF.json": "image_qwen_image_2_1_t2i.json",
    "Qwen-Image-2.1-Multi-Reference-Edit-GGUF.json": "image_qwen_image_2_1_image_edit.json",
}


def adapt(value: object) -> None:
    """Replace every official UNET loader, including ones nested in subgraphs."""
    if isinstance(value, list):
        for item in value:
            adapt(item)
    elif isinstance(value, dict):
        if value.get("type") == "UNETLoader":
            value["type"] = "UnetLoaderGGUF"
            properties = value.setdefault("properties", {})
            properties["Node name for S&R"] = "UnetLoaderGGUF"
            widgets = value.get("widgets_values")
            if isinstance(widgets, list) and widgets:
                widgets[0] = GGUF_NAME
                if len(widgets) > 1:
                    del widgets[1:]
            named = value.get("widgets_values_named")
            if isinstance(named, dict):
                named.clear()
                named["unet_name"] = GGUF_NAME
        for child in value.values():
            adapt(child)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    for local_name, remote_name in WORKFLOWS.items():
        with urllib.request.urlopen(BASE_URL + remote_name, timeout=60) as response:
            workflow = json.load(response)
        adapt(workflow)
        target = args.output / local_name
        target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {target}")


if __name__ == "__main__":
    main()
