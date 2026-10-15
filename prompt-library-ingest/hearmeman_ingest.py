#!/usr/bin/env python3
"""CLI facade for the HearmemanAI prompt-library ingest tool.

The implementation lives in :mod:`hearmeman_ingest_core`.  Pack discovery is
kept here because the public library page also links to the pack index itself;
only concrete ``/prompts/packs/<slug>/`` collection URLs are valid ingest
inputs.
"""
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import hearmeman_ingest_core as _core
from hearmeman_ingest_core import *  # noqa: F401,F403 - preserve public API


def discover_pack_urls(html: str, base_url: str = LIBRARY_URL) -> list[str]:
    """Return only concrete HearmemanAI pack collection URLs.

    The library page links both to ``/prompts/packs/`` (the pack index) and to
    individual collections.  The index is not itself a pack and does not have
    the fallback ``Browse and copy prompts`` section expected by ``parse_pack``.
    Nested paths below a pack are ignored as well.
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


# scrape() is defined in the core module, so update its module-global binding.
_core.discover_pack_urls = discover_pack_urls


if __name__ == "__main__":
    raise SystemExit(_core.main())
