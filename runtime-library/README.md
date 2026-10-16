# Runtime prompt bundles

This directory contains **published, rendered prompt bundles** intended for direct use by the ComfyUI custom nodes in this repository.

Do not hand-edit generated bundle contents. Build and curate under `prompt-library-ingest/prompt-library/`, render with `hearmeman_render.py`, then publish a validated export with `hearmeman_publish.py`.

Example:

```bash
cd prompt-library-ingest

python3 hearmeman_publish.py \
  --profile krea2-lora \
  --name sh1vx-all \
  --out ./prompt-library
```

That creates a versionable bundle such as:

```text
runtime-library/
├── index.json
└── krea2-lora/
    └── sh1vx-all/
        ├── manifest.json
        └── collections/
            └── ...
```

A fresh pod can clone this private repository directly under `ComfyUI/custom_nodes/hAI_prompt_library`; the nodes discover manifests below this directory automatically.

To keep runtime prompt data elsewhere, set `HAI_PROMPT_LIBRARY_ROOT` to one or more roots separated by the platform path separator (`:` on Linux).
