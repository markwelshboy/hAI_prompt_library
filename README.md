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

The node UI exposes the semantic runtime mode directly rather than asking for a manifest path:

```text
hAI Prompt Select

mode:        t2i | i2i
subject:     sH1VX woman
selection:   index | random | prompt_id
index:       0
seed:        0
collection:  <all> (188) | After Shower (5) | ...
prompt_id:   <used with selection=prompt_id>
wrap_index:  true
```

The `collection` widget is populated from the published runtime manifests and presented as a dropdown with the number of available prompts shown directly in each choice. When the `t2i` and `i2i` counts are identical the label is compact, such as `Wanderlust Diaries (5)`. If mode counts ever diverge, the label reports the per-mode counts instead of presenting a misleading single number.

For **hAI Prompt Batch**:

- `count = 0` means use every prompt remaining after `start` and `stride`.
- `count = N` limits the mapped batch to the first `N` prompts after those controls are applied.
- `stride = 1` uses every prompt, `stride = 2` every other prompt, and so on.
- `available_count` reports the number of prompts in the chosen collection before `start`/`stride`/`count`.
- `selected_count` reports how many prompts are actually emitted by the node.

`mode=t2i` resolves `runtime-library/t2i/manifest.json`; `mode=i2i` resolves `runtime-library/i2i/manifest.json` internally. The manifest remains the storage contract but is not exposed as a workflow-facing implementation detail.

At execution time the node replaces every `[[SUBJECT]]` occurrence with the supplied subject and rejects the prompt if any other unresolved `[[...]]` placeholder remains. Changing `subject`, collection, or the underlying manifest invalidates the node cache.

Both nodes require no additional Python packages.

Published manifests are discovered automatically at `runtime-library/t2i/manifest.json` and `runtime-library/i2i/manifest.json`. To use runtime bundles elsewhere, set `HAI_PROMPT_LIBRARY_ROOT`; when set, it **replaces** the bundled default root rather than falling back to it. Multiple external roots may be separated with the platform path separator (`:` on Linux), and the first matching mode in root order wins.

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
