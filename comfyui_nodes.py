"""ComfyUI nodes for consuming published hAI prompt-library manifests."""
from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path
from typing import Any

_NO_MANIFEST = "<no published manifests found>"
_ENV_ROOT = "HAI_PROMPT_LIBRARY_ROOT"
_RUNTIME_MODES = ("t2i", "i2i")
_SUBJECT_PLACEHOLDER = "[[SUBJECT]]"
_PLACEHOLDER_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]")


def _default_runtime_root() -> Path:
    return Path(__file__).resolve().parent / "runtime-library"


def runtime_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get(_ENV_ROOT, "").strip()
    if configured:
        for value in configured.split(os.pathsep):
            value = value.strip()
            if value:
                roots.append(Path(value).expanduser().resolve())
    roots.append(_default_runtime_root().resolve())
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique.append(root)
    return unique


def discover_manifests() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root_index, root in enumerate(runtime_roots(), start=1):
        if not root.exists():
            continue
        for mode in _RUNTIME_MODES:
            path = root / mode / "manifest.json"
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            label = rel if rel not in found else f"root{root_index}:{rel}"
            found[label] = path.resolve()
    return found


def manifest_choices() -> list[str]:
    choices = list(discover_manifests())
    return choices if choices else [_NO_MANIFEST]


def _relative_manifest_candidate(root: Path, label: str) -> Path | None:
    candidate = (root / label).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if candidate.is_file() and candidate.name == "manifest.json":
        return candidate
    return None


def resolve_manifest(label: str) -> Path:
    found = discover_manifests()
    if label in found:
        return found[label]

    for root in runtime_roots():
        candidate = _relative_manifest_candidate(root, label)
        if candidate is not None:
            return candidate

    candidate = Path(label).expanduser()
    if candidate.is_file() and candidate.name == "manifest.json":
        return candidate.resolve()
    if label == _NO_MANIFEST:
        raise FileNotFoundError(
            "No published prompt manifests found. Publish a runtime bundle or "
            f"set {_ENV_ROOT}."
        )
    raise FileNotFoundError(f"Prompt manifest not found: {label}")


def load_manifest(label: str) -> tuple[Path, dict[str, Any]]:
    path = resolve_manifest(label)
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: manifest root must be an object")
    items = obj.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{path}: manifest.items must be a list")
    if obj.get("prompt_count") != len(items):
        raise ValueError(
            f"{path}: prompt_count={obj.get('prompt_count')} but items={len(items)}"
        )
    if obj.get("subject_deferred") is not True:
        raise ValueError(f"{path}: runtime manifest must defer {_SUBJECT_PLACEHOLDER}")
    if obj.get("subject_placeholder") != _SUBJECT_PLACEHOLDER:
        raise ValueError(
            f"{path}: subject_placeholder must be {_SUBJECT_PLACEHOLDER}"
        )
    return path, obj


def _safe_item_path(manifest_path: Path, item: dict[str, Any]) -> Path:
    rel = item.get("file")
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError(f"{manifest_path}: manifest item has no file path")
    base = manifest_path.parent.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{manifest_path}: prompt file escapes bundle: {rel}") from exc
    if not target.is_file():
        raise FileNotFoundError(f"Prompt file missing: {target}")
    return target


def read_item_template(manifest_path: Path, item: dict[str, Any]) -> str:
    return _safe_item_path(manifest_path, item).read_text(encoding="utf-8").rstrip("\n")


def render_item(manifest_path: Path, item: dict[str, Any], subject: str) -> str:
    value = subject.strip()
    if not value:
        raise ValueError("subject must not be empty")
    text = read_item_template(manifest_path, item)
    if _SUBJECT_PLACEHOLDER not in text:
        raise ValueError(
            f"{manifest_path}: prompt {item.get('prompt_id')} has no {_SUBJECT_PLACEHOLDER}"
        )
    text = text.replace(_SUBJECT_PLACEHOLDER, value)
    unresolved = sorted(set(_PLACEHOLDER_RE.findall(text)))
    if unresolved:
        raise ValueError(
            f"{manifest_path}: unresolved placeholder(s) after subject substitution: "
            + ", ".join(unresolved)
        )
    return text


def _filter_items(items: list[dict[str, Any]], collection: str) -> list[dict[str, Any]]:
    value = collection.strip().casefold()
    if not value or value in {"*", "all"}:
        return list(items)
    return [
        item
        for item in items
        if str(item.get("collection_slug") or "").casefold() == value
        or str(item.get("collection") or "").casefold() == value
    ]


def _manifest_change_token(label: str) -> str:
    try:
        path = resolve_manifest(label)
        stat = path.stat()
        return f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return f"missing:{label}"


class HAIPromptSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest": (manifest_choices(),),
                "subject": ("STRING", {"default": "woman", "multiline": False}),
                "mode": (["index", "random", "prompt_id"],),
                "index": ("INT", {"default": 0, "min": 0, "max": 2147483647, "step": 1}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "collection": ("STRING", {"default": "", "multiline": False}),
                "prompt_id": ("STRING", {"default": "", "multiline": False}),
                "wrap_index": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "INT", "INT", "STRING")
    RETURN_NAMES = ("prompt", "prompt_id", "collection", "source_character", "source_model", "index", "total", "prompt_file")
    FUNCTION = "select"
    CATEGORY = "hAI/Prompt Library"

    @classmethod
    def IS_CHANGED(cls, manifest, subject, mode, index, seed, collection, prompt_id, wrap_index):
        return f"{_manifest_change_token(manifest)}:{subject}"

    def select(self, manifest, subject, mode, index, seed, collection, prompt_id, wrap_index):
        manifest_path, obj = load_manifest(manifest)
        items = _filter_items(obj["items"], collection)
        if not items:
            raise ValueError(f"No prompts match collection filter {collection!r} in {manifest_path}")

        if mode == "prompt_id":
            wanted = prompt_id.strip()
            if not wanted:
                raise ValueError("mode=prompt_id requires a non-empty prompt_id")
            matches = [item for item in items if item.get("prompt_id") == wanted]
            if not matches:
                raise ValueError(f"prompt_id not found in selection: {wanted}")
            item = matches[0]
            selected_index = items.index(item)
        elif mode == "random":
            selected_index = random.Random(int(seed)).randrange(len(items))
            item = items[selected_index]
        elif mode == "index":
            requested = int(index)
            if wrap_index:
                selected_index = requested % len(items)
            else:
                if requested < 0 or requested >= len(items):
                    raise IndexError(f"index {requested} outside 0..{len(items) - 1}")
                selected_index = requested
            item = items[selected_index]
        else:
            raise ValueError(f"Unknown selection mode: {mode}")

        prompt_path = _safe_item_path(manifest_path, item)
        prompt = render_item(manifest_path, item, subject)
        return (
            prompt,
            str(item.get("prompt_id") or ""),
            str(item.get("collection") or ""),
            str(item.get("source_character") or ""),
            str(item.get("source_model") or ""),
            selected_index,
            len(items),
            str(prompt_path),
        )


class HAIPromptBatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest": (manifest_choices(),),
                "subject": ("STRING", {"default": "woman", "multiline": False}),
                "collection": ("STRING", {"default": "", "multiline": False}),
                "order": (["manifest", "shuffle"],),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "start": ("INT", {"default": 0, "min": 0, "max": 2147483647, "step": 1}),
                "count": ("INT", {"default": 0, "min": 0, "max": 2147483647, "step": 1}),
                "stride": ("INT", {"default": 1, "min": 1, "max": 1000000, "step": 1}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("prompts", "prompt_ids", "collections", "source_characters", "source_models", "total")
    OUTPUT_IS_LIST = (True, True, True, True, True, False)
    FUNCTION = "batch"
    CATEGORY = "hAI/Prompt Library"

    @classmethod
    def IS_CHANGED(cls, manifest, subject, collection, order, seed, start, count, stride):
        return f"{_manifest_change_token(manifest)}:{subject}"

    def batch(self, manifest, subject, collection, order, seed, start, count, stride):
        manifest_path, obj = load_manifest(manifest)
        items = _filter_items(obj["items"], collection)
        if not items:
            raise ValueError(f"No prompts match collection filter {collection!r} in {manifest_path}")

        if order == "shuffle":
            items = list(items)
            random.Random(int(seed)).shuffle(items)
        elif order != "manifest":
            raise ValueError(f"Unknown batch order: {order}")

        start_i = int(start)
        stride_i = int(stride)
        selected = items[start_i::stride_i]
        count_i = int(count)
        if count_i:
            selected = selected[:count_i]
        if not selected:
            raise ValueError(
                f"Batch selection is empty: start={start_i}, count={count_i}, "
                f"stride={stride_i}, available={len(items)}"
            )

        prompts = [render_item(manifest_path, item, subject) for item in selected]
        prompt_ids = [str(item.get("prompt_id") or "") for item in selected]
        collections = [str(item.get("collection") or "") for item in selected]
        characters = [str(item.get("source_character") or "") for item in selected]
        models = [str(item.get("source_model") or "") for item in selected]
        return prompts, prompt_ids, collections, characters, models, len(selected)


NODE_CLASS_MAPPINGS = {
    "HAIPromptSelect": HAIPromptSelect,
    "HAIPromptBatch": HAIPromptBatch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HAIPromptSelect": "hAI Prompt Select",
    "HAIPromptBatch": "hAI Prompt Batch",
}
