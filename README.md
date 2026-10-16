# hAI Prompt Library

Public, curated prompt-library tooling and ComfyUI integration based on HearmemanAI PROmpt content.

The repository has four layers:

1. **Ingest** — snapshot and parse the source library without modifying prompt text.
2. **Curate** — normalize subjects/reference semantics into model-neutral templates while retaining immutable originals.
3. **Compile** — build model-neutral `t2i` and `i2i` runtime prompt bundles while deliberately leaving `[[SUBJECT]]` unresolved.
4. **Publish / ComfyUI** — copy validated bundles into the versioned `runtime-library/`; the included ComfyUI nodes resolve `[[SUBJECT]]` at runtime.

## Runtime library

The committed runtime contract is intentionally independent of Krea, Qwen, Klei, a particular LoRA, or a particular trigger:

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

- `t2i` removes reference-image identity/edit instructions and uses generic product descriptions.
- `i2i` retains the reference-aware identity/edit semantics and reference-aware product wording.
- Both modes retain only the runtime placeholder `[[SUBJECT]]`.
- A ComfyUI workflow supplies the subject dynamically, e.g. `sH1VX woman`, `woman`, or another trigger/category phrase.

This makes the same published library usable with different text-to-image and image-edit/reference-capable models without republishing it for every model or LoRA.

## ComfyUI nodes

The repository root is itself a ComfyUI custom node. Clone it as:

```text
ComfyUI/custom_nodes/hAI_prompt_library/
```

It exposes:

- **hAI Prompt Select** — select one prompt by index, deterministic random seed, or exact prompt ID, then resolve `[[SUBJECT]]` from the node's `subject` input.
- **hAI Prompt Batch** — return a ComfyUI list of some/many/all prompts, with collection, start/count/stride and deterministic shuffle controls, resolving the same `subject` across the batch.

Both nodes require no additional Python packages.

Published manifests are discovered automatically at `runtime-library/t2i/manifest.json` and `runtime-library/i2i/manifest.json`. To store runtime bundles elsewhere, set `HAI_PROMPT_LIBRARY_ROOT`; multiple roots may be separated with the platform path separator (`:` on Linux).

## Compile and publish

From `prompt-library-ingest/`:

```bash
python3 hearmeman_render.py --mode t2i --out ./prompt-library
python3 hearmeman_render.py --mode i2i --out ./prompt-library

python3 hearmeman_publish.py --mode t2i --out ./prompt-library
python3 hearmeman_publish.py --mode i2i --out ./prompt-library
```

The compiler writes:

```text
prompt-library/exports/t2i/
prompt-library/exports/i2i/
```

The publisher validates every prompt file, permits only the deferred `[[SUBJECT]]` placeholder, rejects any other unresolved semantic placeholder, publishes the two canonical runtime directories, and rebuilds `runtime-library/index.json`.

Detailed ingest/curation/compile documentation lives in [`prompt-library-ingest/README.md`](prompt-library-ingest/README.md).
