import dataclasses

import requests

import bandcamp_reco.main as main_mod
import bandcamp_reco.fans as fans_mod
from bandcamp_reco.config import Config, AppleMusicConfig
from bandcamp_reco.models import Album
from bandcamp_reco.apple_music import AppleMatch


def _cfg(tmp_path):
    return Config(
        username="me", supporters_per_album=5, max_fans=10,
        max_albums_per_fan=50, top_n=5, request_delay=0.0,
        cache_path=str(tmp_path / "c.db"),
        output_path=str(tmp_path / "out.html"),
        affinity_cap=4, max_per_source=2, hide_owned_sources=False,
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


def test_owned_albums_excluded_even_beyond_limit(tmp_path, monkeypatch):
    """--limit bounds the supporter crawl but must NOT shrink the owned-exclusion set.

    Regression: with --limit N, owned_keys was built from only the first N owned
    albums, so the user's other owned albums leaked back in as recommendations.
    """
    owned = [_album("https://own/1"), _album("https://own/2"), _album("https://own/3")]

    def fake_get_collection(username, fetcher, cache, max_items=None):
        if username == "me":
            result = owned
        else:
            # fan1 owns own/2 (an owned album BEYOND limit=1) plus a real candidate
            result = [_album("https://own/2"), _album("https://cand/x")]
        return result[:max_items] if max_items is not None else result

    monkeypatch.setattr(main_mod, "get_collection", fake_get_collection)
    monkeypatch.setattr(fans_mod, "get_collection", fake_get_collection)
    monkeypatch.setattr(main_mod, "get_supporters",
                        lambda album, fetcher, cache, limit: ["fan1"])
    monkeypatch.setattr(main_mod, "get_album_page",
                        lambda album, fetcher, cache: type(
                            "I", (), {"tralbum_id": "1", "tags": (),
                                      "supporter_usernames": []})())

    cfg = _cfg(tmp_path)
    recs = main_mod.run(cfg, fetcher=None, cache=None, limit=1)
    rec_urls = {r.album.url for r in recs}
    assert "https://own/2" not in rec_urls  # owned — excluded despite limit=1
    assert "https://cand/x" in rec_urls


def test_user_not_sampled_as_their_own_fan(tmp_path, monkeypatch):
    """The user supports their own albums; they must not be fetched as a fan."""
    owned = [_album("https://own/1"), _album("https://own/2")]
    calls = []

    def fake_get_collection(username, fetcher, cache, max_items=None):
        calls.append(username)
        if username == "me":
            return owned
        return [_album("https://cand/x")]

    monkeypatch.setattr(main_mod, "get_collection", fake_get_collection)
    monkeypatch.setattr(fans_mod, "get_collection", fake_get_collection)
    # the user "me" appears among the supporters of their own album
    monkeypatch.setattr(main_mod, "get_supporters",
                        lambda album, fetcher, cache, limit: ["me", "fan1"])
    monkeypatch.setattr(main_mod, "get_album_page",
                        lambda album, fetcher, cache: type(
                            "I", (), {"tralbum_id": "1", "tags": (),
                                      "supporter_usernames": []})())

    cfg = _cfg(tmp_path)
    main_mod.run(cfg, fetcher=None, cache=None)
    # "me" is fetched once as the owner, never again as a sampled fan
    assert calls.count("me") == 1


def _apple_cfg(tmp_path):
    return dataclasses.replace(_cfg(tmp_path), apple_music=AppleMusicConfig(
        enabled=True, country="gb", request_delay=0.0))


def _base_stubs(monkeypatch, owned):
    def fake_get_collection(username, fetcher, cache, max_items=None):
        if username == "me":
            return owned
        return owned + [_album("https://cand/x")]
    monkeypatch.setattr(main_mod, "get_collection", fake_get_collection)
    monkeypatch.setattr(fans_mod, "get_collection", fake_get_collection)
    # two supporters so the shared candidate reaches the pool (min_fans=2)
    monkeypatch.setattr(main_mod, "get_supporters",
                        lambda album, fetcher, cache, limit: ["fan1", "fan2"])
    monkeypatch.setattr(main_mod, "get_album_page",
                        lambda album, fetcher, cache: type(
                            "I", (), {"tralbum_id": "1", "tags": (),
                                      "supporter_usernames": []})())


def test_run_annotates_apple_music_when_enabled(tmp_path, monkeypatch):
    _base_stubs(monkeypatch, [_album("https://own/1")])
    monkeypatch.setattr(main_mod, "AppleMusicClient", lambda **kw: object())
    monkeypatch.setattr(main_mod, "lookup_pool",
                        lambda pool, client, cache, country: {
                            "https://cand/x": AppleMatch(
                                "available", "https://music.apple.com/gb/album/z/9",
                                "X", "A")})
    main_mod.run(_apple_cfg(tmp_path), fetcher=None, cache=None)
    html = (tmp_path / "out.html").read_text()
    assert "APPLE_ENABLED = true" in html
    assert "https://music.apple.com/gb/album/z/9" in html


def test_run_without_apple_config_keeps_feature_off(tmp_path, monkeypatch):
    _base_stubs(monkeypatch, [_album("https://own/1")])
    main_mod.run(_cfg(tmp_path), fetcher=None, cache=None)
    html = (tmp_path / "out.html").read_text()
    assert "APPLE_ENABLED = false" in html


def test_run_survives_apple_failure(tmp_path, monkeypatch):
    _base_stubs(monkeypatch, [_album("https://own/1")])

    def boom(pool, client, cache, country):
        raise RuntimeError("network down")
    monkeypatch.setattr(main_mod, "AppleMusicClient", lambda **kw: object())
    monkeypatch.setattr(main_mod, "lookup_pool", boom)
    main_mod.run(_apple_cfg(tmp_path), fetcher=None, cache=None)
    html = (tmp_path / "out.html").read_text()
    assert "APPLE_ENABLED = false" in html
