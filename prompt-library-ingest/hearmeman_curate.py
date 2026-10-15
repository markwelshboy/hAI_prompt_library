#!/usr/bin/env python3
"""Build the Phase-2 curated prompt library from a Phase-1 library.json.

The source layer remains immutable. This tool creates a separate curated layer
with model-neutral semantic placeholders:

  [[SUBJECT]]
  [[REFERENCE_IDENTITY]]
  [[REFERENCE_IDENTITY_SCOPE]]
  [[REFERENCE_GENERATION]]
  [[PRODUCT]]

Reference mechanics are retained as structured slot metadata so later renderers
can choose reference-aware wording (for Qwen-like workflows) or generic/custom
values (for LoRA/Krea-style workflows) without mutating ``prompt_original``.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from hearmeman_ingest_core import SUBJECT_RE, split_sentences, utc_now, write_json

SUBJECT_PLACEHOLDER = "[[SUBJECT]]"
REFERENCE_IDENTITY_PLACEHOLDER = "[[REFERENCE_IDENTITY]]"
REFERENCE_IDENTITY_SCOPE_PLACEHOLDER = "[[REFERENCE_IDENTITY_SCOPE]]"
REFERENCE_GENERATION_PLACEHOLDER = "[[REFERENCE_GENERATION]]"
PRODUCT_PLACEHOLDER = "[[PRODUCT]]"

IDENTITY_RE = re.compile(
    r"preserv(?:e|ing)\s+the\s+character\s+identity\s+from\s+the\s+reference\s+image,\s*"
    r"keeping\s+their\s+exact\s+hair\s+color,\s*hairstyle,\s*eye\s+color,\s*"
    r"skin\s+tone,\s*face\s+shape,\s*and\s+body\s+shape\.?",
    re.IGNORECASE,
)

REFERENCE_GENERATION_RE = re.compile(
    r"Use\s+the\s+reference\s+image\s+ONLY\s+for\s+her\s+[^.]{1,700}?background\.",
    re.IGNORECASE,
)

SUBJECT_REFERENCE_SPLIT_RE = re.compile(
    r"\s+from\s+the\s+reference\s+image\b", re.IGNORECASE
)

RESIDUAL_SUBJECT_REFERENCE_RE = re.compile(
    r"\b(?P<subject>"
    r"(?:(?:one|an?|the|single|a\s+single)\s+)?"
    r"(?:fictional\s+)?"
    r"(?:young\s+)?"
    r"(?:adult\s+)?"
    r"woman"
    r")"
    r"(?P<scope>\s+from\s+the\s+reference\s+image"
    r"(?:,\s*used\s+(?:only\s+)?for\s+[^.;\n]+)?"
    r")",
    re.IGNORECASE,
)

# The UGC pack normally places "product kept identical" immediately after the
# reference-image phrase, but the perfume prompt inserts pose/action wording
# between them. Capture that intervening wording and put it back after
# [[PRODUCT]] so only the reference mechanics disappear.
SECOND_REFERENCE_PRODUCT_RE = re.compile(
    r"\bthe\s+exact\s+"
    r"(?P<product>[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9-]+){0,3})\s+"
    r"product\s+shown\s+in\s+the\s+second\s+reference\s+image"
    r"(?P<presentation>[^.]{0,180}?)"
    r",\s*product\s+kept\s+identical\b",
    re.IGNORECASE,
)

SNEAKER_PRODUCT_IMAGE_RE = re.compile(
    r"\bthe\s+exact\s+"
    r"(?P<product>white\s+low-top\s+leather\s+sneakers)\s+"
    r"from\s+the\s+product\s+image,\s*kept\s+identical"
    r"(?P<details>\s*\([^)]*\))?",
    re.IGNORECASE,
)

JEWELRY_PRODUCT_IMAGE_RE = re.compile(
    r"\bthe\s+(?P<product>gold\s+pendant\s+necklace)\s+from\s+the\s+product\s+image,\s*"
    r"(?P<details>a\s+thin\s+chain\s+with\s+a\s+small\s+round\s+clear-stone\s+charm\s+"
    r"sitting\s+at\s+her\s+collarbone,\s*plus\s+the\s+matching\s+small\s+gold\s+hoop\s+"
    r"earrings\s+with\s+tiny\s+clear\s+stones),\s*kept\s+exactly\s+as\s+shown",
    re.IGNORECASE,
)

UGC_TOTE_SUBJECT_RE = re.compile(
    r"\bA\s+street-style\s+full-body\s+mirror\s+selfie"
    r"(?=\s+carrying\s+the\s+tote\s+on\s+her\s+shoulder\b)",
    re.IGNORECASE,
)


def _replace_matches(
    text: str,
    pattern: re.Pattern[str],
    placeholder: str,
) -> tuple[str, list[str]]:
    originals: list[str] = []

    def repl(match: re.Match[str]) -> str:
        originals.append(match.group(0))
        return placeholder

    return pattern.sub(repl, text), originals


def _subject_transform(
    text: str,
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    match = SUBJECT_RE.search(text[:500])
    if not match:
        return text, None, None

    candidate = match.group(0)
    split = SUBJECT_REFERENCE_SPLIT_RE.search(candidate)
    if split:
        subject_source = candidate[: split.start()].strip()
        scope_source = candidate[split.start():].strip()
        replacement = f"{SUBJECT_PLACEHOLDER} {REFERENCE_IDENTITY_SCOPE_PLACEHOLDER}"
        scope_slot: dict[str, Any] | None = {
            "placeholder": REFERENCE_IDENTITY_SCOPE_PLACEHOLDER,
            "original": [scope_source],
            "status": "auto",
        }
    else:
        subject_source = candidate
        replacement = SUBJECT_PLACEHOLDER
        scope_slot = None

    transformed = text[: match.start()] + replacement + text[match.end():]
    subject_slot = {
        "placeholder": SUBJECT_PLACEHOLDER,
        "original": subject_source,
        "source_candidate": candidate,
        "additional_originals": [],
        "status": "auto",
    }
    return transformed, subject_slot, scope_slot


def _replace_residual_subject_reference_scopes(
    text: str,
) -> tuple[str, list[str], list[str]]:
    subject_originals: list[str] = []
    scope_originals: list[str] = []

    def repl(match: re.Match[str]) -> str:
        subject_originals.append(match.group("subject").strip())
        scope_originals.append(match.group("scope").strip())
        return f"{SUBJECT_PLACEHOLDER} {REFERENCE_IDENTITY_SCOPE_PLACEHOLDER}"

    return RESIDUAL_SUBJECT_REFERENCE_RE.sub(repl, text), subject_originals, scope_originals


def _insert_known_missing_subject(
    prompt: dict[str, Any],
    text: str,
    subject_slot: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    if subject_slot is not None:
        return text, subject_slot
    if prompt.get("collection_slug") != "ugc-product-spotlight":
        return text, None

    transformed, count = UGC_TOTE_SUBJECT_RE.subn(
        lambda m: f"{m.group(0)} of {SUBJECT_PLACEHOLDER}", text, count=1
    )
    if count != 1:
        return text, None

    return transformed, {
        "placeholder": SUBJECT_PLACEHOLDER,
        "original": None,
        "source_candidate": None,
        "additional_originals": [],
        "status": "inserted",
        "note": (
            "Source tote prompt contains no explicit subject noun; inserted after "
            "'street-style full-body mirror selfie' by a collection-specific rule."
        ),
    }


def _normalized_product_type(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("-", " ")).strip().lower()


def _replace_products(text: str) -> tuple[str, list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []

    def second_reference_repl(match: re.Match[str]) -> str:
        product_type = _normalized_product_type(match.group("product"))
        presentation = match.group("presentation") or ""
        items.append(
            {
                "original": match.group(0),
                "product_type": product_type,
                "generic_description": product_type,
                "reference_source": "second_reference_image",
            }
        )
        return f"{PRODUCT_PLACEHOLDER}{presentation}"

    text = SECOND_REFERENCE_PRODUCT_RE.sub(second_reference_repl, text)

    def sneaker_repl(match: re.Match[str]) -> str:
        details = (match.group("details") or "").strip()
        generic = _normalized_product_type(match.group("product"))
        if details:
            generic = f"{generic} {details}"
        items.append(
            {
                "original": match.group(0),
                "product_type": "sneakers",
                "generic_description": generic,
                "reference_source": "product_image",
            }
        )
        return PRODUCT_PLACEHOLDER

    text = SNEAKER_PRODUCT_IMAGE_RE.sub(sneaker_repl, text)

    def jewelry_repl(match: re.Match[str]) -> str:
        items.append(
            {
                "original": match.group(0),
                "product_type": "jewelry",
                "generic_description": (
                    "gold pendant necklace, a thin chain with a small round clear-stone "
                    "charm sitting at her collarbone, plus matching small gold hoop "
                    "earrings with tiny clear stones"
                ),
                "reference_source": "product_image",
            }
        )
        return PRODUCT_PLACEHOLDER

    text = JEWELRY_PRODUCT_IMAGE_RE.sub(jewelry_repl, text)
    return text, items


def transform_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    original = prompt["prompt_original"]
    template, subject_slot, subject_scope_slot = _subject_transform(original)

    template, extra_subjects, extra_scopes = _replace_residual_subject_reference_scopes(
        template
    )
    if extra_subjects:
        if subject_slot is None:
            subject_slot = {
                "placeholder": SUBJECT_PLACEHOLDER,
                "original": extra_subjects[0],
                "source_candidate": f"{extra_subjects[0]} {extra_scopes[0]}",
                "additional_originals": extra_subjects[1:],
                "status": "auto",
            }
            extra_subjects = []
            extra_scopes = extra_scopes[1:]
        else:
            subject_slot.setdefault("additional_originals", []).extend(extra_subjects)

    if extra_scopes:
        if subject_scope_slot is None:
            subject_scope_slot = {
                "placeholder": REFERENCE_IDENTITY_SCOPE_PLACEHOLDER,
                "original": list(extra_scopes),
                "status": "auto",
            }
        else:
            subject_scope_slot["original"].extend(extra_scopes)

    template, subject_slot = _insert_known_missing_subject(
        prompt, template, subject_slot
    )

    template, identity_originals = _replace_matches(
        template, IDENTITY_RE, REFERENCE_IDENTITY_PLACEHOLDER
    )
    template, generation_originals = _replace_matches(
        template, REFERENCE_GENERATION_RE, REFERENCE_GENERATION_PLACEHOLDER
    )
    template, product_items = _replace_products(template)

    residual_reference_sentences = [
        sentence
        for sentence in split_sentences(template)
        if any(
            marker in sentence.casefold()
            for marker in ("reference image", "product image")
        )
    ]

    review_reasons: list[str] = []
    if subject_slot is None:
        review_reasons.append("no_subject_candidate")
    if residual_reference_sentences:
        review_reasons.append("residual_reference_language")

    slots: dict[str, Any] = {
        "subject": subject_slot,
        "reference_identity": {
            "placeholder": REFERENCE_IDENTITY_PLACEHOLDER,
            "original": identity_originals,
            "status": "auto" if identity_originals else "not_present",
        },
        "reference_identity_scope": subject_scope_slot
        or {
            "placeholder": REFERENCE_IDENTITY_SCOPE_PLACEHOLDER,
            "original": [],
            "status": "not_present",
        },
        "reference_generation": {
            "placeholder": REFERENCE_GENERATION_PLACEHOLDER,
            "original": generation_originals,
            "status": "auto" if generation_originals else "not_present",
        },
        "product": {
            "placeholder": PRODUCT_PLACEHOLDER,
            "items": product_items,
            "status": "auto" if product_items else "not_present",
        },
    }

    return {
        "id": prompt["id"],
        "source_index": prompt["source_index"],
        "collection": prompt["collection"],
        "collection_slug": prompt["collection_slug"],
        "source": {
            "character": prompt["character"],
            "model": prompt["model"],
            "url": prompt["source_url"],
            "image_url": prompt.get("image_url"),
            "image_alt": prompt.get("image_alt"),
            "prompt_sha256": prompt["prompt_sha256"],
        },
        "prompt_original": original,
        "prompt_template": template,
        "slots": slots,
        "curation": {
            "keep": None,
            "reviewed": False,
            "favorite": False,
            "notes": "",
            "review_required": bool(review_reasons),
            "review_reasons": review_reasons,
            "residual_reference_sentences": residual_reference_sentences,
        },
    }


def build_curated(library_path: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    source = json.loads(library_path.read_text(encoding="utf-8"))
    source_prompts: list[dict[str, Any]] = source.get("prompts", [])
    curated_prompts = [transform_prompt(p) for p in source_prompts]

    by_collection: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in curated_prompts:
        by_collection[p["collection_slug"]].append(p)

    counts = Counter()
    review_reasons = Counter()
    product_sources = Counter()
    for p in curated_prompts:
        slots = p["slots"]
        subject = slots["subject"]
        if subject:
            counts["subject_ready"] += 1
            if subject.get("status") == "inserted":
                counts["subject_inserted"] += 1
            else:
                counts["subject_replaced"] += 1
        if slots["reference_identity"]["original"]:
            counts["reference_identity_replaced"] += 1
        if slots["reference_identity_scope"]["original"]:
            counts["reference_identity_scope_extracted"] += 1
        if slots["reference_generation"]["original"]:
            counts["reference_generation_replaced"] += 1
        if slots["product"]["items"]:
            counts["product_prompt_normalized"] += 1
            counts["product_item_normalized"] += len(slots["product"]["items"])
            for item in slots["product"]["items"]:
                product_sources[item["reference_source"]] += 1
        if p["curation"]["review_required"]:
            counts["review_required"] += 1
            review_reasons.update(p["curation"]["review_reasons"])
        else:
            counts["auto_ready"] += 1

    curated_root = out_dir / "curated"
    collections_dir = curated_root / "collections"

    for slug, prompts in sorted(by_collection.items()):
        collection_obj = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "collection": {
                "name": prompts[0]["collection"],
                "slug": slug,
                "prompt_count": len(prompts),
            },
            "prompts": prompts,
        }
        write_json(collections_dir / f"{slug}.json", collection_obj)

    curated_obj = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "source_library": str(library_path),
        "source": deepcopy(source.get("source", {})),
        "stats": {
            "prompt_count": len(curated_prompts),
            "collection_count": len(by_collection),
            **dict(sorted(counts.items())),
            "product_reference_sources": dict(sorted(product_sources.items())),
        },
        "placeholders": {
            "subject": SUBJECT_PLACEHOLDER,
            "reference_identity": REFERENCE_IDENTITY_PLACEHOLDER,
            "reference_identity_scope": REFERENCE_IDENTITY_SCOPE_PLACEHOLDER,
            "reference_generation": REFERENCE_GENERATION_PLACEHOLDER,
            "product": PRODUCT_PLACEHOLDER,
        },
        "prompts": curated_prompts,
    }
    library_out = curated_root / "library.json"
    write_json(library_out, curated_obj)

    review_items = [
        {
            "id": p["id"],
            "collection": p["collection"],
            "source_index": p["source_index"],
            "reasons": p["curation"]["review_reasons"],
            "residual_reference_sentences": p["curation"][
                "residual_reference_sentences"
            ],
            "prompt_original": p["prompt_original"],
            "prompt_template": p["prompt_template"],
        }
        for p in curated_prompts
        if p["curation"]["review_required"]
    ]

    report_obj = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "source_library": str(library_path),
        "summary": {
            "prompt_count": len(curated_prompts),
            "collection_count": len(by_collection),
            **dict(sorted(counts.items())),
            "product_reference_sources": dict(sorted(product_sources.items())),
            "review_reasons": dict(sorted(review_reasons.items())),
        },
        "review_items": review_items,
        "note": (
            "Phase 2 is non-destructive: prompt_original remains unchanged. "
            "Reference mechanics are moved into semantic slots in prompt_template."
        ),
    }
    report_json = out_dir / "reports" / "transformation_report.json"
    write_json(report_json, report_obj)

    s = report_obj["summary"]
    lines = [
        "# HearmemanAI Phase-2 transformation report",
        "",
        f"Generated: {report_obj['generated_at']}",
        "",
        "> `prompt_original` remains immutable. All automatic edits are written only to `prompt_template`.",
        "",
        "## Summary",
        "",
        f"- Prompts: **{s['prompt_count']}**",
        f"- Collections: **{s['collection_count']}**",
        f"- Subject placeholder ready: **{s.get('subject_ready', 0)}**",
        f"  - extracted/replaced: **{s.get('subject_replaced', 0)}**",
        f"  - explicitly inserted: **{s.get('subject_inserted', 0)}**",
        f"- Identity clause replaced: **{s.get('reference_identity_replaced', 0)}**",
        f"- Subject-attached reference scope extracted: **{s.get('reference_identity_scope_extracted', 0)}**",
        f"- Reference-generation instruction replaced: **{s.get('reference_generation_replaced', 0)}**",
        f"- Product prompts normalized: **{s.get('product_prompt_normalized', 0)}**",
        f"- Product items normalized: **{s.get('product_item_normalized', 0)}**",
        f"- Auto-ready: **{s.get('auto_ready', 0)}**",
        f"- Review required: **{s.get('review_required', 0)}**",
        "",
        "### Product reference sources",
        "",
    ]
    for source_name, count in s.get("product_reference_sources", {}).items():
        lines.append(f"- `{source_name}`: {count}")

    lines += ["", "### Review reasons", ""]
    if s.get("review_reasons"):
        for reason, count in s["review_reasons"].items():
            lines.append(f"- `{reason}`: {count}")
    else:
        lines.append("_None._")

    lines += [
        "",
        "## Placeholder semantics",
        "",
        f"- `{SUBJECT_PLACEHOLDER}` — subject phrase / LoRA trigger target.",
        f"- `{REFERENCE_IDENTITY_PLACEHOLDER}` — standard identity-preservation instruction.",
        f"- `{REFERENCE_IDENTITY_SCOPE_PLACEHOLDER}` — subject-attached `from the reference image...` scope.",
        f"- `{REFERENCE_GENERATION_PLACEHOLDER}` — reference-only / no-compositing generation instruction.",
        f"- `{PRODUCT_PLACEHOLDER}` — product identity. Slot metadata retains the original reference-aware wording, product type/generic description, and whether it came from `second_reference_image` or `product_image`.",
        "",
        "## Review items",
        "",
    ]
    if not review_items:
        lines.append("_None._")
    else:
        for item in review_items:
            lines.append(
                f"- `{item['id']}` — {item['collection']} — "
                + ", ".join(f"`{r}`" for r in item["reasons"])
            )

    report_md = out_dir / "reports" / "transformation_report.md"
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {library_out}")
    print(f"Wrote {len(by_collection)} collection file(s) under {collections_dir}")
    print(f"Wrote {report_json}")
    print(f"Wrote {report_md}")
    print(
        f"Phase 2: {counts.get('auto_ready', 0)} auto-ready; "
        f"{counts.get('review_required', 0)} require review"
    )
    return library_out, report_json, report_md


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
        help="Phase-1 library.json (default: <out>/source/hearmemanai/library.json)",
    )
    args = ap.parse_args()

    library_path = args.library or (
        args.out / "source" / "hearmemanai" / "library.json"
    )
    if not library_path.exists():
        ap.error(f"library not found: {library_path}; run Phase 1 ingest first")

    build_curated(library_path, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
