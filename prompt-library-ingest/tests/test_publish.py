import json
from pathlib import Path

from hearmeman_publish import publish_export, validate_export


def make_export(root: Path, mode: str = "t2i") -> Path:
    source = root / "exports" / mode
    prompt = source / "collections" / "one" / "001__alice__x.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Rendered [[SUBJECT]] prompt\n", encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "mode": mode,
        "subject_placeholder": "[[SUBJECT]]",
        "subject_deferred": True,
        "render_policy": {
            "reference_images": "omit" if mode == "t2i" else "preserve",
            "products": "generic" if mode == "t2i" else "reference",
        },
        "prompt_count": 1,
        "items": [
            {
                "prompt_id": "p1",
                "collection": "One",
                "collection_slug": "one",
                "source_character": "Alice",
                "source_model": "nano-banana-2",
                "file": "collections/one/001__alice__x.txt",
            }
        ],
    }
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return source


def test_publish_copies_validated_bundle_and_builds_index(tmp_path: Path):
    source = make_export(tmp_path)
    runtime = tmp_path / "runtime-library"
    manifest_path = publish_export(source, runtime, mode="t2i")
    published = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert published["runtime_bundle"] is True
    assert published["runtime_manifest"] == "t2i/manifest.json"
    assert published["prompt_count"] == 1
    assert (manifest_path.parent / published["items"][0]["file"]).is_file()

    index = json.loads((runtime / "index.json").read_text(encoding="utf-8"))
    assert index["schema_version"] == 2
    assert index["bundle_count"] == 1
    assert index["bundles"][0]["manifest"] == "t2i/manifest.json"
    assert index["bundles"][0]["mode"] == "t2i"


def test_validate_export_allows_only_deferred_subject_placeholder(tmp_path: Path):
    source = make_export(tmp_path)
    validate_export(source, mode="t2i")

    item = source / "collections" / "one" / "001__alice__x.txt"
    item.write_text("Bad [[SUBJECT]] [[PRODUCT]]\n", encoding="utf-8")
    try:
        validate_export(source, mode="t2i")
    except ValueError as exc:
        assert "Unexpected unresolved placeholder" in str(exc)
    else:
        raise AssertionError("non-subject placeholder should fail")


def test_validate_export_requires_deferred_subject_placeholder(tmp_path: Path):
    source = make_export(tmp_path)
    item = source / "collections" / "one" / "001__alice__x.txt"
    item.write_text("No deferred subject here\n", encoding="utf-8")
    try:
        validate_export(source, mode="t2i")
    except ValueError as exc:
        assert "has no [[SUBJECT]]" in str(exc)
    else:
        raise AssertionError("missing subject placeholder should fail")


def test_publish_rejects_unknown_mode(tmp_path: Path):
    source = make_export(tmp_path)
    runtime = tmp_path / "runtime-library"
    try:
        publish_export(source, runtime, mode="../escape")
    except ValueError as exc:
        assert "single path component" in str(exc)
    else:
        raise AssertionError("path-like mode should fail")


def test_runtime_index_ignores_legacy_nested_manifests(tmp_path: Path):
    source = make_export(tmp_path, mode="i2i")
    runtime = tmp_path / "runtime-library"
    legacy = runtime / "qwen-reference" / "qwen-all"
    legacy.mkdir(parents=True)
    (legacy / "manifest.json").write_text("{}", encoding="utf-8")

    publish_export(source, runtime, mode="i2i")
    index = json.loads((runtime / "index.json").read_text(encoding="utf-8"))
    assert index["bundle_count"] == 1
    assert index["bundles"][0]["manifest"] == "i2i/manifest.json"
