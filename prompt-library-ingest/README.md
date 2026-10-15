# HearmemanAI prompt-library ingest — Phase 1

This is the **non-mutating ingest/audit stage** for a personal prompt library.
It snapshots the public HearmemanAI PROmpt pages, parses the visible exact-prompt
fallback into JSON, and inventories subject/reference-image wording before any
normalization rules are applied.

## Output layout

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

Each prompt record preserves:

- collection and collection slug
- source character name
- source model
- source pack URL
- source image URL/alt text where available
- prompt text as `prompt_original`
- the parsed source text blocks as `prompt_blocks_original`
- SHA-256 of the prompt
- deterministic prompt ID

No `[[SUBJECT]]` or reference-image replacement is done in Phase 1.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python hearmeman_ingest.py all --out ./prompt-library
```

To force a fresh web snapshot:

```bash
python hearmeman_ingest.py all --out ./prompt-library --refresh
```

After the first scrape, the audit can be regenerated entirely from the local
JSON without contacting the site:

```bash
python hearmeman_ingest.py audit --out ./prompt-library
```

## Validation gates

The script compares:

1. the library's declared total prompt count with the parsed total;
2. each pack's declared prompt count with its parsed count;
3. prompt-card image count with parsed prompt count;
4. image-alt character with prompt-header character.

Any discrepancy is emitted as a warning and retained in `library.json`. Do not
start Phase 2 normalization until the declared/parsed totals match or every
mismatch has been understood.

## Phase 2 (intentionally not implemented yet)

Use `reports/pattern_audit.*` to define explicit transformations such as:

- source subject phrase -> `[[SUBJECT]]`
- identity-preservation clause -> semantic reference slot
- reference-compositing instructions -> semantic reference slot
- second-reference/product instructions -> separate product-reference slot

The planned curated layer should retain `prompt_original` unchanged and add a
separate template/rendering representation.
