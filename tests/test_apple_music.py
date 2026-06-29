import pytest

from bandcamp_reco.apple_music import normalize, match_album, AppleMatch, AppleMusicClient, AppleRateLimited, AppleSearchError


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("bandcamp_reco.apple_music.time.sleep", lambda *_: None)
    monkeypatch.setattr("bandcamp_reco.apple_music.random.uniform", lambda *_: 0.0)


def _result(name, artist, url="https://music.apple.com/gb/album/x/1"):
    return {"collectionName": name, "artistName": artist, "collectionViewUrl": url}


def test_normalize_strips_brackets_diacritics_and_punctuation():
    assert normalize("Sǽ (Deluxe Edition)") == "sae"
    assert normalize("Album - EP") == "album"
    assert normalize("A/B & C!") == "a b c"
    assert normalize("ÆON") == "aeon"      # uppercase ligature
    assert normalize("Œuvre") == "oeuvre"  # lowercase ligature mapping


def test_match_album_exact_match_is_available():
    results = [_result("Album X", "Artist A")]
    m = match_album("Artist A", "Album X", results)
    assert m.status == "available"
    assert m.url == "https://music.apple.com/gb/album/x/1"
    assert m.name == "Album X"
    assert m.artist == "Artist A"


def test_match_album_deluxe_edition_still_matches():
    results = [_result("Album X (Deluxe Edition)", "Artist A")]
    assert match_album("Artist A", "Album X", results).status == "available"


def test_match_album_wrong_artist_is_unavailable():
    results = [_result("Album X", "Some Other Band")]
    m = match_album("Artist A", "Album X", results)
    assert m.status == "unavailable"
    assert m.url is None


def test_match_album_no_results_is_unavailable():
    assert match_album("Artist A", "Album X", []).status == "unavailable"


def test_match_album_compilation_matches_on_title_alone():
    results = [_result("Big Compilation", "Various Artists 2024 Reissue")]
    m = match_album("Various Artists", "Big Compilation", results)
    assert m.status == "available"


def test_match_album_picks_best_of_several():
    results = [
        _result("Album X (Live)", "Artist A", "https://music.apple.com/gb/album/live/2"),
        _result("Album X", "Artist A", "https://music.apple.com/gb/album/x/1"),
    ]
    assert match_album("Artist A", "Album X", results).url == "https://music.apple.com/gb/album/x/1"


class FakeResp:
    def __init__(self, status, json_data=None):
        self.status_code = status
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.last_params = None

    def get(self, url, **kwargs):
        self.last_params = kwargs.get("params")
        return self._responses.pop(0)


def _itunes_payload():
    return {"resultCount": 1, "results": [
        {"collectionName": "Album X", "artistName": "Artist A",
         "collectionViewUrl": "https://music.apple.com/gb/album/x/1"}
    ]}


def test_search_album_returns_results_and_sends_params():
    sess = FakeSession([FakeResp(200, _itunes_payload())])
    client = AppleMusicClient(session=sess)
    results = client.search_album("Artist A", "Album X", "gb")
    assert results[0]["collectionName"] == "Album X"
    assert sess.last_params["entity"] == "album"
    assert sess.last_params["country"] == "gb"
    assert sess.last_params["term"] == "Artist A Album X"


def test_search_album_empty_when_no_results():
    sess = FakeSession([FakeResp(200, {"resultCount": 0, "results": []})])
    client = AppleMusicClient(session=sess)
    assert client.search_album("a", "b", "gb") == []


def test_search_album_raises_on_403_rate_limit():
    sess = FakeSession([FakeResp(403)])
    client = AppleMusicClient(session=sess)
    with pytest.raises(AppleRateLimited):
        client.search_album("a", "b", "gb")


def test_search_album_raises_on_429_rate_limit():
    sess = FakeSession([FakeResp(429)])
    client = AppleMusicClient(session=sess)
    with pytest.raises(AppleRateLimited):
        client.search_album("a", "b", "gb")


def test_search_album_raises_search_error_on_persistent_5xx():
    sess = FakeSession([FakeResp(500), FakeResp(500), FakeResp(500)])
    client = AppleMusicClient(session=sess, max_retries=2)
    with pytest.raises(AppleSearchError):
        client.search_album("a", "b", "gb")


from bandcamp_reco.apple_music import lookup_pool, AppleMatch


class StubCache:
    def __init__(self):
        self.store = {}

    def get(self, ns, key):
        return self.store.get((ns, key))

    def set(self, ns, key, value):
        self.store[(ns, key)] = value


class FakeClient:
    def __init__(self, mapping, errors=(), rate_limit_on=None):
        self.mapping = mapping            # title -> iTunes results list
        self.errors = set(errors)         # titles that raise a generic error
        self.rate_limit_on = rate_limit_on  # title that raises AppleRateLimited
        self.calls = []

    def search_album(self, artist, title, country):
        self.calls.append(title)
        if title == self.rate_limit_on:
            raise AppleRateLimited()
        if title in self.errors:
            raise RuntimeError("boom")
        return self.mapping.get(title, [])


def _item(url, title, artist="Artist A"):
    return {"url": url, "title": title, "artist": artist}


def _itunes_result(name, artist, url):
    return {"collectionName": name, "artistName": artist, "collectionViewUrl": url}


def test_lookup_pool_matches_and_caches():
    pool = [_item("https://x.bandcamp.com/album/y", "Album X")]
    client = FakeClient({"Album X": [
        _itunes_result("Album X", "Artist A", "https://music.apple.com/gb/album/x/1")]})
    cache = StubCache()
    results = lookup_pool(pool, client, cache, "gb")
    key = "https://x.bandcamp.com/album/y"
    assert results[key].status == "available"
    assert results[key].url == "https://music.apple.com/gb/album/x/1"
    assert cache.store[("apple_music", key)]["status"] == "available"


def test_lookup_pool_skips_cached_albums():
    pool = [_item("https://x.bandcamp.com/album/y", "Album X")]
    cache = StubCache()
    cache.set("apple_music", "https://x.bandcamp.com/album/y",
              {"status": "unavailable", "url": None, "name": None, "artist": None})
    client = FakeClient({})
    results = lookup_pool(pool, client, cache, "gb")
    assert results["https://x.bandcamp.com/album/y"].status == "unavailable"
    assert client.calls == []  # cached -> no API call


def test_lookup_pool_error_is_unknown_and_not_cached():
    pool = [_item("https://x.bandcamp.com/album/y", "Boom")]
    client = FakeClient({}, errors={"Boom"})
    cache = StubCache()
    results = lookup_pool(pool, client, cache, "gb")
    assert "https://x.bandcamp.com/album/y" not in results  # unknown
    assert ("apple_music", "https://x.bandcamp.com/album/y") not in cache.store


def test_lookup_pool_stops_on_rate_limit_and_leaves_rest_unknown():
    pool = [
        _item("https://x.bandcamp.com/album/a", "First"),
        _item("https://x.bandcamp.com/album/b", "Limited"),
        _item("https://x.bandcamp.com/album/c", "Third"),
    ]
    client = FakeClient(
        {"First": [_itunes_result("First", "Artist A", "https://music.apple.com/gb/album/a/1")]},
        rate_limit_on="Limited",
    )
    cache = StubCache()
    results = lookup_pool(pool, client, cache, "gb")
    assert results["https://x.bandcamp.com/album/a"].status == "available"  # done before limit
    assert "https://x.bandcamp.com/album/b" not in results                  # the limited one
    assert "https://x.bandcamp.com/album/c" not in results                  # never reached
    assert client.calls == ["First", "Limited"]                            # stopped, did not call Third
