#!/usr/bin/env python3
"""Build the Phase-2 curated prompt library from a Phase-1 library.json.

The source layer remains immutable.  This tool creates a separate curated layer
with semantic placeholders and review metadata:

  [[SUBJECT]]
  [[REFERENCE_IDENTITY]]
  [[REFERENCE_IDENTITY_SCOPE]]
  [[REFERENCE_GENERATION]]

Second-reference/product wording is intentionally *not* rewritten yet.  Those
few prompts are retained verbatim in the template and sent to a review queue so
scene/action language is not accidentally discarded.
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

# This exact semantic clause accounts for the overwhelming majority of the
# library, including a small number of prompts where it is embedded inline in a
# longer sentence rather than standing alone.
IDENTITY_RE = re.compile(
    r"preserve\s+the\s+character\s+identity\s+from\s+the\s+reference\s+image,\s*"
    r"keeping\s+their\s+exact\s+hair\s+color,\s*hairstyle,\s*eye\s+color,\s*"
    r"skin\s+tone,\s*face\s+shape,\s*and\s+body\s+shape\.?",
    re.IGNORECASE,
)

# The audit found a small family of multi-panel instructions beginning with
# "Use the reference image ONLY..." and ending with an instruction not to
# preserve/composite the source background.  Keep the original wording in the
# slot, but make the template model-neutral.
REFERENCE_GENERATION_RE = re.compile(
    r"Use\s+the\s+reference\s+image\s+ONLY\s+for\s+her\s+[^.]{1,700}?background\.",
    re.IGNORECASE,
)

SUBJECT_REFERENCE_SPLIT_RE = re.compile(
    r"\s+from\s+the\s+reference\s+image\b", re.IGNORECASE
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


def _subject_transform(text: str) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """Replace the first subject declaration and separate any ref-image suffix."""
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
        "status": "auto",
    }
    return transformed, subject_slot, scope_slot


def transform_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    original = prompt["prompt_original"]
    template, subject_slot, subject_scope_slot = _subject_transform(original)

    template, identity_originals = _replace_matches(
        template, IDENTITY_RE, REFERENCE_IDENTITY_PLACEHOLDER
    )
    template, generation_originals = _replace_matches(
        template, REFERENCE_GENERATION_RE, REFERENCE_GENERATION_PLACEHOLDER
    )

    product_reference_sentences = [
        sentence
        for sentence in split_sentences(original)
        if "second reference image" in sentence.casefold()
    ]

    residual_reference_sentences = [
        sentence
        for sentence in split_sentences(template)
        if "reference image" in sentence.casefold()
    ]

    review_reasons: list[str] = []
    if subject_slot is None:
        review_reasons.append("no_subject_candidate")
    if product_reference_sentences:
        review_reasons.append("second_reference_product")
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
        "reference_product": {
            "placeholder": "[[REFERENCE_PRODUCT]]",
            "original": product_reference_sentences,
            "status": "review" if product_reference_sentences else "not_present",
            "note": (
                "Not automatically replaced: these sentences also carry useful "
                "product/action/scene wording."
                if product_reference_sentences
                else ""
            ),
        },
    }

    result = {
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
        # Immutable source copy.  Never derive this from prompt_template.
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
    return result


def build_curated(library_path: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    source = json.loads(library_path.read_text(encoding="utf-8"))
    source_prompts: list[dict[str, Any]] = source.get("prompts", [])
    curated_prompts = [transform_prompt(p) for p in source_prompts]

    by_collection: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in curated_prompts:
        by_collection[p["collection_slug"]].append(p)

    counts = Counter()
    review_reasons = Counter()
    for p in curated_prompts:
        slots = p["slots"]
        if slots["subject"]:
            counts["subject_replaced"] += 1
        if slots["reference_identity"]["original"]:
            counts["reference_identity_replaced"] += 1
        if slots["reference_identity_scope"]["original"]:
            counts["reference_identity_scope_extracted"] += 1
        if slots["reference_generation"]["original"]:
            counts["reference_generation_replaced"] += 1
        if slots["reference_product"]["original"]:
            counts["second_reference_product_review"] += 1
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
        },
        "placeholders": {
            "subject": SUBJECT_PLACEHOLDER,
            "reference_identity": REFERENCE_IDENTITY_PLACEHOLDER,
            "reference_identity_scope": REFERENCE_IDENTITY_SCOPE_PLACEHOLDER,
            "reference_generation": REFERENCE_GENERATION_PLACEHOLDER,
            "reference_product_reserved": "[[REFERENCE_PRODUCT]]",
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
            "residual_reference_sentences": p["curation"]["residual_reference_sentences"],
            "product_reference_sentences": p["slots"]["reference_product"]["original"],
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
            "review_reasons": dict(sorted(review_reasons.items())),
        },
        "review_items": review_items,
        "note": (
            "Phase 2 is conservative. prompt_original remains unchanged; second-reference "
            "product instructions are review-only and are not rewritten automatically."
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
        f"- Subject replaced: **{s.get('subject_replaced', 0)}**",
        f"- Identity clause replaced: **{s.get('reference_identity_replaced', 0)}**",
        f"- Subject-attached reference scope extracted: **{s.get('reference_identity_scope_extracted', 0)}**",
        f"- Reference-generation instruction replaced: **{s.get('reference_generation_replaced', 0)}**",
        f"- Second-reference/product prompts held for review: **{s.get('second_reference_product_review', 0)}**",
        f"- Auto-ready: **{s.get('auto_ready', 0)}**",
        f"- Review required: **{s.get('review_required', 0)}**",
        "",
        "### Review reasons",
        "",
    ]
    for reason, count in s.get("review_reasons", {}).items():
        lines.append(f"- `{reason}`: {count}")

    lines += [
        "",
        "## Placeholder semantics",
        "",
        f"- `{SUBJECT_PLACEHOLDER}` — source subject phrase; render with a LoRA trigger / desired subject.",
        f"- `{REFERENCE_IDENTITY_PLACEHOLDER}` — standard identity-preservation instruction.",
        f"- `{REFERENCE_IDENTITY_SCOPE_PLACEHOLDER}` — subject-attached `from the reference image...` scope.",
        f"- `{REFERENCE_GENERATION_PLACEHOLDER}` — reference-only / no-compositing generation instruction.",
        "- `[[REFERENCE_PRODUCT]]` is reserved but **not auto-inserted yet**; the seven second-reference product cases remain intact and are queued for review.",
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
