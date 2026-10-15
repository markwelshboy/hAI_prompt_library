# HearmemanAI prompt library

This repository has three deliberately separate stages:

1. **Phase 1 — immutable ingest/audit**: snapshot HearmemanAI, parse exact source prompts, and inventory subject/reference patterns.
2. **Phase 2 — curated templates**: derive model-neutral prompt templates with semantic placeholders while retaining `prompt_original` unchanged.
3. **Phase 3 — render/export**: resolve those placeholders for a target workflow and write ComfyUI-friendly prompt batches plus a manifest.

The source and curated layers are never modified by rendering/export.

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

Phase 2 uses:

- `[[SUBJECT]]` — the subject phrase / LoRA trigger target.
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

The currently validated library is **188/188 auto-ready with zero review items**.

# Phase 3 — renderer/exporter

Phase 3 reads the curated library and produces resolved prompt text without modifying either Phase 1 or Phase 2 data.

The available profiles are:

- `krea2-lora` — substitute your LoRA trigger/subject, omit all identity/reference-image instructions, and use generic or custom product descriptions.
- `qwen-reference` — substitute the requested subject while restoring the original reference-aware identity/generation semantics and reference-aware product identity.
- `raw` — export `prompt_original` exactly as preserved.

## Krea2 / LoRA export

Render the whole not-rejected library for a LoRA trigger:

```bash
python3 hearmeman_render.py \
  --profile krea2-lora \
  --subject "sH1VX woman" \
  --name sh1vx \
  --out ./prompt-library
```

This removes `[[REFERENCE_IDENTITY]]`, `[[REFERENCE_IDENTITY_SCOPE]]`, and `[[REFERENCE_GENERATION]]`, and validates that no `reference image` / `product image` wording survives in the rendered prompt.

Product prompts use their generic structured descriptions by default. To override selected product types, supply a JSON map:

```json
{
  "tumbler": "a matte black insulated tumbler",
  "perfume": "a clear rectangular perfume bottle with a silver cap",
  "tote bag": "a cream canvas tote bag with black handles"
}
```

then:

```bash
python3 hearmeman_render.py \
  --profile krea2-lora \
  --subject "sH1VX woman" \
  --product-map ./my-products.json \
  --name sh1vx-products
```

The keys are the curated `product_type` values. Unspecified products fall back to their stored generic descriptions.

## Qwen/reference export

```bash
python3 hearmeman_render.py \
  --profile qwen-reference \
  --subject "one adult woman" \
  --name qwen-reference
```

This restores the reference-aware identity/scope/generation wording from the curated slot metadata. Product pose/action remains in `prompt_template`; only product identity/reference mechanics are restored from the product slot, avoiding duplication in the perfume pose variant.

## Raw export

```bash
python3 hearmeman_render.py --profile raw
```

No subject is required for `raw` because it writes `prompt_original` unchanged.

## Filtering and curation selection

Filters can be combined:

```bash
python3 hearmeman_render.py \
  --profile krea2-lora \
  --subject "sH1VX woman" \
  --collection wanderlust-diaries \
  --source-model nano-banana-2 \
  --limit 10 \
  --name wanderlust-test
```

Repeat `--collection`, `--prompt-id`, or `--source-model` to select multiple values.

Curation selection modes:

```text
--selection not-rejected   # default: keep=true or keep=null
--selection all            # all matching prompts
--selection kept           # keep=true only
--selection favorites      # favorite=true only
```

Prompts with `review_required=true` are skipped by default; use `--include-review` only when intentionally testing them.

## Export layout

A named export is written under:

```text
prompt-library/
└── exports/
    └── krea2-lora/
        └── sh1vx/
            ├── manifest.json
            └── collections/
                ├── wanderlust-diaries/
                │   ├── 001__chloe__<id>.txt
                │   └── ...
                └── ...
```

Each `.txt` is one complete rendered prompt. Multiline prompts and punctuation are therefore safe; no delimiter parsing is required.

`manifest.json` records the profile, subject, filters, source metadata, ordered prompt IDs, relative text-file paths, and product counts. It is intended to be the stable machine-readable handoff for batch tooling or a future ComfyUI node.

Rerunning the same `profile + --name` replaces that generated export directory first. This prevents stale prompt files from surviving when a later run uses a narrower filter.

# Tests

Install the development dependencies once:

```bash
pip install -r requirements-dev.txt
```

Then run:

```bash
python3 -m pytest -q
```

Tests cover pack discovery/parsing, Phase-2 transformations, all three Phase-3 rendering profiles, product-reference rendering (including the perfume pose variant), product overrides, selection/filter behavior, and batch manifest/text-file export.
