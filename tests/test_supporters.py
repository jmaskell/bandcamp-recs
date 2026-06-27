from bandcamp_reco.models import Album
from bandcamp_reco.supporters import parse_album_page, get_supporters, AlbumPageInfo


ALBUM_HTML = (
    '<html><body>'
    '<div id="pagedata" data-blob="'
    '{&quot;tralbum_id&quot;:&quot;101&quot;,'
    '&quot;supporters&quot;:[{&quot;username&quot;:&quot;fanA&quot;},'
    '{&quot;username&quot;:&quot;fanB&quot;}]}'
    '"></div>'
    '<div class="tralbum-tags">'
    '<a class="tag" href="/tag/ambient">ambient</a>'
    '<a class="tag" href="/tag/drone">drone</a>'
    '</div>'
    '</body></html>'
)


def test_parse_album_page_extracts_tags_and_supporters():
    info = parse_album_page(ALBUM_HTML)
    assert isinstance(info, AlbumPageInfo)
    assert info.tralbum_id == "101"
    assert info.tags == ("ambient", "drone")
    assert info.supporter_usernames == ["fanA", "fanB"]


class StubCache:
    def __init__(self):
        self.store = {}

    def get(self, ns, key):
        return self.store.get((ns, key))

    def set(self, ns, key, value):
        self.store[(ns, key)] = value


class StubFetcher:
    def __init__(self, html):
        self._html = html

    def get(self, url, **kw):
        html = self._html

        class R:
            text = html
        return R()


def _album():
    return Album(item_id="1", album_id="101", title="X", artist="A",
                 url="https://a.bandcamp.com/album/x", art_url=None)


def test_get_supporters_respects_limit():
    fetcher = StubFetcher(ALBUM_HTML)
    cache = StubCache()
    assert get_supporters(_album(), fetcher, cache, limit=1) == ["fanA"]
