"""Qwenian: persistent local Qwen Image batches and a focused browser UI."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import time
import uuid
import warnings
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web
from PIL import Image, ImageOps, UnidentifiedImageError
from studio_core import (CLIP, GGUF, VAE, MODES, QUALITY_STEPS, REQUIRED_NODES,
                         RESOLUTIONS, SIZES, STYLES, build_workflow, dimensions, settings_from)

ROOT = Path(__file__).resolve().parent
TERMINAL = {"done", "error", "cancelled"}
LOG = logging.getLogger("qwenian")


class EngineError(Exception):
    pass


def error_text(value):
    if isinstance(value, dict):
        value = value.get("message") or value.get("exception_message") or value.get("details") or value
    return str(value)[:1200]


def image_url(item):
    return "/api/view?" + urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": "output"})


def normalize_reference(raw, input_dir):
    if len(raw) > 20 * 1024**2:
        raise ValueError("Each reference must be smaller than 20 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("References must be PNG, JPEG, or WebP images.")
                if source.width * source.height > 32_000_000:
                    raise ValueError("References must be smaller than 32 megapixels.")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB")
                if not 0.25 <= image.width / image.height <= 4:
                    raise ValueError("Use references with an aspect ratio between 1:4 and 4:1.")
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                content = buffer.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("A reference is damaged or is not a supported image.") from None
    filename = hashlib.sha256(content).hexdigest() + ".png"
    target = input_dir / filename
    if not target.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(target)
    return filename


class Studio:
    def __init__(self, comfy_url, data_dir, input_dir, output_dir):
        self.comfy_url = comfy_url.rstrip("/")
        self.data_dir, self.input_dir, self.output_dir = map(Path, (data_dir, input_dir, output_dir))
        self.batches = {}
        self.lock = asyncio.Lock()
        self.client_id = "qwenian-local"
        self.session = None
        self.engine_online = False
        self.progress_online = False
        self.capabilities = None

    @property
    def history_cutoff_path(self):
        return self.data_dir / "history-cleared-before.txt"

    def history_cutoff(self):
        try:
            return float(self.history_cutoff_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0.0

    def persist(self, batch):
        target = self.data_dir / (batch["id"] + ".json")
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def load(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for path in self.data_dir.glob("*.json"):
            try:
                batch = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(batch.get("items"), list) or batch.get("id") != path.stem:
                    continue
                for item in batch["items"]:
                    if item["status"] == "waiting":
                        item.update(status="error", error="Studio stopped before this image was submitted. Reuse the settings to try again.")
                    elif item["status"] == "submitting":
                        item["status"] = "checking"
                self.batches[batch["id"]] = batch
            except (OSError, ValueError, KeyError, TypeError):
                LOG.warning("Ignoring invalid job record %s", path.name)

    async def api(self, method, path, **kwargs):
        try:
            async with self.session.request(method, self.comfy_url + path, **kwargs) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    detail, nodes = data.get("error", data), data.get("node_errors")
                    raise EngineError(error_text(detail) + (" " + error_text(nodes) if nodes else ""))
                return data
        except (ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise EngineError("Cannot reach the local generator. " + str(exc)[:300]) from exc

    async def preflight(self):
        if self.capabilities:
            return
        info = await self.api("GET", "/object_info")
        missing = REQUIRED_NODES - info.keys()
        if missing:
            raise EngineError("Generator is missing nodes: " + ", ".join(sorted(missing)))
        for node, field, name in [("UnetLoaderGGUF", "unet_name", GGUF), ("CLIPLoader", "clip_name", CLIP), ("VAELoader", "vae_name", VAE)]:
            if name not in info[node]["input"]["required"][field][0]:
                raise EngineError("Required model is not installed: " + name)
        self.capabilities = True

    def public(self, batch):
        states = [item["status"] for item in batch["items"]]
        status = "working"
        if all(state in TERMINAL for state in states):
            status = "done" if all(state == "done" for state in states) else "partial" if "done" in states else "cancelled" if "cancelled" in states else "error"
        return {**batch, "status": status, "completed": states.count("done"),
                "finished": sum(state in TERMINAL for state in states),
                "images": [image for item in batch["items"] for image in item.get("images", [])]}

    async def refresh(self):
        active = [(batch, item) for batch in list(self.batches.values()) for item in batch["items"]
                  if item["status"] not in TERMINAL and item["status"] != "waiting"]
        if not active:
            return
        queue = await self.api("GET", "/queue")
        running = {entry[1] for entry in queue.get("queue_running", [])}
        pending = {entry[1]: index + 1 for index, entry in enumerate(queue.get("queue_pending", []))}
        for batch, item in active:
            if item["status"] in TERMINAL or item["status"] == "submitting":
                continue
            pid = item["prompt_id"]
            entry = (await self.api("GET", f"/history/{pid}")).get(pid)
            old = json.dumps(item, sort_keys=True)
            if entry:
                messages = entry.get("status", {}).get("messages", [])
                if entry.get("status", {}).get("status_str") == "error":
                    event = next((m for m in reversed(messages) if m[0] in {"execution_error", "execution_interrupted"}), None)
                    item.update(status="cancelled" if event and event[0] == "execution_interrupted" else "error",
                                error=error_text(event[1]) if event else "Generation failed. Check the generator log.")
                else:
                    images = [image_url(image) for output in entry.get("outputs", {}).values()
                              for image in output.get("images", []) if image.get("type", "output") == "output"]
                    if images:
                        item.update(status="done", images=images, progress=1.0, stage="Complete")
                        item.pop("error", None)
                    elif entry.get("status", {}).get("completed"):
                        item.update(status="error", error="The generator finished without an image.")
                for event, data in messages:
                    if event == "execution_start" and data.get("timestamp"):
                        item["started_at"] = data["timestamp"] / 1000
                    if event in {"execution_success", "execution_error", "execution_interrupted"} and data.get("timestamp"):
                        item["ended_at"] = data["timestamp"] / 1000
            elif pid in running:
                item.update(status="running", queue_position=0)
                item.setdefault("started_at", time.time())
                item.pop("missing_since", None)
            elif pid in pending:
                item.update(status="queued", queue_position=pending[pid])
                item.pop("missing_since", None)
            else:
                item.setdefault("missing_since", time.time())
                if time.time() - item["missing_since"] > 20:
                    item.update(status="cancelled" if item.get("cancel_requested") else "error",
                                error=item.get("error") or "Job is no longer in the generator queue or history.")
            if item["status"] in TERMINAL:
                item.setdefault("ended_at", time.time())
            if old != json.dumps(item, sort_keys=True):
                self.persist(batch)

    async def monitor(self):
        while True:
            try:
                async with self.lock:
                    await self.refresh()
            except EngineError:
                self.engine_online = False
            except Exception:
                LOG.exception("Job monitor failed")
            await asyncio.sleep(2)

    def progress(self, message):
        event, data = message.get("type"), message.get("data", {})
        pid = data.get("prompt_id")
        item = next((i for b in self.batches.values() for i in b["items"] if i.get("prompt_id") == pid), None)
        if not item or item["status"] in TERMINAL:
            return
        if event in {"execution_start", "executing", "progress"}:
            item["status"] = "running"
            item.setdefault("started_at", time.time())
        if event == "progress" and data.get("max"):
            item.update(progress=min(1.0, data["value"] / data["max"]), step=data["value"], total_steps=data["max"], stage="Sampling")
        elif event == "executing":
            item["stage"] = {"1": "Loading model", "2": "Loading text encoder", "3": "Loading decoder", "5": "Understanding your brief",
                             "6": "Sampling", "7": "Decoding image", "8": "Saving image"}.get(str(data.get("node")), "Preparing")

    async def events(self):
        while True:
            try:
                async with self.session.ws_connect(self.comfy_url + "/ws", params={"clientId": self.client_id}, heartbeat=30) as ws:
                    self.engine_online, self.progress_online = True, True
                    async for message in ws:
                        if message.type == WSMsgType.TEXT:
                            self.progress(json.loads(message.data))
                        elif message.type == WSMsgType.ERROR:
                            break
            except (ClientError, asyncio.TimeoutError, ValueError):
                pass
            self.engine_online, self.progress_online = False, False
            self.capabilities = None
            await asyncio.sleep(3)


@web.middleware
async def guard(request, handler):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return web.json_response({"error": "Requests must come from Qwenian."}, status=403)
    try:
        return await handler(request)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except EngineError as exc:
        return web.json_response({"error": str(exc)}, status=503)


async def home(request):
    return web.FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})


async def config(request):
    return web.json_response({"modes": MODES, "styles": STYLES, "sizes": SIZES, "quality_steps": QUALITY_STEPS, "resolutions": RESOLUTIONS})


async def preview(request):
    return web.json_response({"prompt": settings_from(await request.post())["effective_prompt"]})


async def health(request):
    studio = request.app["studio"]
    try:
        stats, queue = await asyncio.gather(studio.api("GET", "/system_stats"), studio.api("GET", "/queue"))
        await studio.preflight()
        device = next(iter(stats.get("devices", [])), {})
        studio.engine_online = True
        return web.json_response({"online": True, "device": device.get("name", "Local generator"),
                                  "vram_gb": round(device.get("vram_total", 0) / 1024**3, 1),
                                  "queued": len(queue.get("queue_pending", [])), "running": len(queue.get("queue_running", [])),
                                  "live_progress": studio.progress_online})
    except EngineError as exc:
        studio.engine_online = False
        return web.json_response({"online": False, "error": str(exc)}, status=503)


async def generate(request):
    studio = request.app["studio"]
    data = await request.post()
    settings = settings_from(data)
    uploads = [file for file in data.getall("references", []) if getattr(file, "file", None)]
    saved = data.getall("saved_references", [])
    if len(uploads) + len(saved) > 10:
        raise ValueError("Use up to 10 reference images.")
    refs = []
    for filename in saved:
        if not valid_reference(filename) or not (studio.input_dir / filename).is_file():
            raise ValueError("A saved reference is no longer available. Add it again.")
        refs.append(filename)
    if settings["mode"] in {"edit", "design"} and not (uploads or refs):
        raise ValueError("Add at least one reference image for Edit or Design Match.")
    async with studio.lock:
        active = sum(i["status"] not in TERMINAL for b in studio.batches.values() for i in b["items"])
        if active + settings["count"] > 24:
            raise ValueError("The studio queue is full (24 images). Wait for an image to finish or cancel a batch.")
        await studio.preflight()
        for upload in uploads:
            refs.append(await asyncio.to_thread(normalize_reference, upload.file.read(20 * 1024**2 + 1), studio.input_dir))
        width, height, _ = dimensions(settings, refs, studio.input_dir)
        batch_id = uuid.uuid4().hex
        batch = {"id": batch_id, "created_at": time.time(), "settings": settings, "references": refs,
                 "width": width, "height": height, "items": [
                     {"index": index, "seed": settings["seed"] + index, "prompt_id": str(uuid.uuid4()),
                      "status": "waiting", "images": [], "progress": 0} for index in range(settings["count"])]}
        studio.batches[batch_id] = batch
        studio.persist(batch)
        for index, item in enumerate(batch["items"]):
            item["status"] = "submitting"
            studio.persist(batch)
            body = build_workflow(settings, item["seed"], refs, studio.input_dir,
                                  prefix=f"QwenStudio_{batch_id}_{index + 1}", client_id=studio.client_id)
            body["prompt_id"] = item["prompt_id"]
            try:
                result = await studio.api("POST", "/prompt", json=body)
                item.update(prompt_id=result["prompt_id"], status="queued", submitted_at=time.time())
            except EngineError as exc:
                # Preassigned UUIDs allow recovery if POST succeeds but its response is lost.
                item.update(status="checking", error=str(exc), submitted_at=time.time())
                for remaining in batch["items"][index + 1:]:
                    remaining.update(status="error", error="Not submitted after the generator rejected or lost connection during this batch.")
                studio.persist(batch)
                break
            studio.persist(batch)
    return web.json_response(studio.public(batch), status=202)


async def batches(request):
    studio = request.app["studio"]
    records = sorted(studio.batches.values(), key=lambda b: b["created_at"], reverse=True)
    return web.json_response({"batches": [studio.public(b) for index, b in enumerate(records)
                                         if index < 100 or any(i["status"] not in TERMINAL for i in b["items"])]})


def get_batch(request):
    batch = request.app["studio"].batches.get(request.match_info["batch_id"])
    if batch is None:
        raise web.HTTPNotFound(text="Unknown batch")
    return batch


async def job(request):
    return web.json_response(request.app["studio"].public(get_batch(request)))


async def cancel(request):
    studio, batch = request.app["studio"], get_batch(request)
    async with studio.lock:
        for item in batch["items"]:
            if item["status"] in TERMINAL:
                continue
            # The native endpoint checks the UUID atomically; never interrupt other jobs.
            result = await studio.api("POST", f"/api/jobs/{item['prompt_id']}/cancel", json={})
            if result.get("cancelled"):
                item.update(status="cancelled", cancel_requested=True, ended_at=time.time(), stage="Cancelled")
            else:
                item["cancel_requested"] = True
            studio.persist(batch)
        await studio.refresh()
    return web.json_response(studio.public(batch))


async def cancel_item(request):
    studio, batch = request.app["studio"], get_batch(request)
    try:
        index = int(request.match_info["index"])
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid item index")
    if index < 0 or index >= len(batch["items"]):
        raise web.HTTPNotFound(text="Unknown batch item")
    item = batch["items"][index]
    async with studio.lock:
        if item["status"] in TERMINAL:
            return web.json_response(studio.public(batch))
        result = await studio.api("POST", f"/api/jobs/{item['prompt_id']}/cancel", json={})
        item["cancel_requested"] = True
        if result.get("cancelled"):
            item.update(status="cancelled", ended_at=time.time(), stage="Removed from queue")
        studio.persist(batch)
    return web.json_response(studio.public(batch))


async def clear_queue(request):
    studio = request.app["studio"]
    async with studio.lock:
        queue = await studio.api("GET", "/queue")
        owned = {item["prompt_id"]: (batch, item)
                 for batch in studio.batches.values() for item in batch["items"]
                 if item["status"] not in TERMINAL and item.get("prompt_id")}
        queued_ids = [entry[1] for entry in queue.get("queue_pending", []) if entry[1] in owned]
        if queued_ids:
            await studio.api("POST", "/queue", json={"delete": queued_ids})
        for prompt_id in queued_ids:
            batch, item = owned[prompt_id]
            item.update(status="cancelled", cancel_requested=True, ended_at=time.time(), stage="Removed from queue")
            studio.persist(batch)
    return web.json_response({"removed": len(queued_ids), "batches": [studio.public(batch) for batch in studio.batches.values()]})


async def clear_history(request):
    studio = request.app["studio"]
    async with studio.lock:
        removable = [batch_id for batch_id, batch in studio.batches.items()
                     if all(item["status"] in TERMINAL for item in batch["items"])]
        cutoff = time.time()
        studio.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = studio.history_cutoff_path.with_suffix(".tmp")
        temporary.write_text(str(cutoff), encoding="utf-8")
        temporary.replace(studio.history_cutoff_path)
        for batch_id in removable:
            path = studio.data_dir / f"{batch_id}.json"
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            studio.batches.pop(batch_id, None)
        records = sorted(studio.batches.values(), key=lambda batch: batch["created_at"], reverse=True)
    return web.json_response({"removed": len(removable), "batches": [studio.public(batch) for batch in records]})


def output_path(studio, filename, subfolder=""):
    base = studio.output_dir.resolve()
    path = (base / subfolder / filename).resolve()
    if not path.is_relative_to(base) or not path.name.startswith("QwenStudio") or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
        raise web.HTTPNotFound(text="Image not found")
    return path


async def view(request):
    return web.FileResponse(output_path(request.app["studio"], request.query.get("filename", ""), request.query.get("subfolder", "")))


def valid_reference(filename):
    return isinstance(filename, str) and len(filename) == 68 and filename.endswith(".png") and all(c in "0123456789abcdef" for c in filename[:-4])


async def reference(request):
    filename = request.match_info["filename"]
    if not valid_reference(filename):
        raise web.HTTPNotFound()
    return web.FileResponse(request.app["studio"].input_dir / filename)


async def recent(request):
    studio = request.app["studio"]
    cutoff = studio.history_cutoff()
    files = await asyncio.to_thread(lambda: sorted(
        (path for path in studio.output_dir.glob("QwenStudio*.png") if path.stat().st_mtime > cutoff),
        key=lambda path: path.stat().st_mtime, reverse=True)[:48])
    return web.json_response({"images": [image_url({"filename": p.name}) for p in files]})


async def download_batch(request):
    studio, batch = request.app["studio"], get_batch(request)
    paths = []
    for item in batch["items"]:
        for url in item.get("images", []):
            query = parse_qs(urlsplit(url).query)
            paths.append(output_path(studio, query["filename"][0], query.get("subfolder", [""])[0]))
    if not paths:
        raise ValueError("This batch has no completed images yet.")
    def archive():
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as bundle:
            for path in paths:
                bundle.write(path, path.name)
            bundle.writestr("settings.json", json.dumps(studio.public(batch), ensure_ascii=False, indent=2))
        return buffer.getvalue()
    return web.Response(body=await asyncio.to_thread(archive), content_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="qwenian-{batch["id"][:8]}.zip"'})


async def lifecycle(app):
    studio = app["studio"]
    studio.load()
    async with ClientSession(timeout=ClientTimeout(total=30, connect=5)) as session:
        studio.session = session
        tasks = [asyncio.create_task(studio.monitor()), asyncio.create_task(studio.events())]
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for batch in studio.batches.values():
            studio.persist(batch)


def create_app(comfy_url="http://127.0.0.1:8188", data_dir=None, input_dir=None, output_dir=None):
    app = web.Application(client_max_size=80 * 1024**2, middlewares=[guard])
    app["studio"] = Studio(comfy_url, data_dir or ROOT / ".studio" / "jobs",
                           input_dir or ROOT / "ComfyUI" / "input" / "qwen_studio", output_dir or ROOT / "ComfyUI" / "output")
    app.cleanup_ctx.append(lifecycle)
    app.add_routes([web.get("/", home), web.get("/api/config", config), web.post("/api/preview", preview), web.get("/api/health", health),
                    web.post("/api/generate", generate), web.get("/api/batches", batches),
                    web.get("/api/job/{batch_id}", job), web.post("/api/job/{batch_id}/cancel", cancel),
                    web.post("/api/job/{batch_id}/item/{index}/cancel", cancel_item), web.post("/api/queue/clear", clear_queue),
                    web.post("/api/history/clear", clear_history),
                    web.get("/api/job/{batch_id}/download", download_batch), web.get("/api/view", view),
                    web.get("/api/reference/{filename}", reference), web.get("/api/recent", recent)])
    app.router.add_static("/static/", ROOT / "static")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), host="127.0.0.1", port=args.port)
