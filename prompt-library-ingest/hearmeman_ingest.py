#!/usr/bin/env python3
"""CLI facade for the HearmemanAI prompt-library ingest tool.

The implementation lives in :mod:`hearmeman_ingest_core`. This module carries
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


_MODEL_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_UI_ONLY_TOKENS = {"View prompt"}


def discover_pack_urls(html: str, base_url: str = LIBRARY_URL) -> list[str]:
    """Return only concrete HearmemanAI pack collection URLs.

    The library page links both to ``/prompts/packs/`` (the pack index) and to
    individual collections. The index is not itself a pack. Nested paths below
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
    """Parse ``Collection · Character · model`` from rendered fallback text.

    Parse from the right because a collection name itself may contain a middle
    dot. The model value in the site's fallback section is a compact slug such
    as ``gpt-image-2`` or ``nano-banana-2``; validating that final token prevents
    a candidate from swallowing the first sentence of the prompt body.
    """
    text = compact_ws(text)
    parts = [compact_ws(p) for p in re.split(r"\s*·\s*", text)]
    if len(parts) < 3 or not all(parts):
        return None

    collection = HEADER_SEP.join(parts[:-2])
    character = parts[-2]
    model = parts[-1]

    if not _MODEL_TOKEN_RE.fullmatch(model):
        return None

    return collection, character, model


def _consume_prompt_header(
    tokens: list[str],
    start: int,
    expected_collection: str,
    max_tokens: int = 12,
) -> tuple[tuple[str, str, str], int] | None:
    """Recognize a prompt header even when HTML splits it across text nodes.

    The live fallback markup has changed shape over time. Sometimes the whole
    ``Collection · Character · model`` string is one text node; sometimes each
    component and middle-dot separator is emitted as a separate node. Build
    progressively wider candidates and accept the first valid header whose
    collection matches the pack's H1.
    """
    expected = compact_ws(expected_collection).casefold()
    limit = min(len(tokens), start + max_tokens)

    for end in range(start + 1, limit + 1):
        candidate = " ".join(tokens[start:end])
        parsed = _parse_prompt_heading(candidate)
        if parsed is None:
            continue

        collection, _character, _model = parsed
        if compact_ws(collection).casefold() != expected:
            continue

        return parsed, end - start

    return None


def _fallback_tokens(soup: BeautifulSoup) -> list[str]:
    """Return normalized visible-text tokens from the fallback prompt section."""
    tokens = [compact_ws(s) for s in soup.stripped_strings]

    try:
        start = tokens.index("Browse and copy prompts") + 1
    except ValueError as exc:
        raise ValueError("Could not find fallback prompt section") from exc

    result: list[str] = []
    for token in tokens[start:]:
        if token in STOP_MARKERS:
            break

        if token in SKIP_TOKENS or token in _UI_ONLY_TOKENS:
            continue

        # The UI anchor is normally a separate text node, but tolerate markup
        # that concatenates it with the next fallback header.
        if token.startswith("Open this collection"):
            token = token[len("Open this collection"):].strip()
            if not token:
                continue

        result.append(token)

    return result


def parse_pack(html: str, url: str) -> tuple[dict, list[str]]:
    """Parse one pack from the site's non-JavaScript fallback text.

    Do not depend on prompt headers being specific DOM elements. Instead scan
    normalized text nodes after ``Browse and copy prompts`` and recognize each
    header by its ``Collection · Character · model`` grammar. This preserves
    multiline prompt blocks while tolerating nested spans/divs around headers.
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

    try:
        tokens = _fallback_tokens(soup)
    except ValueError as exc:
        raise ValueError(f"Could not find fallback prompt section in {url}") from exc

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

    i = 0
    while i < len(tokens):
        consumed = _consume_prompt_header(tokens, i, page_title)
        if consumed is not None:
            flush()
            current_header, width = consumed
            i += width
            continue

        if current_header is not None:
            current_blocks.append(tokens[i])
        i += 1

    flush()

    if not records:
        warnings.append(
            f"{page_title}: fallback section found but no prompt headers parsed"
        )

    collections = {r.collection for r in records}
    if records and len(collections) == 1:
        collection_name = records[0].collection
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
