#!/usr/bin/env python3
"""CLI facade for the HearmemanAI prompt-library ingest tool.

The implementation lives in :mod:`hearmeman_ingest_core`.  This module carries
small live-site adapters where the public site's HTML shape differs from the
minimal parser fixtures in the core implementation.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import hearmeman_ingest_core as _core
from hearmeman_ingest_core import *  # noqa: F401,F403 - preserve public API


_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def discover_pack_urls(html: str, base_url: str = LIBRARY_URL) -> list[str]:
    """Return only concrete HearmemanAI pack collection URLs.

    The library page links both to ``/prompts/packs/`` (the pack index) and to
    individual collections.  The index is not itself a pack. Nested paths below
    a pack are ignored as well.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        abs_url = urljoin(base_url, str(a.get("href")))
        parsed = urlparse(abs_url)
        path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"

        if not parsed.netloc.endswith("hearmemanai.com"):
            continue
        if not path.startswith(PACK_PREFIX):
            continue

        remainder = path[len(PACK_PREFIX):].strip("/")
        if not remainder or "/" in remainder:
            continue

        urls.add(f"{parsed.scheme}://{parsed.netloc}{PACK_PREFIX}{remainder}/")

    return sorted(urls)


def _parse_prompt_heading(text: str) -> tuple[str, str, str] | None:
    """Parse ``Collection · Character · model`` from a rendered heading.

    The real site renders each visible heading from nested elements.  Parsing
    the heading element's combined text avoids depending on ``stripped_strings``
    yielding the entire heading as one token.  Right-side parsing is important
    because some collection names themselves contain `` · ``.
    """
    text = compact_ws(text)
    parts = [compact_ws(p) for p in re.split(r"\s*·\s*", text)]
    if len(parts) < 3 or not all(parts):
        return None
    collection = HEADER_SEP.join(parts[:-2])
    character = parts[-2]
    model = parts[-1]
    return collection, character, model


def parse_pack(html: str, url: str) -> tuple[dict, list[str]]:
    """Parse one pack using DOM-level headings and paragraph blocks.

    On the live site, prompt headings are visually a single string but are
    composed from nested HTML elements.  The original parser iterated
    ``soup.stripped_strings`` and therefore never saw a complete header token.
    This parser combines each heading's descendant text first, then accumulates
    paragraph blocks until the next prompt heading.
    """
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        raise ValueError(f"No <h1> collection name found: {url}")

    page_title = compact_ws(h1.get_text(" ", strip=True))
    collection_slug = slugify(
        urlparse(url).path.rstrip("/").split("/")[-1] or page_title
    )
    page_text = soup.get_text("\n", strip=True)
    count = declared_count(page_text)
    images = prompt_images(soup)

    browse_heading = None
    for heading in soup.find_all(_HEADING_TAGS):
        if compact_ws(heading.get_text(" ", strip=True)) == "Browse and copy prompts":
            browse_heading = heading
            break
    if browse_heading is None:
        raise ValueError(f"Could not find fallback prompt section in {url}")

    records: list[PromptRecord] = []
    warnings: list[str] = []
    current_header: tuple[str, str, str] | None = None
    current_blocks: list[str] = []

    def flush() -> None:
        nonlocal current_header, current_blocks
        if current_header is None:
            current_blocks = []
            return

        collection, character, model = current_header
        cleaned = [b for b in current_blocks if b and b not in SKIP_TOKENS]
        prompt = "\n".join(cleaned).strip()
        if not prompt:
            warnings.append(
                f"{collection}: empty prompt for {character} / {model}"
            )
            current_header = None
            current_blocks = []
            return

        idx = len(records)
        img = images[idx] if idx < len(images) else None
        if (
            img
            and img.character_from_alt
            and img.character_from_alt.casefold() != character.casefold()
        ):
            warnings.append(
                f"{collection} #{idx}: image character "
                f"{img.character_from_alt!r} != header character {character!r}"
            )

        digest = sha256_text(prompt)
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

    # Only headings and paragraphs matter here. Ignoring anchors means UI text
    # such as "View prompt" cannot leak into the prompt body.
    for element in browse_heading.find_all_next([*_HEADING_TAGS, "p"]):
        text = compact_ws(element.get_text(" ", strip=True))
        if not text:
            continue

        if text in STOP_MARKERS:
            flush()
            break

        if element.name in _HEADING_TAGS:
            header = _parse_prompt_heading(text)
            if header is not None:
                flush()
                current_header = header
            continue

        if element.name == "p" and current_header is not None:
            if text in SKIP_TOKENS:
                continue
            current_blocks.append(text)
    else:
        flush()

    if not records:
        warnings.append(
            f"{page_title}: fallback section found but no prompt headings parsed"
        )

    collections = {r.collection for r in records}
    if records and len(collections) == 1:
        collection_name = records[0].collection
        if page_title.casefold() != collection_name.casefold():
            warnings.append(
                f"{page_title}: <h1> differs from prompt collection "
                f"{collection_name!r}"
            )
    else:
        collection_name = page_title
        if len(collections) > 1:
            warnings.append(
                f"{page_title}: parsed multiple collection names: "
                + ", ".join(sorted(collections))
            )

    if count is not None and count != len(records):
        warnings.append(
            f"{collection_name}: declared {count} prompts but parsed {len(records)}"
        )
    if images and len(images) != len(records):
        warnings.append(
            f"{collection_name}: found {len(images)} prompt-card images "
            f"but parsed {len(records)} prompts"
        )

    pack = {
        "schema_version": 1,
        "source": {
            "provider": "HearmemanAI PROmpt",
            "url": url,
            "scraped_at": utc_now(),
            "declared_prompt_count": count,
        },
        "collection": {
            "name": collection_name,
            "slug": collection_slug,
        },
        "prompts": [asdict(r) for r in records],
        "warnings": warnings,
    }
    return pack, warnings


# scrape() is defined in the core module, so update the module-global bindings
# it resolves at runtime.
_core.discover_pack_urls = discover_pack_urls
_core.parse_pack = parse_pack


if __name__ == "__main__":
    raise SystemExit(_core.main())
