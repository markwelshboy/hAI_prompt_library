# HearmemanAI prompt library

This repository has four deliberately separate stages:

1. **Phase 1 — immutable ingest/audit**: snapshot HearmemanAI, parse exact source prompts, and inventory subject/reference patterns.
2. **Phase 2 — curated templates**: derive model-neutral prompt templates with semantic placeholders while retaining `prompt_original` unchanged.
3. **Phase 3 — compile/export**: resolve every semantic difference except the subject itself into canonical `t2i` and `i2i` runtime bundles.
4. **Phase 4 — publish/runtime**: validate those bundles, commit them under `runtime-library/`, and resolve `[[SUBJECT]]` dynamically inside ComfyUI.

The source and curated layers are never modified by compiling or publishing.

# Phase 1 — immutable ingest/audit

## Output

```text
prompt-library/
├── source/
│   └── hearmemanai/
│       ├── raw_html/
│       ├── parsed/
│       └── library.json
└── reports/
    ├── pattern_audit.json
    └── pattern_audit.md
```

Each source prompt record preserves collection, source character/model metadata, source URL/image metadata, exact `prompt_original`, parsed source blocks, SHA-256, and a deterministic prompt ID.

No placeholder replacement is performed in Phase 1.

## Run Phase 1

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python3 hearmeman_ingest.py all --out ./prompt-library
```

Force a fresh web snapshot with:

```bash
python3 hearmeman_ingest.py all --out ./prompt-library --refresh
```

Regenerate only the audit from the local source snapshot with:

```bash
python3 hearmeman_ingest.py audit --out ./prompt-library
```

The current validated source snapshot is **188 prompts across 35 collections**.

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
└── reports/
    ├── transformation_report.json
    └── transformation_report.md
```

`prompt_original` is copied unchanged into every curated record. Automatic transformations are written only to `prompt_template`.

## Semantic placeholders

Phase 2 uses:

- `[[SUBJECT]]` — subject/category phrase, eventually resolved to e.g. `woman` or a LoRA trigger phrase.
- `[[REFERENCE_IDENTITY]]` — standard identity-preservation instruction.
- `[[REFERENCE_IDENTITY_SCOPE]]` — subject-attached reference-image identity scope.
- `[[REFERENCE_GENERATION]]` — reference-only / no-compositing generation instruction.
- `[[PRODUCT]]` — product identity/reference mechanics while preserving useful pose/presentation wording around it.

The currently validated curated library is **188/188 auto-ready with zero review items**.

Inspect the acceptance report with:

```bash
cat prompt-library/reports/transformation_report.md
```

# Phase 3 — model-neutral runtime compilation

Phase 3 does **not** compile for a specific model or LoRA. Instead it produces two semantic runtime modes:

- `t2i` — for workflows that do not consume an identity/reference image. Reference-image instructions are omitted and product references become generic product descriptions.
- `i2i` — for image-edit/reference-capable workflows. Reference-aware identity/generation wording and product-reference semantics are retained.
- `raw` — optional exact source export for debugging/comparison only; it is not a published runtime mode.

The critical design rule is that both runtime modes deliberately retain `[[SUBJECT]]`. A trigger such as `sH1VX woman` is supplied later by the ComfyUI node, so the committed runtime library is not tied to Krea, Qwen, Klei, or one trained character.

## Compile both runtime modes

```bash
python3 hearmeman_render.py --mode t2i --out ./prompt-library
python3 hearmeman_render.py --mode i2i --out ./prompt-library
```

Output:

```text
prompt-library/
└── exports/
    ├── t2i/
    │   ├── manifest.json
    │   └── collections/...
    └── i2i/
        ├── manifest.json
        └── collections/...
```

There is one canonical generated directory per runtime mode. Rerunning a mode replaces that generated directory first, preventing stale prompt files from surviving narrower test runs.

Each runtime `.txt` must contain `[[SUBJECT]]` and may contain **no other** unresolved `[[...]]` placeholder.

## Optional filters

Filters can be combined:

```bash
python3 hearmeman_render.py \
  --mode t2i \
  --collection wanderlust-diaries \
  --source-model nano-banana-2 \
  --limit 10
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

For `t2i` product prompts, `--product-map FILE.json` may override generic product descriptions. It is intentionally rejected for `i2i`, where reference-aware product wording is the point of the mode.

# Phase 4 — publish/runtime library

Publish the canonical compiled bundles with:

```bash
python3 hearmeman_publish.py --mode t2i --out ./prompt-library
python3 hearmeman_publish.py --mode i2i --out ./prompt-library
```

The committed runtime layout is:

```text
runtime-library/
├── index.json
├── t2i/
│   ├── manifest.json
│   └── collections/...
└── i2i/
    ├── manifest.json
    └── collections/...
```

The publisher validates:

- manifest item count matches `prompt_count`;
- every prompt file exists and is non-empty;
- paths cannot escape the bundle;
- `[[SUBJECT]]` is present and deliberately deferred;
- no other unresolved semantic placeholder survives.

`runtime-library/index.json` indexes only the canonical `t2i` and `i2i` manifests; legacy nested model/trigger-specific manifests are ignored.

# ComfyUI runtime

The repository root is itself a ComfyUI custom node. It exposes:

- **hAI Prompt Select** — one prompt by index, deterministic random seed, or exact prompt ID.
- **hAI Prompt Batch** — a ComfyUI list with collection, start/count/stride and deterministic shuffle controls.

Both nodes have a `subject` input. They read a deferred runtime template, replace every `[[SUBJECT]]` occurrence with that input, reject any remaining placeholder, and then emit the final prompt.

Examples:

```text
t2i + subject="sH1VX woman"
    -> LoRA-triggered text-to-image prompt

i2i + subject="woman"
    -> generic image-edit/reference prompt
```

The same `i2i` bundle can therefore be consumed by Qwen, Klei, or another reference-capable workflow without republishing the library.

# Migrating the old runtime layout

The earlier runtime prototype used model/trigger-specific paths such as:

```text
runtime-library/krea2-lora/sh1vx-all/
runtime-library/qwen-reference/qwen-all/
```

Do not rewrite Git history. Remove those generated trees in a normal follow-up commit, compile/publish the canonical modes, and commit the replacement:

```bash
git rm -r runtime-library/krea2-lora runtime-library/qwen-reference

cd prompt-library-ingest
python3 hearmeman_render.py --mode t2i --out ./prompt-library
python3 hearmeman_render.py --mode i2i --out ./prompt-library
python3 hearmeman_publish.py --mode t2i --out ./prompt-library
python3 hearmeman_publish.py --mode i2i --out ./prompt-library
cd ..

git add runtime-library
git commit -m "Generalize runtime prompt library to t2i and i2i"
git push
```

# Tests

Run:

```bash
python3 -m pytest -q
```

Tests cover ingest parsing, Phase-2 normalization, `t2i`/`i2i` compilation, product-reference handling, deferred-subject validation, runtime publishing, path safety, and ComfyUI subject substitution/batching.
