"""Read-only prompt selection endpoints for Image Playground.

This intentionally exposes the same curated runtime bundles and subject
semantics as the hAI ComfyUI nodes. It does not alter their widgets or queue.
"""
from __future__ import annotations
import random
from .comfyui_nodes import load_manifest, _filter_items, render_item

MAX_SELECTION = 200


def collections():
    result = {}
    totals = {}
    for mode in ("t2i", "i2i"):
        _, data = load_manifest(mode)
        totals[mode] = len(data["items"])
        for item in data["items"]:
            name = item.get("collection")
            if not name:
                continue
            data_item = result.setdefault(name, {"name": name, "slug": item.get("collection_slug", ""),
                                                 "counts": {}})
            data_item["counts"][mode] = data_item["counts"].get(mode, 0) + 1
    return {"modes": ["t2i", "i2i"], "totals": totals,
            "collections": sorted(result.values(), key=lambda x: x["name"].casefold())}


def select(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a prompt selection JSON object.")
    mode = payload.get("mode", "t2i")
    if mode not in ("t2i", "i2i"):
        raise ValueError("Prompt mode must be t2i or i2i.")
    subject = payload.get("subject")
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 300:
        raise ValueError("Subject must contain 1–300 characters.")
    collection = payload.get("collection", "<all>")
    if not isinstance(collection, str) or len(collection) > 300:
        raise ValueError("Invalid collection.")
    start = payload.get("start", 0)
    stride = payload.get("stride", 1)
    count = payload.get("count", 8)
    seed = payload.get("seed", 42)
    if not (type(start) is int and 0 <= start <= 100000 and
            type(stride) is int and 1 <= stride <= 10000 and
            type(count) is int and 1 <= count <= MAX_SELECTION and
            type(seed) is int and 0 <= seed <= 0xFFFFFFFF):
        raise ValueError("Invalid start/count/stride/seed.")
    manifest_path, manifest = load_manifest(mode)
    items = _filter_items(manifest["items"], collection)
    if payload.get("shuffle", False) is True:
        items = list(items)
        random.Random(seed).shuffle(items)
    selected = items[start::stride][:count]
    if not selected:
        raise ValueError("No prompts matched the selected collection and range.")
    return {"mode": mode, "selected": [{
        "id": str(item.get("prompt_id") or ""), "prompt_id": str(item.get("prompt_id") or ""),
        "text": render_item(manifest_path, item, subject),
        "collection": item.get("collection"), "group_name": item.get("collection"),
        "group_id": item.get("collection_slug"), "group_position": item.get("source_index"),
        "source_model": item.get("source_model"),
        "source_character": item.get("source_character")
    } for item in selected], "count": len(selected)}


def register_routes():
    from aiohttp import web
    from server import PromptServer

    routes = PromptServer.instance.routes

    @routes.get("/hai_prompt_library/api/collections")
    async def list_collections(request):
        try:
            return web.json_response(collections())
        except (ValueError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @routes.post("/hai_prompt_library/api/select")
    async def select_prompts(request):
        if request.content_length is not None and request.content_length > 16384:
            return web.json_response({"error": "Request too large."}, status=413)
        try:
            body = await request.json()
            return web.json_response(select(body))
        except (ValueError, TypeError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
