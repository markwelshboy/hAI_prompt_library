#!/usr/bin/env python3
"""Ingest and audit the public HearmemanAI PROmpt library.

Phase 1 is deliberately non-mutating:
  * download + snapshot source HTML
  * parse exact visible prompt text into JSON
  * audit subject/reference-image wording

No [[SUBJECT]] or reference-clause replacement is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

LIBRARY_URL = "https://hearmemanai.com/prompts/"
PACK_PREFIX = "/prompts/packs/"
UA = "prompt-library-curator/0.1 (+private personal prompt-library archival)"
HEADER_SEP = " · "

STOP_MARKERS = {
    "Make these prompts your own character",
    "Good prompts deserve to be shared.",
}
SKIP_TOKENS = {
    "Open this collection",
    "Interactive search, saved prompts, and contributions need JavaScript. You can still read and manually copy these exact prompts.",
}

SUBJECT_RE = re.compile(
    r"\b(?:"
    r"(?:one|an?|the|single|a\s+single)\s+"
    r")?"
    r"(?:fictional\s+)?"
    r"(?:young\s+)?"
    r"(?:adult\s+)?"
    r"woman"
    r"(?:\s+from\s+the\s+reference\s+image"
    r"(?:,\s*used\s+only\s+for\s+[^.;\n]+)?"
    r")?",
    re.IGNORECASE,
)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])" )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "item"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compact_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class Fetcher:
    def __init__(self, timeout: float = 30.0, delay: float = 0.25):
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
        self._last_fetch = 0.0

    def get_text(self, url: str) -> str:
        elapsed = time.monotonic() - self._last_fetch
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                self._last_fetch = time.monotonic()
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == 3:
                    break
                time.sleep(1.0 * (2 ** attempt))
        raise RuntimeError(f"Failed to fetch {url}: {last_exc}")


@dataclass
class ImageEntry:
    character_from_alt: str | None
    alt: str | None
    url: str | None


@dataclass
class PromptRecord:
    id: str
    source_index: int
    collection: str
    collection_slug: str
    character: str
    model: str
    source_url: str
    image_url: str | None
    image_alt: str | None
    prompt_original: str
    prompt_blocks_original: list[str]
    prompt_sha256: str


def discover_pack_urls(html: str, base_url: str = LIBRARY_URL) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a.get("href"))
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.netloc.endswith("hearmemanai.com") and parsed.path.startswith(PACK_PREFIX):
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if not clean.endswith("/"):
                clean += "/"
            urls.add(clean)
    return sorted(urls)


def declared_count(text: str) -> int | None:
    # Pack/root pages expose e.g. "5 prompts" / "188 prompts".
    matches = [int(x) for x in re.findall(r"\b(\d+)\s+prompts\b", text, flags=re.I)]
    return max(matches) if matches else None


def prompt_images(soup: BeautifulSoup) -> list[ImageEntry]:
    result: list[ImageEntry] = []
    # Prompt-card alts currently look like:
    #   Image: Chloe, wanderlust diaries AI image
    rx = re.compile(r"^Image:\s*([^,]+),\s*.+\bAI image$", re.I)
    for img in soup.find_all("img"):
        alt = compact_ws(str(img.get("alt") or "")) or None
        if not alt:
            continue
        m = rx.match(alt)
        if not m:
            continue
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        result.append(
            ImageEntry(
                character_from_alt=compact_ws(m.group(1)),
                alt=alt,
                url=urljoin(LIBRARY_URL, str(src)) if src else None,
            )
        )
    return result


def parse_header(token: str, collection: str) -> tuple[str, str] | None:
    prefix = collection + HEADER_SEP
    if not token.startswith(prefix):
        return None
    rest = token[len(prefix):]
    parts = [p.strip() for p in rest.rsplit(HEADER_SEP, 1)]
    if len(parts) != 2 or not all(parts):
        return None
    return parts[0], parts[1]


def parse_pack(html: str, url: str) -> tuple[dict, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        raise ValueError(f"No <h1> collection name found: {url}")
    collection = compact_ws(h1.get_text(" ", strip=True))
    collection_slug = slugify(urlparse(url).path.rstrip("/").split("/")[-1] or collection)
    page_text = soup.get_text("\n", strip=True)
    count = declared_count(page_text)
    images = prompt_images(soup)

    tokens = [compact_ws(s) for s in soup.stripped_strings]
    try:
        start = tokens.index("Browse and copy prompts") + 1
    except ValueError as exc:
        raise ValueError(f"Could not find fallback prompt section in {url}") from exc

    records: list[PromptRecord] = []
    warnings: list[str] = []
    current_header: tuple[str, str] | None = None
    current_blocks: list[str] = []

    def flush() -> None:
        nonlocal current_header, current_blocks
        if current_header is None:
            current_blocks = []
            return
        character, model = current_header
        blocks = [b for b in current_blocks if b and b not in SKIP_TOKENS]
        # Sometimes "Open this collection" is concatenated into presentation text;
        # strip only that UI label, never prompt language.
        cleaned: list[str] = []
        for block in blocks:
            if block == "Open this collection":
                continue
            if block.startswith("Open this collection"):
                remainder = block[len("Open this collection"):].strip()
                if remainder:
                    cleaned.append(remainder)
                continue
            cleaned.append(block)
        prompt = "\n".join(cleaned).strip()
        if not prompt:
            warnings.append(f"{collection}: empty prompt for {character} / {model}")
            current_header = None
            current_blocks = []
            return
        digest = sha256_text(prompt)
        idx = len(records)
        img = images[idx] if idx < len(images) else None
        if img and img.character_from_alt and img.character_from_alt.casefold() != character.casefold():
            warnings.append(
                f"{collection} #{idx}: image character {img.character_from_alt!r} != header character {character!r}"
            )
        stable_material = f"{collection}\n{character}\n{model}\n{prompt}"
        stable = sha256_text(stable_material)[:12]
        records.append(
            PromptRecord(
                id=f"hmm-{collection_slug}-{stable}",
                source_index=idx,
                collection=collection,
                collection_slug=collection_slug,
                character=character,
                model=model,
                source_url=url,
                image_url=img.url if img else None,
                image_alt=img.alt if img else None,
                prompt_original=prompt,
                prompt_blocks_original=cleaned,
                prompt_sha256=digest,
            )
        )
        current_header = None
        current_blocks = []

    for token in tokens[start:]:
        if token in STOP_MARKERS:
            break
        hdr = parse_header(token, collection)
        if hdr:
            flush()
            current_header = hdr
            continue
        if current_header is None:
            # Ignore UI text until the first prompt header.
            continue
        if token == "Open this collection":
            continue
        current_blocks.append(token)
    flush()

    if count is not None and count != len(records):
        warnings.append(f"{collection}: declared {count} prompts but parsed {len(records)}")
    if images and len(images) != len(records):
        warnings.append(f"{collection}: found {len(images)} prompt-card images but parsed {len(records)} prompts")

    pack = {
        "schema_version": 1,
        "source": {
            "provider": "HearmemanAI PROmpt",
            "url": url,
            "scraped_at": utc_now(),
            "declared_prompt_count": count,
        },
        "collection": {
            "name": collection,
            "slug": collection_slug,
        },
        "prompts": [asdict(r) for r in records],
        "warnings": warnings,
    }
    return pack, warnings


def scrape(out_dir: Path, refresh: bool, timeout: float, delay: float) -> Path:
    raw_dir = out_dir / "source" / "hearmemanai" / "raw_html"
    parsed_dir = out_dir / "source" / "hearmemanai" / "parsed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)

    fetcher = Fetcher(timeout=timeout, delay=delay)
    root_html_path = raw_dir / "_library.html"
    if refresh or not root_html_path.exists():
        root_html = fetcher.get_text(LIBRARY_URL)
        root_html_path.write_text(root_html, encoding="utf-8")
    else:
        root_html = root_html_path.read_text(encoding="utf-8")

    pack_urls = discover_pack_urls(root_html)
    if not pack_urls:
        raise RuntimeError("No pack URLs discovered from the library page")

    root_count = declared_count(BeautifulSoup(root_html, "html.parser").get_text("\n", strip=True))
    all_packs: list[dict] = []
    all_prompts: list[dict] = []
    all_warnings: list[str] = []

    print(f"Discovered {len(pack_urls)} packs; site declares {root_count or '?'} prompts")
    for n, url in enumerate(pack_urls, 1):
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        html_path = raw_dir / f"{slug}.html"
        if refresh or not html_path.exists():
            print(f"[{n:02d}/{len(pack_urls):02d}] fetch {slug}")
            html = fetcher.get_text(url)
            html_path.write_text(html, encoding="utf-8")
        else:
            print(f"[{n:02d}/{len(pack_urls):02d}] cache {slug}")
            html = html_path.read_text(encoding="utf-8")

        pack, warnings = parse_pack(html, url)
        write_json(parsed_dir / f"{slug}.json", pack)
        all_packs.append({
            "name": pack["collection"]["name"],
            "slug": pack["collection"]["slug"],
            "url": url,
            "declared_prompt_count": pack["source"]["declared_prompt_count"],
            "parsed_prompt_count": len(pack["prompts"]),
            "json": f"source/hearmemanai/parsed/{slug}.json",
            "html": f"source/hearmemanai/raw_html/{slug}.html",
        })
        all_prompts.extend(pack["prompts"])
        all_warnings.extend(warnings)

    library = {
        "schema_version": 1,
        "source": {
            "provider": "HearmemanAI PROmpt",
            "library_url": LIBRARY_URL,
            "scraped_at": utc_now(),
            "declared_prompt_count": root_count,
            "discovered_pack_count": len(pack_urls),
        },
        "stats": {
            "parsed_prompt_count": len(all_prompts),
            "parsed_pack_count": len(all_packs),
        },
        "packs": all_packs,
        "prompts": all_prompts,
        "warnings": all_warnings,
    }
    library_path = out_dir / "source" / "hearmemanai" / "library.json"
    write_json(library_path, library)

    print(f"Parsed {len(all_prompts)} prompts across {len(all_packs)} packs")
    if root_count is not None and root_count != len(all_prompts):
        print(
            f"WARNING: site declares {root_count}, parsed {len(all_prompts)}; inspect warnings before curation",
            file=sys.stderr,
        )
    if all_warnings:
        print(f"Parser emitted {len(all_warnings)} warning(s)", file=sys.stderr)
    return library_path


def split_sentences(text: str) -> list[str]:
    flat = compact_ws(text)
    if not flat:
        return []
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(flat) if s.strip()]


def first_subject_candidate(text: str) -> str | None:
    # The subject is overwhelmingly established at the start; limiting the scan
    # avoids wardrobe/action mentions being mistaken for the subject declaration.
    head = compact_ws(text[:500])
    match = SUBJECT_RE.search(head)
    return compact_ws(match.group(0)) if match else None


def model_stats(prompts: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(p["model"] for p in prompts).items()))


def character_stats(prompts: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(p["character"] for p in prompts).items()))


def audit(library_path: Path, out_dir: Path) -> tuple[Path, Path]:
    library = json.loads(library_path.read_text(encoding="utf-8"))
    prompts: list[dict] = library.get("prompts", [])

    subject_counts: Counter[str] = Counter()
    subject_examples: defaultdict[str, list[str]] = defaultdict(list)
    no_subject: list[str] = []

    reference_sentence_counts: Counter[str] = Counter()
    identity_clause_counts: Counter[str] = Counter()
    generation_reference_counts: Counter[str] = Counter()
    second_reference_counts: Counter[str] = Counter()
    no_reference: list[str] = []
    multi_reference: list[dict] = []

    for p in prompts:
        text = p["prompt_original"]
        subject = first_subject_candidate(text)
        if subject:
            subject_counts[subject] += 1
            if len(subject_examples[subject]) < 5:
                subject_examples[subject].append(p["id"])
        else:
            no_subject.append(p["id"])

        ref_sentences = [s for s in split_sentences(text) if "reference image" in s.casefold()]
        if not ref_sentences:
            no_reference.append(p["id"])
        if len(ref_sentences) > 1:
            multi_reference.append({"id": p["id"], "count": len(ref_sentences)})
        for sentence in ref_sentences:
            reference_sentence_counts[sentence] += 1
            low = sentence.casefold()
            if "preserve the character identity" in low:
                identity_clause_counts[sentence] += 1
            if any(x in low for x in ("paste", "composite", "used only for", "use the reference image only")):
                generation_reference_counts[sentence] += 1
            if "second reference image" in low:
                second_reference_counts[sentence] += 1

    def counter_rows(counter: Counter[str]) -> list[dict]:
        return [
            {"text": text, "count": count}
            for text, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
        ]

    audit_obj = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "source_library": str(library_path),
        "summary": {
            "prompt_count": len(prompts),
            "collection_count": len({p["collection"] for p in prompts}),
            "models": model_stats(prompts),
            "characters": character_stats(prompts),
            "subject_candidate_variants": len(subject_counts),
            "prompts_without_subject_candidate": len(no_subject),
            "reference_sentence_variants": len(reference_sentence_counts),
            "prompts_without_reference_image_language": len(no_reference),
            "prompts_with_multiple_reference_sentences": len(multi_reference),
        },
        "subject_candidates": [
            {"text": text, "count": count, "example_prompt_ids": subject_examples[text]}
            for text, count in sorted(subject_counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
        ],
        "reference_sentences": counter_rows(reference_sentence_counts),
        "identity_clauses": counter_rows(identity_clause_counts),
        "generation_reference_clauses": counter_rows(generation_reference_counts),
        "second_reference_image_clauses": counter_rows(second_reference_counts),
        "review_lists": {
            "no_subject_candidate": no_subject,
            "no_reference_image_language": no_reference,
            "multiple_reference_sentences": multi_reference,
        },
        "note": "Audit only. No source prompt text has been transformed.",
    }

    reports_dir = out_dir / "reports"
    json_path = reports_dir / "pattern_audit.json"
    md_path = reports_dir / "pattern_audit.md"
    write_json(json_path, audit_obj)

    lines: list[str] = []
    s = audit_obj["summary"]
    lines += [
        "# HearmemanAI prompt-pattern audit",
        "",
        f"Generated: {audit_obj['generated_at']}",
        "",
        "> Phase 1 audit only: **no prompt text was modified.**",
        "",
        "## Summary",
        "",
        f"- Prompts: **{s['prompt_count']}**",
        f"- Collections: **{s['collection_count']}**",
        f"- Subject candidate variants: **{s['subject_candidate_variants']}**",
        f"- Prompts without an automatically detected subject candidate: **{s['prompts_without_subject_candidate']}**",
        f"- Distinct sentences containing `reference image`: **{s['reference_sentence_variants']}**",
        f"- Prompts without `reference image` language: **{s['prompts_without_reference_image_language']}**",
        f"- Prompts with multiple reference-image sentences: **{s['prompts_with_multiple_reference_sentences']}**",
        "",
        "### Models",
        "",
    ]
    for model, count in s["models"].items():
        lines.append(f"- `{model}`: {count}")

    lines += ["", "## Subject phrase candidates", "", "| Count | Candidate |", "|---:|---|"]
    for row in audit_obj["subject_candidates"]:
        candidate = row["text"].replace("|", "\\|")
        lines.append(f"| {row['count']} | `{candidate}` |")

    def add_counter_section(title: str, rows: list[dict], limit: int | None = None) -> None:
        lines.extend(["", f"## {title}", ""])
        chosen = rows if limit is None else rows[:limit]
        if not chosen:
            lines.append("_None found._")
            return
        for row in chosen:
            lines.append(f"- **{row['count']}×** {row['text']}")

    add_counter_section("Identity/reference sentences", audit_obj["identity_clauses"])
    add_counter_section("Other reference-generation instructions", audit_obj["generation_reference_clauses"])
    add_counter_section("Second-reference/product instructions", audit_obj["second_reference_image_clauses"])

    lines += [
        "",
        "## Review queues",
        "",
        f"- No subject candidate: {len(no_subject)}",
        f"- No reference-image language: {len(no_reference)}",
        f"- Multiple reference-image sentences: {len(multi_reference)}",
        "",
        "The JSON report contains the prompt IDs for each review queue.",
        "",
        "## Proposed phase-2 use",
        "",
        "Use this report to define explicit, tested transformations for `[[SUBJECT]]` and reference blocks. Keep `prompt_original` immutable and write normalized/template text into a separate curated layer.",
        "",
    ]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return json_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["scrape", "audit", "all"])
    ap.add_argument("--out", type=Path, default=Path("prompt-library"), help="Output root (default: prompt-library)")
    ap.add_argument("--library", type=Path, help="Existing library.json for audit")
    ap.add_argument("--refresh", action="store_true", help="Re-download HTML snapshots")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--delay", type=float, default=0.25, help="Delay between HTTP requests in seconds")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    library_path = args.library or (args.out / "source" / "hearmemanai" / "library.json")

    if args.command in {"scrape", "all"}:
        library_path = scrape(args.out, refresh=args.refresh, timeout=args.timeout, delay=args.delay)
    if args.command in {"audit", "all"}:
        if not library_path.exists():
            ap.error(f"library not found: {library_path}; run scrape first or pass --library")
        audit(library_path, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
