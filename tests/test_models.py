from bandcamp_reco.models import Album, album_key, art_url_from_id


def _album(url):
    return Album(item_id="1", album_id="9", title="T", artist="A", url=url, art_url=None)


def test_album_key_strips_query_and_trailing_slash():
    a = _album("https://artist.bandcamp.com/album/x/?from=fanpub")
    b = _album("https://artist.bandcamp.com/album/x")
    assert album_key(a) == album_key(b) == "https://artist.bandcamp.com/album/x"


def test_art_url_from_id_builds_bcbits_url():
    assert art_url_from_id(123) == "https://f4.bcbits.com/img/a123_16.jpg"


def test_art_url_from_id_none_when_missing():
    assert art_url_from_id(None) is None
    assert art_url_from_id("") is None


def test_album_key_from_url_strips_query_and_trailing_slash():
    from bandcamp_reco.models import album_key_from_url
    assert (album_key_from_url("https://x.bandcamp.com/album/y/?from=1")
            == "https://x.bandcamp.com/album/y")
