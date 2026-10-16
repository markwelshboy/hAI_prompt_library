import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import comfyui_nodes


def make_bundle(root: Path) -> str:
    run = root / "t2i"
    prompt_dir = run / "collections" / "one"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "001__alice__a.txt").write_text(
        "Prompt [[SUBJECT]] A\n", encoding="utf-8"
    )
    (prompt_dir / "002__bob__b.txt").write_text(
        "Prompt [[SUBJECT]] B\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": 2,
        "mode": "t2i",
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
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return "t2i/manifest.json"


def test_select_by_index_and_prompt_id_resolves_subject(tmp_path: Path, monkeypatch):
    label = make_bundle(tmp_path)
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))

    node = comfyui_nodes.HAIPromptSelect()
    out = node.select(label, "sH1VX woman", "index", 1, 0, "", "", True)
    assert out[0] == "Prompt sH1VX woman B"
    assert out[1] == "p-b"
    assert out[5] == 1
    assert out[6] == 2

    out = node.select(label, "one adult woman", "prompt_id", 0, 0, "", "p-a", True)
    assert out[0] == "Prompt one adult woman A"
    assert out[1] == "p-a"


def test_select_random_is_seed_deterministic(tmp_path: Path, monkeypatch):
    label = make_bundle(tmp_path)
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    a = node.select(label, "woman", "random", 0, 123, "", "", True)
    b = node.select(label, "woman", "random", 0, 123, "", "", True)
    assert a[1] == b[1]


def test_batch_returns_comfy_lists_with_subject_resolved(tmp_path: Path, monkeypatch):
    label = make_bundle(tmp_path)
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptBatch()
    prompts, ids, collections, chars, models, total = node.batch(
        label, "testTrigger woman", "one", "manifest", 0, 0, 0, 1
    )
    assert prompts == ["Prompt testTrigger woman A", "Prompt testTrigger woman B"]
    assert ids == ["p-a", "p-b"]
    assert collections == ["One", "One"]
    assert total == 2


def test_empty_subject_is_rejected(tmp_path: Path, monkeypatch):
    label = make_bundle(tmp_path)
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    try:
        node.select(label, "   ", "index", 0, 0, "", "", True)
    except ValueError as exc:
        assert "subject must not be empty" in str(exc)
    else:
        raise AssertionError("empty subject should fail")


def test_manifest_rejects_path_escape(tmp_path: Path, monkeypatch):
    run = tmp_path / "bad"
    run.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "mode": "t2i",
        "subject_placeholder": "[[SUBJECT]]",
        "subject_deferred": True,
        "prompt_count": 1,
        "items": [{"file": "../outside.txt", "prompt_id": "x"}],
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    try:
        node.select("bad/manifest.json", "woman", "index", 0, 0, "", "", True)
    except ValueError as exc:
        assert "escapes bundle" in str(exc)
    else:
        raise AssertionError("path escape should fail")


def test_node_rejects_unexpected_runtime_placeholder(tmp_path: Path, monkeypatch):
    label = make_bundle(tmp_path)
    prompt = tmp_path / "t2i" / "collections" / "one" / "001__alice__a.txt"
    prompt.write_text("Prompt [[SUBJECT]] [[PRODUCT]]\n", encoding="utf-8")
    monkeypatch.setenv("HAI_PROMPT_LIBRARY_ROOT", str(tmp_path))
    node = comfyui_nodes.HAIPromptSelect()
    try:
        node.select(label, "woman", "index", 0, 0, "", "", True)
    except ValueError as exc:
        assert "unresolved placeholder" in str(exc)
    else:
        raise AssertionError("unexpected runtime placeholder should fail")
