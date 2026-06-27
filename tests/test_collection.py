from bandcamp_reco.collection import parse_pagedata_blob, raw_to_album, get_collection


PROFILE_HTML = (
    '<html><body>'
    '<div id="pagedata" data-blob="'
    '{&quot;fan_data&quot;:{&quot;fan_id&quot;:42},'
    '&quot;collection_data&quot;:{&quot;item_count&quot;:2,&quot;last_token&quot;:&quot;tok1&quot;,'
    '&quot;sequence&quot;:[&quot;a1&quot;]},'
    '&quot;item_cache&quot;:{&quot;collection&quot;:{'
    '&quot;a1&quot;:{&quot;item_type&quot;:&quot;album&quot;,&quot;item_id&quot;:&quot;a1&quot;,'
    '&quot;album_id&quot;:&quot;101&quot;,&quot;item_title&quot;:&quot;First&quot;,'
    '&quot;band_name&quot;:&quot;Band One&quot;,'
    '&quot;item_url&quot;:&quot;https://one.bandcamp.com/album/first&quot;,'
    '&quot;item_art_id&quot;:&quot;555&quot;}}}}'
    '"></div></body></html>'
)


def test_parse_pagedata_blob_reads_fan_id():
    blob = parse_pagedata_blob(PROFILE_HTML)
    assert blob["fan_data"]["fan_id"] == 42
    assert blob["collection_data"]["last_token"] == "tok1"


def test_raw_to_album_normalizes_fields():
    raw = {
        "item_type": "album", "item_id": "a1", "album_id": "101",
        "item_title": "First", "band_name": "Band One",
        "item_url": "https://one.bandcamp.com/album/first", "item_art_id": "555",
    }
    album = raw_to_album(raw)
    assert album.title == "First"
    assert album.artist == "Band One"
    assert album.url == "https://one.bandcamp.com/album/first"
    assert album.art_url == "https://f4.bcbits.com/img/a555_16.jpg"


def test_raw_to_album_skips_tracks():
    assert raw_to_album({"item_type": "track", "item_id": "t1"}) is None


class StubFetcher:
    def __init__(self, html, api_pages):
        self._html = html
        self._api_pages = list(api_pages)
        self.post_json_call_count = 0

    def get(self, url, **kw):
        class R:
            text = self._html
        return R()

    def post_json(self, url, json_body):
        self.post_json_call_count += 1
        return self._api_pages.pop(0)


class StubCache:
    def __init__(self):
        self.store = {}

    def get(self, ns, key):
        return self.store.get((ns, key))

    def set(self, ns, key, value):
        self.store[(ns, key)] = value


def test_get_collection_combines_cache_items_and_api_page():
    api_page = {
        "items": [{
            "item_type": "album", "item_id": "a2", "album_id": "102",
            "item_title": "Second", "band_name": "Band Two",
            "item_url": "https://two.bandcamp.com/album/second", "item_art_id": "666",
        }],
        "more_available": False,
        "last_token": "tok2",
    }
    fetcher = StubFetcher(PROFILE_HTML, [api_page])
    cache = StubCache()
    albums = get_collection("jmaskell", fetcher, cache)
    titles = sorted(a.title for a in albums)
    assert titles == ["First", "Second"]


def test_get_collection_dedups_by_album_key():
    api_page = {
        "items": [
            {
                "item_type": "album", "item_id": "a1", "album_id": "101",
                "item_title": "First", "band_name": "Band One",
                "item_url": "https://one.bandcamp.com/album/first", "item_art_id": "555",
            },
            {
                "item_type": "album", "item_id": "a2", "album_id": "102",
                "item_title": "Second", "band_name": "Band Two",
                "item_url": "https://two.bandcamp.com/album/second", "item_art_id": "666",
            },
        ],
        "more_available": False,
        "last_token": "tok2",
    }
    fetcher = StubFetcher(PROFILE_HTML, [api_page])
    cache = StubCache()
    albums = get_collection("jmaskell", fetcher, cache)
    titles = sorted(a.title for a in albums)
    assert titles == ["First", "Second"]


def test_get_collection_terminates_on_empty_page():
    api_page = {
        "items": [],
        "more_available": True,
        "last_token": "tok2",
    }
    fetcher = StubFetcher(PROFILE_HTML, [api_page])
    cache = StubCache()
    albums = get_collection("jmaskell", fetcher, cache)
    titles = sorted(a.title for a in albums)
    assert titles == ["First"]


def test_raw_to_album_honors_tralbum_type():
    album = raw_to_album(
        {"tralbum_type": "a", "item_id": "x", "item_url": "https://a/b"}
    )
    assert album is not None
    assert album.url == "https://a/b"
    assert raw_to_album({"tralbum_type": "t", "item_id": "y"}) is None


def test_get_collection_respects_max_items():
    api_page = {
        "items": [{
            "item_type": "album", "item_id": "a2", "album_id": "102",
            "item_title": "Second", "band_name": "Band Two",
            "item_url": "https://two.bandcamp.com/album/second", "item_art_id": "666",
        }],
        "more_available": False,
        "last_token": "tok2",
    }
    fetcher = StubFetcher(PROFILE_HTML, [api_page])
    cache = StubCache()
    albums = get_collection("jmaskell", fetcher, cache, max_items=1)
    assert len(albums) == 1


def test_get_collection_caches_api_pages():
    """A second get_collection call for the same user must not re-POST paged data."""
    api_page = {
        "items": [{
            "item_type": "album", "item_id": "a2", "album_id": "102",
            "item_title": "Second", "band_name": "Band Two",
            "item_url": "https://two.bandcamp.com/album/second", "item_art_id": "666",
        }],
        "more_available": False,
        "last_token": "tok2",
    }
    # First call: profile is fetched via GET, one additional page via POST.
    fetcher = StubFetcher(PROFILE_HTML, [api_page])
    cache = StubCache()
    get_collection("jmaskell", fetcher, cache)
    first_call_count = fetcher.post_json_call_count  # should be 1

    # Second call: profile already cached; paged data must also come from cache.
    fetcher2 = StubFetcher(PROFILE_HTML, [])  # empty api_pages — would raise on pop
    fetcher2.post_json_call_count = 0
    get_collection("jmaskell", fetcher2, cache)
    assert fetcher2.post_json_call_count == 0, (
        "second get_collection call should serve paged data from cache, "
        "not re-POST to the API"
    )
    assert first_call_count == 1
