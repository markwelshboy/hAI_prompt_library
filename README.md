# hAI Prompt Library

Private, curated prompt-library tooling and ComfyUI integration based on HearmemanAI PROmpt content.

The repository has four layers:

1. **Ingest** — snapshot and parse the source library without modifying prompt text.
2. **Curate** — normalize subjects/reference semantics into model-neutral templates while retaining immutable originals.
3. **Render** — generate model/workflow-specific prompt exports such as `krea2-lora` and `qwen-reference`.
4. **Publish / ComfyUI** — copy validated rendered exports into the versioned `runtime-library/` and consume them with the included custom nodes.

## ComfyUI nodes

The repository root is itself a ComfyUI custom node. Clone it as:

```text
ComfyUI/custom_nodes/hAI_prompt_library/
```

It exposes:

- **hAI Prompt Select** — select one rendered prompt by index, deterministic random seed, or exact prompt ID.
- **hAI Prompt Batch** — return a ComfyUI list of some/many/all prompts, with collection, start/count/stride and deterministic shuffle controls.

Both nodes read the exact `manifest.json` format produced by the Phase-3 renderer. They add no third prompt-storage format and require no additional Python packages.

Published manifests are discovered automatically below `runtime-library/`. To store runtime bundles elsewhere, set `HAI_PROMPT_LIBRARY_ROOT`; multiple roots may be separated with the platform path separator (`:` on Linux).

## Publish a rendered export

From `prompt-library-ingest/`:

```bash
python3 hearmeman_publish.py \
  --profile krea2-lora \
  --name sh1vx-all \
  --out ./prompt-library
```

This validates every prompt file, rejects unresolved placeholders, copies the complete export into:

```text
runtime-library/krea2-lora/sh1vx-all/
```

and rebuilds `runtime-library/index.json`.

Because this is a private repository, the published runtime bundles can then be committed so a fresh pod receives the exact same prompt library simply by cloning/pulling the repo.

Detailed ingest/curation/render documentation lives in [`prompt-library-ingest/README.md`](prompt-library-ingest/README.md).
