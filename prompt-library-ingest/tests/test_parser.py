from hearmeman_ingest import discover_pack_urls, parse_pack, first_subject_candidate


def fixture_html():
    return '''
    <html><body>
      <a href="/prompts/packs/test-pack/">Test</a>
      <h1>Test Pack</h1>
      <div>2 prompts</div>
      <img alt="Image: Alice, test pack AI image" src="https://cdn.example/a.webp">
      <img alt="Image: Bea, test pack AI image" src="https://cdn.example/b.webp">
      <h2>Browse and copy prompts</h2>
      <p>Interactive search, saved prompts, and contributions need JavaScript. You can still read and manually copy these exact prompts.</p>
      <h3>Test Pack · Alice · nano-banana-2</h3>
      <p>Full body photo of one adult woman. Preserve the character identity from the reference image, keeping identity stable.</p>
      <p>Second paragraph with periods. Still the same prompt.</p>
      <a>Open this collection</a>
      <h3>Test Pack · Bea · gpt-image-2</h3>
      <p>Candid photo of a single fictional adult woman from the reference image, used only for identity. Generate a new native photo; do not paste or composite the reference.</p>
      <a>Open this collection</a>
      <h2>Make these prompts your own character</h2>
    </body></html>
    '''


def test_discovery():
    urls = discover_pack_urls(fixture_html())
    assert urls == ["https://hearmemanai.com/prompts/packs/test-pack/"]


def test_parse_pack_and_multiline():
    pack, warnings = parse_pack(fixture_html(), "https://hearmemanai.com/prompts/packs/test-pack/")
    assert warnings == []
    assert len(pack["prompts"]) == 2
    p0 = pack["prompts"][0]
    assert p0["character"] == "Alice"
    assert p0["model"] == "nano-banana-2"
    assert "\n" in p0["prompt_original"]
    assert "Second paragraph with periods." in p0["prompt_original"]
    assert p0["image_url"] == "https://cdn.example/a.webp"


def test_subject_candidates():
    assert first_subject_candidate("Photo of one adult woman. Rest.") == "one adult woman"
    assert first_subject_candidate("Candid photo of a single fictional adult woman from the reference image, used only for identity. Rest.") == "a single fictional adult woman from the reference image, used only for identity"
