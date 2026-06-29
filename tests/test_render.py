import json

from bandcamp_reco.render import render_html, write_html


DEFAULTS = {"affinity_cap": 4, "max_per_source": 2, "top_n": 50, "min_fans": 2,
            "hide_owned_sources": False}


def _pool():
    return [{
        "title": "Weird & Wonderful",
        "artist": "Cool <Band>",
        "url": "https://x.bandcamp.com/album/y",
        "art": "https://f4.bcbits.com/img/a1_16.jpg",
        "source": "x",
        "tags": ["ambient", "drone"],
        "hist": {"2": 5, "3": 2},
        "fans": 7,
    }]


def test_render_embeds_pool_and_controls():
    html = render_html(_pool(), username="jmaskell", defaults=DEFAULTS)
    # candidate data is embedded for client-side ranking
    assert "https://x.bandcamp.com/album/y" in html
    assert "Weird & Wonderful" in html
    assert "ambient" in html
    # the affinity-cap control is present and defaults are embedded to seed it
    assert 'id="cap"' in html
    assert '"affinity_cap"' in html
    assert "jmaskell" in html


def test_render_embeds_owned_sources_and_filter():
    html = render_html(_pool(), username="u", defaults=DEFAULTS,
                       owned_sources=["kompakt", "manualsmiles"])
    assert 'id="hideOwned"' in html          # the filter checkbox exists
    assert "kompakt" in html                  # owned sources embedded
    assert "manualsmiles" in html
    assert "OWNED_SOURCES" in html            # JS uses them


def test_render_escapes_username_in_title():
    html = render_html([], username="a<b>&c", defaults=DEFAULTS)
    assert "a&lt;b&gt;&amp;c" in html
    assert "<b>" not in html  # raw tag not injected


def test_render_neutralizes_script_breakout_in_data():
    pool = _pool()
    pool[0]["title"] = "evil</script>alert(1)"
    html = render_html(pool, username="u", defaults=DEFAULTS)
    # data cannot close the script tag: only the real closing </script> remains
    assert html.count("</script>") == 1
    assert "<\\/script>" in html  # the data's closing sequence was escaped


def test_embedded_pool_is_valid_json():
    html = render_html(_pool(), username="u", defaults=DEFAULTS)
    marker = "const POOL = "
    start = html.index(marker) + len(marker)
    end = html.index(";\n", start)
    raw = html[start:end].replace("<\\/", "</")  # undo breakout-escaping
    data = json.loads(raw)
    assert data[0]["title"] == "Weird & Wonderful"
    assert data[0]["hist"] == {"2": 5, "3": 2}


def test_write_html_writes_file(tmp_path):
    p = tmp_path / "out.html"
    write_html("<html>ok</html>", str(p))
    assert p.read_text() == "<html>ok</html>"


def _apple_pool():
    p = _pool()
    p[0]["apple"] = "available"
    p[0]["appleUrl"] = "https://music.apple.com/gb/album/z/123"
    p[0]["appleName"] = "Weird & Wonderful"
    p[0]["appleArtist"] = "Cool Band"
    return p


def test_render_apple_disabled_when_not_requested():
    html = render_html(_pool(), username="u", defaults=DEFAULTS)
    assert "APPLE_ENABLED = false" in html


def test_render_apple_enabled_embeds_controls_and_data():
    html = render_html(_apple_pool(), username="u", defaults=DEFAULTS,
                       apple_enabled=True)
    assert "APPLE_ENABLED = true" in html
    assert 'id="hideOnApple"' in html
    assert 'id="hideNotApple"' in html
    assert "https://music.apple.com/gb/album/z/123" in html


def test_render_includes_flag_ui_when_apple_enabled():
    html = render_html(_apple_pool(), username="u", defaults=DEFAULTS,
                       apple_enabled=True)
    assert 'id="flagBar"' in html
    assert "apple-music-flags.json" in html


def test_render_has_no_apple_flag_when_disabled():
    html = render_html(_pool(), username="u", defaults=DEFAULTS)
    assert "APPLE_ENABLED = false" in html
