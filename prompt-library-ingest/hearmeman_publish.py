#!/usr/bin/env python3
"""Publish a compiled t2i/i2i export into the repo runtime library."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from hearmeman_ingest_core import utc_now, write_json

RUNTIME_MODES = ("t2i", "i2i")
SUBJECT_PLACEHOLDER = "[[SUBJECT]]"
PLACEHOLDER_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]")


def _safe_component(value: str, label: str) -> str:
    value = value.strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{label} must be a single path component: {value!r}")
    return value


def _safe_relative(base: Path, rel: str) -> Path:
    target = (base / rel).resolve()
    base = base.resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Manifest file escapes export bundle: {rel}") from exc
    return target


def validate_export(source_dir: Path, *, mode: str | None = None) -> dict[str, Any]:
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Export manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mode is not None and manifest.get("mode") != mode:
        raise ValueError(
            f"Manifest mode {manifest.get('mode')!r} does not match {mode!r}"
        )
    if manifest.get("subject_deferred") is not True:
        raise ValueError("Runtime export must defer [[SUBJECT]] substitution")
    if manifest.get("subject_placeholder") != SUBJECT_PLACEHOLDER:
        raise ValueError(
            f"Runtime export subject_placeholder must be {SUBJECT_PLACEHOLDER}"
        )

    items = manifest.get("items")
    if not isinstance(items, list):
        raise ValueError("manifest.items must be a list")
    if manifest.get("prompt_count") != len(items):
        raise ValueError(
            f"prompt_count={manifest.get('prompt_count')} but items={len(items)}"
        )

    for item in items:
        rel = item.get("file")
        if not isinstance(rel, str) or not rel:
            raise ValueError("Manifest item missing file")
        path = _safe_relative(source_dir, rel)
        if not path.is_file():
            raise FileNotFoundError(f"Prompt file missing: {path}")
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"Prompt file is empty: {path}")
        placeholders = set(PLACEHOLDER_RE.findall(text))
        unexpected = sorted(placeholders - {SUBJECT_PLACEHOLDER})
        if unexpected:
            raise ValueError(
                f"Unexpected unresolved placeholder(s) in {path}: "
                + ", ".join(unexpected)
            )
        if SUBJECT_PLACEHOLDER not in placeholders:
            raise ValueError(f"Published runtime prompt has no {SUBJECT_PLACEHOLDER}: {path}")
    return manifest


def rebuild_runtime_index(runtime_root: Path) -> Path:
    entries: list[dict[str, Any]] = []
    for mode in RUNTIME_MODES:
        path = runtime_root / mode / "manifest.json"
        if not path.is_file():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append(
            {
                "manifest": f"{mode}/manifest.json",
                "mode": mode,
                "prompt_count": manifest.get("prompt_count"),
                "published_at": manifest.get("published_at"),
            }
        )
    index = {
        "schema_version": 2,
        "generated_at": utc_now(),
        "bundle_count": len(entries),
        "bundles": entries,
    }
    path = runtime_root / "index.json"
    write_json(path, index)
    return path


def publish_export(
    source_dir: Path,
    runtime_root: Path,
    *,
    mode: str,
) -> Path:
    mode = _safe_component(mode, "mode")
    if mode not in RUNTIME_MODES:
        raise ValueError(f"mode must be one of: {', '.join(RUNTIME_MODES)}")

    source_dir = source_dir.resolve()
    runtime_root = runtime_root.resolve()
    manifest = validate_export(source_dir, mode=mode)

    destination = runtime_root / mode
    runtime_root.mkdir(parents=True, exist_ok=True)
    tmp = runtime_root / f".tmp-{mode}"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(source_dir, tmp)

    copied_manifest_path = tmp / "manifest.json"
    copied = json.loads(copied_manifest_path.read_text(encoding="utf-8"))
    copied["published_at"] = utc_now()
    copied["runtime_bundle"] = True
    copied["runtime_manifest"] = f"{mode}/manifest.json"
    write_json(copied_manifest_path, copied)

    if destination.exists():
        shutil.rmtree(destination)
    tmp.rename(destination)
    rebuild_runtime_index(runtime_root)
    return destination / "manifest.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("prompt-library"),
        help="Prompt-library root containing exports/",
    )
    ap.add_argument("--mode", choices=RUNTIME_MODES, required=True)
    ap.add_argument(
        "--runtime-root",
        type=Path,
        help="Destination runtime-library root (default: repo/runtime-library)",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    runtime_root = args.runtime_root or (repo_root / "runtime-library")
    source_dir = args.out / "exports" / args.mode
    manifest = publish_export(source_dir, runtime_root, mode=args.mode)
    print(f"Published {manifest}")
    print(f"Runtime index: {runtime_root / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
