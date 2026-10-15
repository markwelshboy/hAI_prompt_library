from hearmeman_ingest import _parse_prompt_heading, parse_pack


def nested_header_fixture_html():
    return """
    <html><body>
      <h1>Tanning Shots</h1>
      <div>2 prompts</div>
      <img alt="Image: Ashley, tanning shots AI image" src="https://cdn.example/a.webp">
      <img alt="Image: Brooke, tanning shots AI image" src="https://cdn.example/b.webp">

      <h2><span>Browse and copy prompts</span></h2>
      <p>Interactive search, saved prompts, and contributions need JavaScript. You can still read and manually copy these exact prompts.</p>

      <h3>
        <span>Tanning Shots</span><span> · </span>
        <span>Ashley</span><span> · </span>
        <span>gpt-image-2</span>
      </h3>
      <p>Prompt one. Preserve the character identity from the reference image.</p>
      <p>Second paragraph with periods. Still the same prompt.</p>
      <a href="#">View prompt</a>

      <h3>
        <span>Tanning Shots</span><span> · </span>
        <span>Brooke</span><span> · </span>
        <span>gpt-image-2</span>
      </h3>
      <p>Prompt two.</p>

      <h2>Make these prompts your own character</h2>
    </body></html>
    """


def non_heading_header_fixture_html():
    return """
    <html><body>
      <h1>Tanning Shots</h1>
      <div>2 prompts</div>
      <img alt="Image: Ashley, tanning shots AI image" src="https://cdn.example/a.webp">
      <img alt="Image: Brooke, tanning shots AI image" src="https://cdn.example/b.webp">

      <div><span>Browse and copy prompts</span></div>
      <div>Interactive search, saved prompts, and contributions need JavaScript. You can still read and manually copy these exact prompts.</div>

      <div class="prompt-fallback">
        <span>Tanning Shots</span><span> · </span><span>Ashley</span><span> · </span><span>gpt-image-2</span>
      </div>
      <div>Prompt one.</div>
      <div>Second paragraph.</div>
      <a>Open this collection</a>

      <div class="prompt-fallback">
        <span>Tanning Shots</span><span> · </span><span>Brooke</span><span> · </span><span>gpt-image-2</span>
      </div>
      <div>Prompt two.</div>
      <a>Open this collection</a>

      <div>Make these prompts your own character</div>
    </body></html>
    """


def test_nested_heading_markup_is_combined_before_parsing():
    pack, warnings = parse_pack(
        nested_header_fixture_html(),
        "https://hearmemanai.com/prompts/packs/tanning-shots/",
    )

    assert warnings == []
    assert len(pack["prompts"]) == 2
    assert pack["prompts"][0]["character"] == "Ashley"
    assert pack["prompts"][1]["character"] == "Brooke"
    assert (
        pack["prompts"][0]["prompt_original"]
        == "Prompt one. Preserve the character identity from the reference image.\n"
           "Second paragraph with periods. Still the same prompt."
    )


def test_headers_need_not_be_heading_elements():
    pack, warnings = parse_pack(
        non_heading_header_fixture_html(),
        "https://hearmemanai.com/prompts/packs/tanning-shots/",
    )

    assert warnings == []
    assert len(pack["prompts"]) == 2
    assert pack["prompts"][0]["character"] == "Ashley"
    assert pack["prompts"][0]["model"] == "gpt-image-2"
    assert pack["prompts"][0]["prompt_original"] == "Prompt one.\nSecond paragraph."
    assert pack["prompts"][1]["character"] == "Brooke"
    assert pack["prompts"][1]["prompt_original"] == "Prompt two."


def test_collection_name_may_itself_contain_middle_dot():
    assert _parse_prompt_heading(
        "Flash Selfie Collage · GPT Image 2 · Emma · nano-banana-2"
    ) == (
        "Flash Selfie Collage · GPT Image 2",
        "Emma",
        "nano-banana-2",
    )
