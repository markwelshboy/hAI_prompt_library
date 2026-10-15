# HearmemanAI prompt library

This repository now has two deliberately separate stages:

1. **Phase 1 — immutable ingest/audit**: snapshot HearmemanAI, parse exact source prompts, and inventory subject/reference patterns.
2. **Phase 2 — curated templates**: derive model-neutral prompt templates with semantic placeholders while retaining `prompt_original` unchanged.

Rendering/export for ComfyUI is intentionally a later stage. We first validate the transformations across the complete library.

## Phase 1 output

```text
prompt-library/
├── source/
│   └── hearmemanai/
│       ├── raw_html/
│       │   ├── _library.html
│       │   └── <pack>.html
│       ├── parsed/
│       │   └── <pack>.json
│       └── library.json
└── reports/
    ├── pattern_audit.json
    └── pattern_audit.md
```

Each source prompt record preserves:

- collection and collection slug
- source character name
- source model
- source pack URL
- source image URL/alt text where available
- prompt text as `prompt_original`
- parsed source text blocks as `prompt_blocks_original`
- SHA-256 of the prompt
- deterministic prompt ID

No placeholder replacement is performed in Phase 1.

## Run Phase 1

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 hearmeman_ingest.py all --out ./prompt-library
```

For development/testing, install the dev requirements instead (they include the runtime requirements plus pytest):

```bash
pip install -r requirements-dev.txt
```

To force a fresh web snapshot:

```bash
python3 hearmeman_ingest.py all --out ./prompt-library --refresh
```

After the first scrape, regenerate the audit entirely from local JSON:

```bash
python3 hearmeman_ingest.py audit --out ./prompt-library
```

## Phase 1 validation gates

The ingest compares:

1. the library's declared total prompt count with the parsed total;
2. each pack's declared prompt count with its parsed count;
3. prompt-card image count with parsed prompt count;
4. image-alt character with prompt-header character.

Do not normalize until the declared/parsed totals agree or every mismatch is understood. The current validated snapshot is **188 prompts across 35 collections**.

# Phase 2 — curated/template layer

Run:

```bash
python3 hearmeman_curate.py --out ./prompt-library
```

This reads:

```text
prompt-library/source/hearmemanai/library.json
```

and writes:

```text
prompt-library/
├── curated/
│   ├── library.json
│   └── collections/
│       └── <collection>.json
└── reports/
    ├── transformation_report.json
    └── transformation_report.md
```

`prompt_original` is copied unchanged into every curated record. Automatic transformations are written only to `prompt_template`.

## Semantic placeholders

Phase 2 currently uses:

- `[[SUBJECT]]` — the source subject phrase, to be rendered later with the desired subject/LoRA trigger.
- `[[REFERENCE_IDENTITY]]` — the standard "Preserve the character identity..." instruction, including the inline `preserving...` variant.
- `[[REFERENCE_IDENTITY_SCOPE]]` — subject-attached wording such as `from the reference image, used only for identity...`. Later repeated subject/reference phrases are normalized too, but ordinary later uses of `woman` are not globally replaced.
- `[[REFERENCE_GENERATION]]` — instructions that the reference is identity-only and must not be pasted/composited into the result.
- `[[PRODUCT]]` — the product identity. The prompt body retains presentation/action wording; structured slot metadata retains the original reference-aware wording, a generic product description/type, and whether the product came from `second_reference_image` or `product_image`.

The UGC product prompts deliberately normalize only the product-identity fragment. For example, wording equivalent to:

```text
holding the exact tumbler product shown in the second reference image,
product kept identical,
held clearly toward camera
```

becomes:

```text
holding [[PRODUCT]], held clearly toward camera
```

so the pose/presentation instruction survives intact. The two UGC prompts that use `product image` rather than `second reference image` (jewelry and sneakers) are normalized into the same slot.

One tote UGC prompt has no explicit subject noun in the source. A narrowly scoped collection-specific rule inserts `[[SUBJECT]]` after `street-style full-body mirror selfie`; the curated slot records this as `status: inserted` rather than pretending a source phrase existed.

## Curation metadata

Every curated record includes editable curation state:

```json
{
  "keep": null,
  "reviewed": false,
  "favorite": false,
  "notes": "",
  "review_required": false,
  "review_reasons": []
}
```

`keep: null` means the prompt has not yet been manually accepted/rejected.

## Phase 2 acceptance step

After generating the curated layer, inspect:

```bash
cat prompt-library/reports/transformation_report.md
```

The current target is for all 188 prompts to be structurally auto-ready before we create Krea2/Qwen renderers or ComfyUI batch exports.

## Tests

Install the development dependencies once:

```bash
pip install -r requirements-dev.txt
```

Then run:

```bash
python3 -m pytest -q
```

The tests cover pack discovery/parsing as well as the Phase-2 transformations, including subject-attached reference scope, inline identity clauses, the inline `preserving...` identity variant, later repeated identity-scoped subject phrases, multi-panel reference instructions, second-reference products, `product image` jewelry/sneakers, the tote subject insertion rule, and the generic missing-subject review fallback.
