import json
from pathlib import Path

from hearmeman_publish import publish_export, validate_export


def make_export(root: Path) -> Path:
    source = root / "exports" / "krea2-lora" / "demo"
    prompt = source / "collections" / "one" / "001__alice__x.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Rendered prompt\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "profile": "krea2-lora",
        "export_name": "demo",
        "subject": "sH1VX woman",
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
    manifest_path = publish_export(
        source, runtime, profile="krea2-lora", name="demo"
    )
    published = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert published["runtime_bundle"] is True
    assert published["prompt_count"] == 1
    assert (manifest_path.parent / published["items"][0]["file"]).is_file()

    index = json.loads((runtime / "index.json").read_text(encoding="utf-8"))
    assert index["bundle_count"] == 1
    assert index["bundles"][0]["manifest"] == "krea2-lora/demo/manifest.json"


def test_validate_export_rejects_unresolved_placeholder(tmp_path: Path):
    source = make_export(tmp_path)
    item = source / "collections" / "one" / "001__alice__x.txt"
    item.write_text("Bad [[SUBJECT]]\n", encoding="utf-8")
    try:
        validate_export(source)
    except ValueError as exc:
        assert "Unresolved placeholder" in str(exc)
    else:
        raise AssertionError("unresolved placeholder should fail")
