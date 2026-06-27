import bandcamp_reco.main as main_mod
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
