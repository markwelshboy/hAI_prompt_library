import json
from pathlib import Path

import pytest

from hearmeman_render import RenderError, export_prompts, render_prompt


IDENTITY = (
    "Preserve the character identity from the reference image, keeping their exact "
    "hair color, hairstyle, eye color, skin tone, face shape, and body shape."
)
SCOPE = "from the reference image, used only for identity, face, hair and natural expression"
GENERATION = (
    "Use the reference image ONLY for her face, hair color and texture, and natural "
    "features; keep her identity identical across all three panels; generate NEW "
    "native selfies and do NOT paste, cut out, composite, or preserve the reference's "
    "body, clothing, pose, or background."
)


def curated_prompt(
    *,
    ident: str = "hmm-test-abc123",
    template: str | None = None,
    original: str = "Original prompt text.",
    product_items: list[dict] | None = None,
    keep=None,
    favorite: bool = False,
) -> dict:
    return {
        "id": ident,
        "source_index": 0,
        "collection": "Test Collection",
        "collection_slug": "test-collection",
        "source": {
            "character": "Alice",
            "model": "nano-banana-2",
            "url": "https://example.test/",
            "image_url": None,
            "image_alt": None,
            "prompt_sha256": "deadbeef",
        },
        "prompt_original": original,
        "prompt_template": template
        or (
            "Candid photo of [[SUBJECT]] [[REFERENCE_IDENTITY_SCOPE]]. "
            "[[REFERENCE_IDENTITY]] Holding [[PRODUCT]] toward camera. "
            "[[REFERENCE_GENERATION]]"
        ),
        "slots": {
            "subject": {
                "placeholder": "[[SUBJECT]]",
                "original": "one adult woman",
                "status": "auto",
            },
            "reference_identity": {
                "placeholder": "[[REFERENCE_IDENTITY]]",
                "original": [IDENTITY],
                "status": "auto",
            },
            "reference_identity_scope": {
                "placeholder": "[[REFERENCE_IDENTITY_SCOPE]]",
                "original": [SCOPE],
                "status": "auto",
            },
            "reference_generation": {
                "placeholder": "[[REFERENCE_GENERATION]]",
                "original": [GENERATION],
                "status": "auto",
            },
            "product": {
                "placeholder": "[[PRODUCT]]",
                "items": product_items
                if product_items is not None
                else [
                    {
                        "original": (
                            "the exact tumbler product shown in the second reference "
                            "image, product kept identical"
                        ),
                        "product_type": "tumbler",
                        "generic_description": "tumbler",
                        "reference_source": "second_reference_image",
                    }
                ],
                "status": "auto",
            },
        },
        "curation": {
            "keep": keep,
            "reviewed": False,
            "favorite": favorite,
            "notes": "",
            "review_required": False,
            "review_reasons": [],
            "residual_reference_sentences": [],
        },
    }


def test_t2i_omits_reference_slots_uses_generic_product_and_defers_subject():
    prompt = curated_prompt()
    rendered = render_prompt(prompt, "t2i")

    assert "[[SUBJECT]]" in rendered
    assert "Holding tumbler toward camera" in rendered
    assert "reference image" not in rendered.casefold()
    assert "product image" not in rendered.casefold()
    assert "[[REFERENCE_" not in rendered
    assert "[[PRODUCT]]" not in rendered


def test_t2i_product_override_uses_product_type_key():
    prompt = curated_prompt()
    rendered = render_prompt(
        prompt,
        "t2i",
        product_overrides={"tumbler": "a matte black insulated tumbler"},
    )
    assert "Holding a matte black insulated tumbler toward camera" in rendered
    assert "[[SUBJECT]]" in rendered


def test_i2i_restores_reference_semantics_and_defers_subject():
    prompt = curated_prompt()
    rendered = render_prompt(prompt, "i2i")

    assert "[[SUBJECT]]" in rendered
    assert SCOPE in rendered
    assert IDENTITY in rendered
    assert GENERATION in rendered
    assert (
        "the exact tumbler product shown in the second reference image, product kept identical"
        in rendered
    )
    assert "[[REFERENCE_" not in rendered
    assert "[[PRODUCT]]" not in rendered


