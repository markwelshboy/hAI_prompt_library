#!/usr/bin/env python3
"""Publish a rendered prompt export into the repo's ComfyUI runtime library."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from hearmeman_ingest_core import utc_now, write_json


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


def validate_export(source_dir: Path) -> dict[str, Any]:
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Export manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        if "[[" in text:
            raise ValueError(f"Unresolved placeholder in published prompt: {path}")
    return manifest


def rebuild_runtime_index(runtime_root: Path) -> Path:
    entries: list[dict[str, Any]] = []
    for path in sorted(runtime_root.rglob("manifest.json")):
        if ".tmp-" in path.as_posix():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append(
            {
                "manifest": path.relative_to(runtime_root).as_posix(),
                "profile": manifest.get("profile"),
                "export_name": manifest.get("export_name"),
                "subject": manifest.get("subject"),
                "prompt_count": manifest.get("prompt_count"),
                "published_at": manifest.get("published_at"),
            }
        )
    index = {
        "schema_version": 1,
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
    profile: str,
    name: str,
) -> Path:
    profile = _safe_component(profile, "profile")
    name = _safe_component(name, "name")
    source_dir = source_dir.resolve()
    runtime_root = runtime_root.resolve()
    manifest = validate_export(source_dir)

    if manifest.get("profile") != profile:
        raise ValueError(
            f"Manifest profile {manifest.get('profile')!r} does not match {profile!r}"
        )

    destination = runtime_root / profile / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.parent / f".tmp-{destination.name}"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(source_dir, tmp)

    copied_manifest_path = tmp / "manifest.json"
    copied = json.loads(copied_manifest_path.read_text(encoding="utf-8"))
    copied["published_at"] = utc_now()
    copied["runtime_bundle"] = True
    copied["runtime_manifest"] = f"{profile}/{name}/manifest.json"
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
    ap.add_argument("--profile", required=True)
    ap.add_argument("--name", required=True, help="Rendered export name")
    ap.add_argument(
        "--runtime-root",
        type=Path,
        help="Destination runtime-library root (default: repo/runtime-library)",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    runtime_root = args.runtime_root or (repo_root / "runtime-library")
    source_dir = args.out / "exports" / args.profile / args.name
    manifest = publish_export(
        source_dir, runtime_root, profile=args.profile, name=args.name
    )
    print(f"Published {manifest}")
    print(f"Runtime index: {runtime_root / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
