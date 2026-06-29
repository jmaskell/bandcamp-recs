import contextlib

import bandcamp_reco.fans as fans
from bandcamp_reco.models import Album
from bandcamp_reco.fetch import CircuitBreakerTripped
from bandcamp_reco.progress import Reporter


def _album(url):
    return Album(item_id=url, album_id=None, title=url, artist="A", url=url, art_url=None)


def test_get_fan_collections_dedupes_and_caps_fans(monkeypatch):
    seen = []

    def fake_get_collection(username, fetcher, cache, max_items=None):
        seen.append(username)
        return [_album(f"https://x/{username}")]

    monkeypatch.setattr(fans, "get_collection", fake_get_collection)
    result = fans.get_fan_collections(
        ["a", "a", "b", "c"], fetcher=None, cache=None,
        max_fans=2, max_albums_per_fan=100,
    )
    assert set(result.keys()) == {"a", "b"}
    assert seen == ["a", "b"]


def test_get_fan_collections_skips_erroring_fan(monkeypatch):
    def fake_get_collection(username, fetcher, cache, max_items=None):
        if username == "bad":
            raise ValueError("boom")
        return [_album(f"https://x/{username}")]

    monkeypatch.setattr(fans, "get_collection", fake_get_collection)
    result = fans.get_fan_collections(
        ["bad", "good"], fetcher=None, cache=None,
        max_fans=10, max_albums_per_fan=100,
    )
    assert set(result.keys()) == {"good"}


def test_get_fan_collections_stops_on_circuit_breaker(monkeypatch):
    def fake_get_collection(username, fetcher, cache, max_items=None):
        if username == "b":
            raise CircuitBreakerTripped("stop")
        return [_album(f"https://x/{username}")]

    monkeypatch.setattr(fans, "get_collection", fake_get_collection)
    result = fans.get_fan_collections(
        ["a", "b", "c"], fetcher=None, cache=None,
        max_fans=10, max_albums_per_fan=100,
    )
    assert set(result.keys()) == {"a"}


def test_get_fan_collections_accepts_reporter(monkeypatch):
    def fake_get_collection(username, fetcher, cache, max_items=None):
        return [_album(f"https://x/{username}")]

    monkeypatch.setattr(fans, "get_collection", fake_get_collection)
    result = fans.get_fan_collections(
        ["a", "b"], fetcher=None, cache=None,
        max_fans=10, max_albums_per_fan=100, reporter=Reporter(enabled=True),
    )
    assert set(result.keys()) == {"a", "b"}


def test_fan_bar_advances_once_per_fan_actually_fetched(monkeypatch):
    """Bar update count equals fans recorded, strictly fewer than usernames considered."""

    class _SpyReporter:
        def __init__(self):
            self.updates = 0

        def phase(self, label):
            pass

        @contextlib.contextmanager
        def bar(self, total, label):
            outer = self

            class _H:
                def update(self, n=1):
                    outer.updates += n

            yield _H()

    def fake_get_collection(username, fetcher, cache, max_items=None):
        if username == "bad":
            raise ValueError("fetch error")
        return [_album(f"https://x/{username}")]

    monkeypatch.setattr(fans, "get_collection", fake_get_collection)
    spy = _SpyReporter()
    # usernames: "a" duplicated, "bad" raises, "c" fetched → 2 fans recorded ("a", "c")
    result = fans.get_fan_collections(
        ["a", "a", "bad", "c"], fetcher=None, cache=None,
        max_fans=10, max_albums_per_fan=100, reporter=spy,
    )
    assert set(result.keys()) == {"a", "c"}
    assert spy.updates == 2  # once per fan actually fetched, not per username considered
