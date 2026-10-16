#!/usr/bin/env python3
"""Compile curated HearmemanAI prompts into model-neutral runtime modes.

Phase 3 consumes ``prompt-library/curated/library.json`` produced by
``hearmeman_curate.py``. It never edits the source or curated layers.

Modes:

* ``t2i``: keep ``[[SUBJECT]]`` deferred for runtime substitution, omit
  reference-image instructions, and render products with generic/custom text.
* ``i2i``: keep ``[[SUBJECT]]`` deferred for runtime substitution while
  restoring the original reference-aware identity/generation semantics and
  reference-aware product identity.
* ``raw``: export ``prompt_original`` exactly as preserved by Phase 1/2.

Exports contain one UTF-8 ``.txt`` file per prompt plus ``manifest.json``.
There is one canonical export directory per mode; rerunning a mode replaces that
whole generated directory so stale prompt files cannot survive narrower runs.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from hearmeman_ingest_core import utc_now, write_json

MODES = ("t2i", "i2i", "raw")
RUNTIME_MODES = ("t2i", "i2i")

SUBJECT_PLACEHOLDER = "[[SUBJECT]]"
REFERENCE_IDENTITY_PLACEHOLDER = "[[REFERENCE_IDENTITY]]"
REFERENCE_IDENTITY_SCOPE_PLACEHOLDER = "[[REFERENCE_IDENTITY_SCOPE]]"
REFERENCE_GENERATION_PLACEHOLDER = "[[REFERENCE_GENERATION]]"
PRODUCT_PLACEHOLDER = "[[PRODUCT]]"
PLACEHOLDER_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]")


class RenderError(ValueError):
    pass


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "export"


def _slot_originals(prompt: dict[str, Any], slot_name: str) -> list[str]:
    slot = prompt.get("slots", {}).get(slot_name) or {}
    values = slot.get("original") or []
    if isinstance(values, str):
        return [values]
    return [str(v) for v in values]


def _replace_sequential(
    text: str,
    placeholder: str,
    values: list[str],
    *,
    prompt_id: str,
) -> str:
    count = text.count(placeholder)
    if count != len(values):
        raise RenderError(
            f"{prompt_id}: {placeholder} occurs {count} time(s) but slot has "
            f"{len(values)} value(s)"
        )
    for value in values:
        text = text.replace(placeholder, value, 1)
    return text


def _render_product_reference(item: dict[str, Any]) -> str:
    """Render only product identity/reference mechanics, never pose/action text."""
    source = item.get("reference_source")
    original = str(item.get("original") or "").strip()
    product_type = str(item.get("product_type") or "product").strip()

    if source == "second_reference_image":
        match = re.search(
            r"\bthe\s+exact\s+(?P<product>.+?)\s+product\s+shown\s+in\s+the\s+second\s+reference\s+image\b",
            original,
            flags=re.IGNORECASE,
        )
        source_product = match.group("product").strip() if match else product_type
        return (
            f"the exact {source_product} product shown in the second reference image, "
            "product kept identical"
        )

    if source == "product_image":
        if original:
            return original
        return f"the {product_type} from the product image, kept identical"

    if original:
        return original
    return product_type


def _product_values(
    prompt: dict[str, Any],
    mode: str,
    overrides: dict[str, str] | None,
) -> list[str]:
    items = (prompt.get("slots", {}).get("product") or {}).get("items") or []
    values: list[str] = []
    overrides = overrides or {}

    for item in items:
        product_type = str(item.get("product_type") or "product").strip().lower()
        if mode == "i2i":
            values.append(_render_product_reference(item))
        else:
            values.append(
                overrides.get(product_type)
                or str(item.get("generic_description") or product_type)
            )
    return values


def _cleanup_omitted_reference_text(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(r",\s*,+", ",", line)
        line = re.sub(r";\s*;+", ";", line)
        line = re.sub(r"([,:;])\s*([.!?])", r"\2", line)
        line = re.sub(r"\.\s*\.", ".", line)
        line = re.sub(r"\s+([,.;:!?])", r"\1", line)
        line = re.sub(r"^\s*[,;:]\s*", "", line)
        line = re.sub(r"\s*[,;:]\s*$", "", line)
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def render_prompt(
    prompt: dict[str, Any],
    mode: str,
    *,
    product_overrides: dict[str, str] | None = None,
) -> str:
    """Compile one prompt for a runtime mode, deliberately deferring SUBJECT."""
    if mode not in MODES:
        raise RenderError(f"unknown mode: {mode}")

    if mode == "raw":
        return str(prompt["prompt_original"])

    prompt_id = str(prompt.get("id") or "<unknown>")
    text = str(prompt["prompt_template"])

    product_values = _product_values(prompt, mode, product_overrides)
    text = _replace_sequential(
        text,
        PRODUCT_PLACEHOLDER,
        product_values,
        prompt_id=prompt_id,
    )

    if mode == "t2i":
        for placeholder in (
            REFERENCE_IDENTITY_PLACEHOLDER,
            REFERENCE_IDENTITY_SCOPE_PLACEHOLDER,
            REFERENCE_GENERATION_PLACEHOLDER,
        ):
            text = text.replace(placeholder, "")
        text = _cleanup_omitted_reference_text(text)
    elif mode == "i2i":
        text = _replace_sequential(
            text,
            REFERENCE_IDENTITY_PLACEHOLDER,
            _slot_originals(prompt, "reference_identity"),
            prompt_id=prompt_id,
        )
        text = _replace_sequential(
            text,
            REFERENCE_IDENTITY_SCOPE_PLACEHOLDER,
            _slot_originals(prompt, "reference_identity_scope"),
            prompt_id=prompt_id,
        )
        text = _replace_sequential(
            text,
            REFERENCE_GENERATION_PLACEHOLDER,
            _slot_originals(prompt, "reference_generation"),
            prompt_id=prompt_id,
        )
        text = text.strip()

    unresolved = sorted(set(PLACEHOLDER_RE.findall(text)))
    unexpected = [p for p in unresolved if p != SUBJECT_PLACEHOLDER]
    if unexpected:
        raise RenderError(
            f"{prompt_id}: unresolved placeholder(s): {', '.join(unexpected)}"
        )
    if SUBJECT_PLACEHOLDER not in text:
        raise RenderError(
            f"{prompt_id}: compiled {mode} prompt has no {SUBJECT_PLACEHOLDER}"
        )

    if mode == "t2i":
        low = text.casefold()
        residual = [
            marker
            for marker in ("reference image", "product image")
            if marker in low
        ]
        if residual:
            raise RenderError(
                f"{prompt_id}: {mode} output still contains reference wording: "
                + ", ".join(residual)
            )

    return text


def _selection_matches(
    prompt: dict[str, Any],
    *,
    collections: set[str],
    prompt_ids: set[str],
    source_models: set[str],
    selection: str,
    include_review: bool,
) -> bool:
    if not include_review and prompt.get("curation", {}).get("review_required"):
        return False

    if collections:
        slug = str(prompt.get("collection_slug") or "").casefold()
        name = str(prompt.get("collection") or "").casefold()
        if slug not in collections and name not in collections:
            return False

    if prompt_ids and str(prompt.get("id")) not in prompt_ids:
        return False

    if source_models:
        model = str(prompt.get("source", {}).get("model") or "").casefold()
        if model not in source_models:
            return False

    cur = prompt.get("curation", {})
    keep = cur.get("keep")
    favorite = bool(cur.get("favorite"))
    if selection == "kept" and keep is not True:
        return False
    if selection == "not-rejected" and keep is False:
        return False
    if selection == "favorites" and not favorite:
        return False

    return True


def select_prompts(
    prompts: Iterable[dict[str, Any]],
    *,
    collections: Iterable[str] = (),
    prompt_ids: Iterable[str] = (),
    source_models: Iterable[str] = (),
    selection: str = "not-rejected",
    include_review: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    collection_set = {x.casefold() for x in collections}
    prompt_id_set = set(prompt_ids)
    source_model_set = {x.casefold() for x in source_models}

    chosen = [
        p
        for p in prompts
        if _selection_matches(
            p,
            collections=collection_set,
            prompt_ids=prompt_id_set,
            source_models=source_model_set,
            selection=selection,
            include_review=include_review,
        )
    ]
    if limit is not None:
        chosen = chosen[:limit]
    return chosen


def load_product_overrides(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in obj.items()
    ):
        raise RenderError(
            "--product-map must be a JSON object mapping product_type to text"
        )
    return {k.strip().lower(): v for k, v in obj.items()}


def _safe_character(value: str) -> str:
    return slugify(value)[:40]


def export_prompts(
    curated_library: Path,
    out_dir: Path,
    *,
    mode: str,
    collections: Iterable[str] = (),
    prompt_ids: Iterable[str] = (),
    source_models: Iterable[str] = (),
    selection: str = "not-rejected",
    include_review: bool = False,
    limit: int | None = None,
    product_overrides: dict[str, str] | None = None,
) -> Path:
    library = json.loads(curated_library.read_text(encoding="utf-8"))
    collections = list(collections)
    prompt_ids = list(prompt_ids)
    source_models = list(source_models)

    prompts = select_prompts(
        library.get("prompts", []),
        collections=collections,
        prompt_ids=prompt_ids,
        source_models=source_models,
        selection=selection,
        include_review=include_review,
        limit=limit,
    )

    run_dir = out_dir / "exports" / mode
    if run_dir.exists():
        shutil.rmtree(run_dir)
    items: list[dict[str, Any]] = []

    for global_index, prompt in enumerate(prompts, start=1):
        rendered = render_prompt(
            prompt,
            mode,
            product_overrides=product_overrides,
        )
        collection_slug = str(prompt["collection_slug"])
        source_index = int(prompt.get("source_index", global_index - 1)) + 1
        character = _safe_character(
            str(prompt.get("source", {}).get("character") or "prompt")
        )
        suffix = str(prompt["id"]).rsplit("-", 1)[-1]
        filename = f"{source_index:03d}__{character}__{suffix}.txt"
        relative = Path("collections") / collection_slug / filename
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered.rstrip() + "\n", encoding="utf-8")

        items.append(
            {
                "index": global_index,
                "prompt_id": prompt["id"],
                "collection": prompt["collection"],
                "collection_slug": collection_slug,
                "source_index": prompt.get("source_index"),
                "source_character": prompt.get("source", {}).get("character"),
                "source_model": prompt.get("source", {}).get("model"),
                "file": relative.as_posix(),
                "product_count": len(
                    (prompt.get("slots", {}).get("product") or {}).get("items") or []
                ),
            }
        )

    if mode == "t2i":
        reference_policy = "omit"
        product_policy = "generic"
        subject_deferred = True
    elif mode == "i2i":
        reference_policy = "preserve"
        product_policy = "reference"
        subject_deferred = True
    else:
        reference_policy = "raw"
        product_policy = "raw"
        subject_deferred = False

    manifest = {
        "schema_version": 2,
        "generated_at": utc_now(),
        "mode": mode,
        "subject_placeholder": SUBJECT_PLACEHOLDER if subject_deferred else None,
        "subject_deferred": subject_deferred,
        "render_policy": {
            "reference_images": reference_policy,
            "products": product_policy,
        },
        "source_library": str(curated_library),
        "selection": {
            "collections": collections,
            "prompt_ids": prompt_ids,
            "source_models": source_models,
            "curation": selection,
            "include_review": include_review,
            "limit": limit,
        },
        "product_overrides": product_overrides or {},
        "prompt_count": len(items),
        "items": items,
    }
    manifest_path = run_dir / "manifest.json"
    write_json(manifest_path, manifest)

    print(f"Compiled {len(items)} prompt(s) for mode {mode}")
    print(f"Wrote {manifest_path}")
    return manifest_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("prompt-library"),
        help="Prompt-library root (default: prompt-library)",
    )
    ap.add_argument(
        "--library",
        type=Path,
        help="Curated library.json (default: <out>/curated/library.json)",
    )
    ap.add_argument("--mode", choices=MODES, required=True)
    ap.add_argument(
        "--collection",
        action="append",
        default=[],
        help="Collection slug or exact name; repeatable",
    )
    ap.add_argument(
        "--prompt-id",
        action="append",
        default=[],
        help="Exact prompt ID; repeatable",
    )
    ap.add_argument(
        "--source-model",
        action="append",
        default=[],
        help="Source model metadata filter, e.g. nano-banana-2; repeatable",
    )
    ap.add_argument(
        "--selection",
        choices=("all", "not-rejected", "kept", "favorites"),
        default="not-rejected",
        help="Curation filter (default: not-rejected)",
    )
    ap.add_argument(
        "--include-review",
        action="store_true",
        help="Include prompts marked review_required (normally skipped)",
    )
    ap.add_argument("--limit", type=int, help="Compile at most N matching prompts")
    ap.add_argument(
        "--product-map",
        type=Path,
        help="JSON object mapping product_type to custom t2i product text",
    )
    args = ap.parse_args()

    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be >= 1")
    if args.product_map is not None and args.mode != "t2i":
        ap.error("--product-map is only valid with --mode t2i")

    curated_library = args.library or (args.out / "curated" / "library.json")
    if not curated_library.exists():
        ap.error(
            f"curated library not found: {curated_library}; run hearmeman_curate.py first"
        )

    product_overrides = load_product_overrides(args.product_map)

    export_prompts(
        curated_library,
        args.out,
        mode=args.mode,
        collections=args.collection,
        prompt_ids=args.prompt_id,
        source_models=args.source_model,
        selection=args.selection,
        include_review=args.include_review,
        limit=args.limit,
        product_overrides=product_overrides,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
