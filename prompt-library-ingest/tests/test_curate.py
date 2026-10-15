from hearmeman_curate import transform_prompt


def prompt(
    text: str,
    ident: str = "p1",
    collection: str = "Test",
    collection_slug: str = "test",
) -> dict:
    return {
        "id": ident,
        "source_index": 0,
        "collection": collection,
        "collection_slug": collection_slug,
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


def test_inline_preserving_identity_variant_is_normalized():
    src = (
        "A woman, preserving the character identity from the reference image, keeping "
        "their exact hair color, hairstyle, eye color, skin tone, face shape, and body "
        "shape, lounging on a soft gray couch."
    )
    out = transform_prompt(prompt(src))

    assert "[[REFERENCE_IDENTITY]]" in out["prompt_template"]
    assert "reference image" not in out["prompt_template"].casefold()
    assert "lounging on a soft gray couch" in out["prompt_template"]
    assert out["curation"]["review_required"] is False


def test_later_identity_scoped_subject_is_normalized_without_global_woman_replace():
    src = (
        f"Candid amateur photo of a single adult woman. {IDENTITY} "
        "She stands taking a full-length mirror selfie. "
        "Candid amateur phone mirror selfie of a woman from the reference image, "
        "used for identity reference only. "
        f"{IDENTITY} Another woman walks past in the distant background."
    )
    out = transform_prompt(prompt(src))

    assert out["prompt_template"].count("[[SUBJECT]]") == 2
    assert out["prompt_template"].count("[[REFERENCE_IDENTITY_SCOPE]]") == 1
    assert out["prompt_template"].count("[[REFERENCE_IDENTITY]]") == 2
    assert "Another woman walks past" in out["prompt_template"]
    assert "reference image" not in out["prompt_template"].casefold()
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


def test_second_reference_product_becomes_product_slot_without_losing_action():
    src = (
        "A casual gym athleisure selfie of a woman, holding the exact tumbler product "
        "shown in the second reference image, product kept identical, held clearly "
        "toward camera."
    )
    out = transform_prompt(prompt(src))

    assert "holding [[PRODUCT]], held clearly toward camera" in out["prompt_template"]
    assert "second reference image" not in out["prompt_template"].casefold()
    assert out["slots"]["product"]["status"] == "auto"
    item = out["slots"]["product"]["items"][0]
    assert item["product_type"] == "tumbler"
    assert item["reference_source"] == "second_reference_image"
    assert out["curation"]["review_required"] is False


def test_product_image_sneakers_become_product_slot():
    src = (
        f"A woman. {IDENTITY} She wears the exact white low-top leather sneakers "
        "from the product image, kept identical (white laces, white rubber soles), "
        "with cuffed cobalt-blue barrel jeans."
    )
    out = transform_prompt(prompt(src))

    assert "She wears [[PRODUCT]], with cuffed" in out["prompt_template"]
    assert "product image" not in out["prompt_template"].casefold()
    item = out["slots"]["product"]["items"][0]
    assert item["product_type"] == "sneakers"
    assert item["reference_source"] == "product_image"
    assert "white laces" in item["generic_description"]
    assert out["curation"]["review_required"] is False


def test_product_image_jewelry_becomes_product_slot():
    src = (
        f"Close-up selfie of a woman. {IDENTITY} She wears the gold pendant necklace "
        "from the product image, a thin chain with a small round clear-stone charm "
        "sitting at her collarbone, plus the matching small gold hoop earrings with tiny "
        "clear stones, kept exactly as shown. Outfit is a red tank."
    )
    out = transform_prompt(prompt(src))

    assert "She wears [[PRODUCT]]. Outfit is a red tank." in out["prompt_template"]
    assert "product image" not in out["prompt_template"].casefold()
    item = out["slots"]["product"]["items"][0]
    assert item["product_type"] == "jewelry"
    assert item["reference_source"] == "product_image"
    assert "matching small gold hoop earrings" in item["generic_description"]
    assert out["curation"]["review_required"] is False


def test_ugc_tote_missing_subject_gets_explicit_collection_rule():
    src = (
        "A street-style full-body mirror selfie carrying the tote on her shoulder, "
        "holding the exact tote-bag product shown in the second reference image, "
        f"product kept identical, held clearly toward camera. {IDENTITY}"
    )
    out = transform_prompt(
        prompt(
            src,
            collection="UGC Product Spotlight",
            collection_slug="ugc-product-spotlight",
        )
    )

    assert "mirror selfie of [[SUBJECT]] carrying" in out["prompt_template"]
    assert "holding [[PRODUCT]], held clearly toward camera" in out["prompt_template"]
    assert out["slots"]["subject"]["status"] == "inserted"
    assert out["slots"]["subject"]["original"] is None
    assert out["curation"]["review_required"] is False


def test_missing_subject_outside_known_rule_is_reviewed_not_guessed():
    src = f"Editorial fashion image at night. {IDENTITY}"
    out = transform_prompt(prompt(src))

    assert out["slots"]["subject"] is None
    assert "no_subject_candidate" in out["curation"]["review_reasons"]
    assert out["curation"]["review_required"] is True
