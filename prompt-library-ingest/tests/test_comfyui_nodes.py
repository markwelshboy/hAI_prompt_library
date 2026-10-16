import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import comfyui_nodes


def make_bundle(root: Path, mode: str = "t2i") -> Path:
    run = root / mode
    prompt_dir = run / "collections" / "one"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "001__alice__a.txt").write_text(
        f"{mode.upper()} Prompt [[SUBJECT]] A\n", encoding="utf-8"
    )
    (prompt_dir / "002__bob__b.txt").write_text(
        f"{mode.upper()} Prompt [[SUBJECT]] B\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": 2,
        "mode": mode,
        "subject_placeholder": "[[SUBJECT]]",
        "subject_deferred": True,
        "prompt_count": 2,
        "items": [
            {
                "prompt_id": "p-a",
                "collection": "One",
                "collection_slug": "one",
                "source_character": "Alice",
                "source_model": "nano-banana-2",
                "file": "collections/one/001__alice__a.txt",
            },
            {
                "prompt_id": "p-b",
                "collection": "One",
                "collection_slug": "one",
                "source_character": "Bob",
                "source_model": "gpt-image-2",
                "file": "collections/one/002__bob__b.txt",
            },
        ],
    }
    manifest_path = run / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_node_ui_exposes_semantic_runtime_modes():
    select_required = comfyui_nodes.HAIPromptSelect.INPUT_TYPES()["required"]
    batch_required = comfyui_nodes.HAIPromptBatch.INPUT_TYPES()["required"]

    assert select_required["mode"][0] == ("t2i", "i2i")
    assert batch_required["mode"][0] == ("t2i", "i2i")
    assert select_required["selection"][0] == ["index", "random", "prompt_id"]
    assert "manifest" not in select_required
    assert "manifest" not in batch_required


def test_select_by_index_and_prompt_id_resolves_subject(tmp_path: Path, monkeypatch):
    make_bundle(tmp_path, "t2i")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))

    node = comfyui_nodes.HAIPromptSelect()
    out = node.select("t2i", "sH1VX woman", "index", 1, 0, "", "", True)
    assert out[0] == "T2I Prompt sH1VX woman B"
    assert out[1] == "p-b"
    assert out[5] == 1
    assert out[6] == 2

    out = node.select(
        "t2i", "one adult woman", "prompt_id", 0, 0, "", "p-a", True
    )
    assert out[0] == "T2I Prompt one adult woman A"
    assert out[1] == "p-a"


def test_i2i_mode_resolves_i2i_manifest(tmp_path: Path, monkeypatch):
    make_bundle(tmp_path, "t2i")
    make_bundle(tmp_path, "i2i")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))

    node = comfyui_nodes.HAIPromptSelect()
    out = node.select("i2i", "woman", "index", 0, 0, "", "", True)
    assert out[0] == "I2I Prompt woman A"


def test_select_random_is_seed_deterministic(tmp_path: Path, monkeypatch):
    make_bundle(tmp_path, "t2i")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    a = node.select("t2i", "woman", "random", 0, 123, "", "", True)
    b = node.select("t2i", "woman", "random", 0, 123, "", "", True)
    assert a[1] == b[1]


def test_batch_returns_comfy_lists_with_subject_resolved(tmp_path: Path, monkeypatch):
    make_bundle(tmp_path, "t2i")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptBatch()
    prompts, ids, collections, chars, models, total = node.batch(
        "t2i", "testTrigger woman", "one", "manifest", 0, 0, 0, 1
    )
    assert prompts == [
        "T2I Prompt testTrigger woman A",
        "T2I Prompt testTrigger woman B",
    ]
    assert ids == ["p-a", "p-b"]
    assert collections == ["One", "One"]
    assert total == 2


def test_empty_subject_is_rejected(tmp_path: Path, monkeypatch):
    make_bundle(tmp_path, "t2i")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    try:
        node.select("t2i", "   ", "index", 0, 0, "", "", True)
    except ValueError as exc:
        assert "subject must not be empty" in str(exc)
    else:
        raise AssertionError("empty subject should fail")


def test_missing_runtime_mode_is_reported(tmp_path: Path, monkeypatch):
    make_bundle(tmp_path, "t2i")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    try:
        node.select("i2i", "woman", "index", 0, 0, "", "", True)
    except FileNotFoundError as exc:
        assert "No published 'i2i' prompt manifest found" in str(exc)
    else:
        raise AssertionError("missing i2i bundle should fail")


def test_manifest_mode_must_match_requested_mode(tmp_path: Path, monkeypatch):
    manifest_path = make_bundle(tmp_path, "t2i")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mode"] = "i2i"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))

    node = comfyui_nodes.HAIPromptSelect()
    try:
        node.select("t2i", "woman", "index", 0, 0, "", "", True)
    except ValueError as exc:
        assert "does not match requested mode" in str(exc)
    else:
        raise AssertionError("manifest mode mismatch should fail")


def test_manifest_rejects_path_escape(tmp_path: Path, monkeypatch):
    manifest_path = make_bundle(tmp_path, "t2i")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["prompt_count"] = 1
    manifest["items"] = [{"file": "../outside.txt", "prompt_id": "x"}]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    try:
        node.select("t2i", "woman", "index", 0, 0, "", "", True)
    except ValueError as exc:
        assert "escapes bundle" in str(exc)
    else:
        raise AssertionError("path escape should fail")


def test_node_rejects_unexpected_runtime_placeholder(tmp_path: Path, monkeypatch):
    make_bundle(tmp_path, "t2i")
    prompt = tmp_path / "t2i" / "collections" / "one" / "001__alice__a.txt"
    prompt.write_text("Prompt [[SUBJECT]] [[PRODUCT]]\n", encoding="utf-8")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    try:
        node.select("t2i", "woman", "index", 0, 0, "", "", True)
    except ValueError as exc:
        assert "unresolved placeholder" in str(exc)
    else:
        raise AssertionError("unexpected runtime placeholder should fail")
