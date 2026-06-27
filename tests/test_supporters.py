from bandcamp_reco.models import Album
from bandcamp_reco.supporters import parse_album_page, get_supporters, AlbumPageInfo


# Fixture updated to match live Bandcamp page structure:
#   - 'album_id' (integer) replaces 'tralbum_id' at the top level of data-blob
#   - 'supporters' key is absent (live site no longer embeds the supporter list
#     in the page; they are fetched via the tralbumcollectors thumbs API instead)
ALBUM_HTML = (
    '<html><body>'
    '<div id="pagedata" data-blob="'
    '{&quot;album_id&quot;:101}'
    '"></div>'
    '<div class="tralbum-tags">'
    '<a class="tag" href="/tag/ambient">ambient</a>'
    '<a class="tag" href="/tag/drone">drone</a>'
    '</div>'
    '</body></html>'
)


def test_parse_album_page_extracts_tags_and_tralbum_id():
    info = parse_album_page(ALBUM_HTML)
    assert isinstance(info, AlbumPageInfo)
    assert info.tralbum_id == "101"
    assert info.tags == ("ambient", "drone")
    # Supporters are not in the page data-blob on the live site
    assert info.supporter_usernames == []


class StubCache:
    def __init__(self):
        self.store = {}

    def get(self, ns, key):
        return self.store.get((ns, key))

    def set(self, ns, key, value):
        self.store[(ns, key)] = value


class StubFetcher:
    def __init__(self, html, api_resp=None):
        self._html = html
        self._api_resp = api_resp if api_resp is not None else {
            "results": [], "more_available": False
        }

    def get(self, url, **kw):
        html = self._html

        class R:
            text = html
        return R()

    def post_json(self, url, json_body):
        return self._api_resp


def _album():
    return Album(item_id="1", album_id="101", title="X", artist="A",
                 url="https://a.bandcamp.com/album/x", art_url=None)


def test_get_supporters_uses_thumbs_api():
    api_resp = {
        "results": [
            {"username": "fanA", "name": "Fan A"},
            {"username": "fanB", "name": "Fan B"},
        ],
        "more_available": False,
    }
    fetcher = StubFetcher(ALBUM_HTML, api_resp)
    cache = StubCache()
    supporters = get_supporters(_album(), fetcher, cache, limit=10)
    assert supporters == ["fanA", "fanB"]


def test_get_supporters_respects_limit():
    api_resp = {
        "results": [
            {"username": "fanA", "name": "Fan A"},
            {"username": "fanB", "name": "Fan B"},
        ],
        "more_available": False,
    }
    fetcher = StubFetcher(ALBUM_HTML, api_resp)
    cache = StubCache()
    assert get_supporters(_album(), fetcher, cache, limit=1) == ["fanA"]


class CountingStubFetcher:
    """StubFetcher that counts post_json calls and returns a fixed response."""
    def __init__(self, html, api_resp):
        self._html = html
        self._api_resp = api_resp
        self.post_json_call_count = 0

    def get(self, url, **kw):
        html = self._html

        class R:
            text = html
        return R()

    def post_json(self, url, json_body):
        self.post_json_call_count += 1
        return self._api_resp


def test_get_supporters_different_limits_use_different_cache_keys():
    """limit=1 cached result must NOT be returned for a later limit=10 call."""
    api_resp = {
        "results": [
            {"username": "fanA", "name": "Fan A"},
            {"username": "fanB", "name": "Fan B"},
        ],
        "more_available": False,
    }
    fetcher = CountingStubFetcher(ALBUM_HTML, api_resp)
    cache = StubCache()

    # First call at limit=1 — fetches from API, caches under url#1 key.
    result1 = get_supporters(_album(), fetcher, cache, limit=1)
    assert result1 == ["fanA"]
    assert fetcher.post_json_call_count == 1

    # Second call at limit=10 — different key, must re-fetch (not reuse cached list).
    result2 = get_supporters(_album(), fetcher, cache, limit=10)
    assert fetcher.post_json_call_count == 2, (
        "a larger limit should fetch from the API again (different cache key), "
        "not silently return the truncated list from the previous call"
    )
    assert result2 == ["fanA", "fanB"]
