from hearmeman_ingest import discover_pack_urls


def test_pack_index_and_nested_paths_are_not_packs():
    html = """
    <html><body>
      <a href="/prompts/packs/">All packs</a>
      <a href="/prompts/packs/test-pack/">Test pack</a>
      <a href="/prompts/packs/test-pack">Same pack without trailing slash</a>
      <a href="/prompts/packs/test-pack/details/">Nested page</a>
    </body></html>
    """

    assert discover_pack_urls(html) == [
        "https://hearmemanai.com/prompts/packs/test-pack/"
    ]
