from bandcamp_reco.models import Album
from bandcamp_reco.score import Recommendation
from bandcamp_reco.render import render_html, write_html


def _rec():
    album = Album(
        item_id="1", album_id="9", title="Weird & Wonderful",
        artist="Cool <Band>", url="https://x.bandcamp.com/album/y",
        art_url="https://f4.bcbits.com/img/a1_16.jpg", tags=("ambient", "drone"),
    )
    return Recommendation(album=album, score=12.5, fan_count=7,
                          typical_shared=9, why="Owned by 7 fans who each share ~9 albums with your collection.")


def test_render_html_contains_fields_and_escapes():
    html = render_html([_rec()], username="jmaskell")
    assert "https://x.bandcamp.com/album/y" in html
    assert "Weird &amp; Wonderful" in html       # escaped &
    assert "Cool &lt;Band&gt;" in html           # escaped <>
    assert "ambient" in html
    assert "7 fans" in html
    assert "jmaskell" in html


def test_write_html_writes_file(tmp_path):
    p = tmp_path / "out.html"
    write_html("<html>ok</html>", str(p))
    assert p.read_text() == "<html>ok</html>"