def test_i2i_perfume_product_does_not_duplicate_pose_text():
    pose = " up near the side of her neck as if about to spray"
    product_original = (
        "the exact perfume product shown in the second reference image"
        f"{pose}, product kept identical"
    )
    prompt = curated_prompt(
        template=(
            "Photo of [[SUBJECT]]. She holds [[PRODUCT]]"
            f"{pose}, held clearly toward camera. [[REFERENCE_IDENTITY]]"
        ),
        product_items=[
            {
                "original": product_original,
                "product_type": "perfume",
                "generic_description": "perfume",
                "reference_source": "second_reference_image",
            }
        ],
    )
    prompt["slots"]["reference_identity_scope"] = {
        "placeholder": "[[REFERENCE_IDENTITY_SCOPE]]",
        "original": [],
        "status": "not_present",
    }
    prompt["slots"]["reference_generation"] = {
        "placeholder": "[[REFERENCE_GENERATION]]",
        "original": [],
        "status": "not_present",
    }

    rendered = render_prompt(prompt, "i2i")
    assert rendered.count("up near the side of her neck as if about to spray") == 1
    assert (
        "the exact perfume product shown in the second reference image, product kept identical"
        in rendered
    )


def test_i2i_rejects_slot_metadata_without_matching_placeholder():
    prompt = curated_prompt(
        template="Photo of [[SUBJECT]]. [[REFERENCE_IDENTITY]]",
        product_items=[],
    )

    with pytest.raises(
        RenderError,
        match=r"\[\[REFERENCE_IDENTITY_SCOPE\]\] occurs 0 time\(s\) but slot has 1 value\(s\)",
    ):
        render_prompt(prompt, "i2i")


def test_runtime_modes_require_subject_placeholder_in_compiled_prompt():
    prompt = curated_prompt(template="Photo with no subject placeholder.", product_items=[])
    for slot_name in (
        "reference_identity",
        "reference_identity_scope",
        "reference_generation",
    ):
        prompt["slots"][slot_name] = {
            "placeholder": f"[[{slot_name.upper()}]]",
            "original": [],
            "status": "not_present",
        }

    with pytest.raises(RenderError, match=r"has no \[\[SUBJECT\]\]"):
        render_prompt(prompt, "t2i")


def test_raw_mode_returns_original_exactly():
    original = "Line one.\nLine two with periods."
    prompt = curated_prompt(original=original)
    assert render_prompt(prompt, "raw") == original


def test_export_writes_canonical_mode_directory_and_manifest(tmp_path: Path):
    first = curated_prompt(ident="hmm-test-first111", keep=None)
    second = curated_prompt(ident="hmm-test-second222", keep=False)
    second["source_index"] = 1

    curated = tmp_path / "curated.json"
    curated.write_text(
        json.dumps({"schema_version": 1, "prompts": [first, second]}),
        encoding="utf-8",
    )

    manifest_path = export_prompts(
        curated,
        tmp_path,
        mode="t2i",
    )

    assert manifest_path == tmp_path / "exports" / "t2i" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["mode"] == "t2i"
    assert manifest["subject_deferred"] is True
    assert manifest["subject_placeholder"] == "[[SUBJECT]]"
    assert manifest["prompt_count"] == 1
    assert manifest["items"][0]["prompt_id"] == "hmm-test-first111"

    prompt_file = manifest_path.parent / manifest["items"][0]["file"]
    text = prompt_file.read_text(encoding="utf-8")
    assert "[[SUBJECT]]" in text
    assert "reference image" not in text.casefold()


def test_export_collection_filter_accepts_slug(tmp_path: Path):
    first = curated_prompt(ident="hmm-test-first111")
    second = curated_prompt(ident="hmm-other-second222")
    second["collection"] = "Other"
    second["collection_slug"] = "other"

    curated = tmp_path / "curated.json"
    curated.write_text(
        json.dumps({"schema_version": 1, "prompts": [first, second]}),
        encoding="utf-8",
    )

    manifest_path = export_prompts(
        curated,
        tmp_path,
        mode="raw",
        collections=["other"],
        selection="all",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["prompt_count"] == 1
    assert manifest["items"][0]["collection_slug"] == "other"
