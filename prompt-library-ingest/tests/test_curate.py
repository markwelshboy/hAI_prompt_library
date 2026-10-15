from hearmeman_curate import transform_prompt


def prompt(text: str, ident: str = "p1") -> dict:
    return {
        "id": ident,
        "source_index": 0,
        "collection": "Test",
        "collection_slug": "test",
        "character": "Alice",
        "model": "nano-banana-2",
        "source_url": "https://example.test/pack/",
        "image_url": None,
        "image_alt": None,
        "prompt_original": text,
        "prompt_blocks_original": [text],
        "prompt_sha256": "deadbeef",
    }


IDENTITY = (
    "Preserve the character identity from the reference image, keeping their exact "
    "hair color, hairstyle, eye color, skin tone, face shape, and body shape."
)


def test_simple_subject_and_standard_identity_clause():
    src = f"Full-body photo of one adult woman on a beach. {IDENTITY} Warm sunset light."
    out = transform_prompt(prompt(src))

    assert out["prompt_original"] == src
    assert "[[SUBJECT]]" in out["prompt_template"]
    assert "[[REFERENCE_IDENTITY]]" in out["prompt_template"]
    assert "reference image" not in out["prompt_template"].casefold()
    assert out["slots"]["subject"]["original"] == "one adult woman"
    assert out["curation"]["review_required"] is False


def test_subject_attached_reference_scope_is_separate_slot():
    src = (
        "Candid amateur photo of one adult woman from the reference image, used only "
        "for identity, face, hair and natural expression. Walking outside."
    )
    out = transform_prompt(prompt(src))

    assert "[[SUBJECT]] [[REFERENCE_IDENTITY_SCOPE]]" in out["prompt_template"]
    assert out["slots"]["subject"]["original"] == "one adult woman"
    assert out["slots"]["reference_identity_scope"]["original"] == [
        "from the reference image, used only for identity, face, hair and natural expression"
    ]
    assert out["curation"]["review_required"] is False


def test_inline_identity_clause_keeps_surrounding_scene_text():
    src = (
        "Candid photo of an adult woman, preserve the character identity from the "
        "reference image, keeping their exact hair color, hairstyle, eye color, skin "
        "tone, face shape, and body shape, sitting beside a pool at golden hour."
    )
    out = transform_prompt(prompt(src))

    assert "[[REFERENCE_IDENTITY]]" in out["prompt_template"]
    assert "sitting beside a pool at golden hour" in out["prompt_template"]
    assert out["curation"]["review_required"] is False


def test_reference_generation_instruction_becomes_separate_slot():
    src = (
        "Three-panel collage of a woman. "
        "Use the reference image ONLY for her face, hair color and texture, and natural "
        "features; keep her identity identical across all three panels; generate NEW "
        "native selfies and do NOT paste, cut out, composite, or preserve the reference's "
        "body, clothing, pose, or background."
    )
    out = transform_prompt(prompt(src))

    assert "[[REFERENCE_GENERATION]]" in out["prompt_template"]
    assert out["slots"]["reference_generation"]["status"] == "auto"
    assert out["curation"]["review_required"] is False


def test_second_reference_product_is_preserved_and_reviewed():
    src = (
        "A casual gym athleisure selfie of a woman, holding the exact tumbler product "
        "shown in the second reference image, product kept identical, held clearly "
        "toward camera."
    )
    out = transform_prompt(prompt(src))

    assert "second reference image" in out["prompt_template"]
    assert out["slots"]["reference_product"]["status"] == "review"
    assert "second_reference_product" in out["curation"]["review_reasons"]
    assert "residual_reference_language" in out["curation"]["review_reasons"]


def test_missing_subject_is_reviewed_not_guessed():
    src = f"Editorial fashion image at night. {IDENTITY}"
    out = transform_prompt(prompt(src))

    assert out["slots"]["subject"] is None
    assert "no_subject_candidate" in out["curation"]["review_reasons"]
    assert out["curation"]["review_required"] is True
