import requests

import bandcamp_reco.main as main_mod
import bandcamp_reco.fans as fans_mod
from bandcamp_reco.config import Config
from bandcamp_reco.models import Album


def _cfg(tmp_path):
    return Config(
        username="me", supporters_per_album=5, max_fans=10,
        max_albums_per_fan=50, top_n=5, request_delay=0.0,
        cache_path=str(tmp_path / "c.db"),
        output_path=str(tmp_path / "out.html"),
    )


def _album(url, tags=()):
    return Album(item_id=url, album_id=None, title=url, artist="A",
                 url=url, art_url=None, tags=tags)


def test_run_pipeline_writes_html_and_returns_recs(tmp_path, monkeypatch):
    owned = [_album("https://own/1"), _album("https://own/2")]

    def fake_get_collection(username, fetcher, cache, max_items=None):
        if username == "me":
            return owned
        return owned + [_album("https://cand/x")]  # a fan who shares your taste

    monkeypatch.setattr(main_mod, "get_collection", fake_get_collection)
    import bandcamp_reco.fans as fans_mod
    monkeypatch.setattr(fans_mod, "get_collection", fake_get_collection)
    monkeypatch.setattr(main_mod, "get_supporters",
                        lambda album, fetcher, cache, limit: ["fan1"])
    monkeypatch.setattr(main_mod, "get_album_page",
                        lambda album, fetcher, cache: type(
                            "I", (), {"tralbum_id": "1", "tags": ("ambient",),
                                      "supporter_usernames": []})())

    cfg = _cfg(tmp_path)
    recs = main_mod.run(cfg, fetcher=None, cache=None)
    assert any(r.album.url == "https://cand/x" for r in recs)
    assert (tmp_path / "out.html").exists()
    # tag enrichment applied to rendered candidate
    top = next(r for r in recs if r.album.url == "https://cand/x")
    assert top.album.tags == ("ambient",)


def test_run_skips_failing_album_in_supporters_loop(tmp_path, monkeypatch):
    """A deleted/private owned album should be skipped, not crash the whole run."""
    album_ok = _album("https://own/ok")
    album_bad = _album("https://own/bad")
    owned = [album_bad, album_ok]

    def fake_get_collection(username, fetcher, cache, max_items=None):
        if username == "me":
            return owned
        # fan1 owns a candidate album not in owned set
        return owned + [_album("https://cand/y")]

    monkeypatch.setattr(main_mod, "get_collection", fake_get_collection)
    monkeypatch.setattr(fans_mod, "get_collection", fake_get_collection)

    def fake_get_supporters(album, fetcher, cache, limit):
        if album.url == "https://own/bad":
            raise requests.HTTPError("404 Not Found")
        return ["fan1"]

    monkeypatch.setattr(main_mod, "get_supporters", fake_get_supporters)
    monkeypatch.setattr(main_mod, "get_album_page",
                        lambda album, fetcher, cache: type(
                            "I", (), {"tralbum_id": "1", "tags": (),
                                      "supporter_usernames": []})())

    cfg = _cfg(tmp_path)
    recs = main_mod.run(cfg, fetcher=None, cache=None)
    # run must complete and produce recommendations from the surviving album
    assert (tmp_path / "out.html").exists()
    assert any(r.album.url == "https://cand/y" for r in recs)
