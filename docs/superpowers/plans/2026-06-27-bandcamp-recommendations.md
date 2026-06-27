# Bandcamp Collaborative Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that reads the public Bandcamp collection at `bandcamp.com/jmaskell`, runs "fans-also-bought" collaborative filtering over Bandcamp's fan graph, and renders a ranked HTML page of buyable recommendations.

**Architecture:** A linear pipeline of small, single-responsibility modules (`collection → supporters → fans → score → render`) sitting on two shared services: a polite single-threaded HTTP layer (`fetch.py`) and a SQLite cache (`cache.py`). Every network read goes through fetch+cache, so re-runs are fast, incremental, and resumable. Scoring weights each candidate album by how much taste its owners share with you, with a popularity dampener.

**Tech Stack:** Python 3.11+, `requests` (HTTP), `beautifulsoup4` (HTML parsing), `sqlite3` + `tomllib` (stdlib), `pytest` (dev).

## Global Constraints

- **Python 3.11+** required (uses stdlib `tomllib`).
- **Runtime dependencies:** `requests`, `beautifulsoup4` only. **Dev:** `pytest`. No other deps without cause (YAGNI).
- **Read-only, no login.** Only fetch public pages. Never authenticate, never POST anything that mutates, never touch private data.
- **Single-threaded fetching.** One request at a time, base delay `0.7s` + randomized jitter, exponential backoff (ceilinged) on 429/5xx, circuit breaker that halts the run after `2` consecutive 429s.
- **Everything cached.** Every profile page, album page, and collection-API response is read-through a SQLite cache keyed by `(namespace, key)`.
- **Default config:** `username="jmaskell"`, `supporters_per_album=30`, `max_fans=500`, `max_albums_per_fan=200`, `top_n=50`, `request_delay=0.7`, `cache_path="cache.db"`, `output_path="recommendations.html"`.
- **Album identity** is the normalized album URL (`album_key`), used consistently as the dictionary/set key across every stage.
- **Scoring:** `score(c) = Σ affinity(f)` over fans `f` owning candidate `c`, where `affinity(f) = |f.collection ∩ your.collection|`; then `final(c) = score(c) / sqrt(global_count(c))`.
- **TDD, DRY, frequent commits.** Write the failing test first; commit after each green task.
- **Unofficial endpoints:** Bandcamp's JSON shapes are undocumented. Parsers must read defensively (`.get()` with fallbacks). Tests run against representative fixtures (no network); Task 11 validates against the live site and adjusts keys if needed.

---

## File Structure

```
bandcamp/
  recommend.py                 # Task 10 — thin CLI entry point
  config.toml                  # Task 2 — user config
  requirements.txt             # Task 1
  README.md                    # Task 11
  bandcamp_reco/
    __init__.py                # Task 1
    models.py                  # Task 1 — Album dataclass, album_key, art_url_from_id
    config.py                  # Task 2 — Config dataclass, load_config
    cache.py                   # Task 3 — SQLite read-through cache
    fetch.py                   # Task 4 — polite HTTP layer + circuit breaker
    collection.py              # Task 5 — parse profile blob + collection items
    supporters.py              # Task 6 — parse album page (supporters + tags)
    fans.py                    # Task 7 — fetch sampled fans' collections
    score.py                   # Task 8 — rank candidates
    render.py                  # Task 9 — HTML output
    main.py                    # Task 10 — orchestration
  tests/
    __init__.py
    fixtures/                  # saved HTML/JSON samples
    test_models.py             # Task 1
    test_config.py             # Task 2
    test_cache.py              # Task 3
    test_fetch.py              # Task 4
    test_collection.py         # Task 5
    test_supporters.py         # Task 6
    test_fans.py               # Task 7
    test_score.py              # Task 8
    test_render.py             # Task 9
    test_main.py               # Task 10
```

---

### Task 1: Models & scaffolding

**Files:**
- Create: `bandcamp_reco/__init__.py` (empty), `tests/__init__.py` (empty), `tests/fixtures/.gitkeep` (empty)
- Create: `requirements.txt`
- Create: `bandcamp_reco/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) class Album` with fields `item_id: str`, `album_id: str | None`, `title: str`, `artist: str`, `url: str`, `art_url: str | None`, `tags: tuple[str, ...] = ()`.
  - `album_key(album: Album) -> str` — normalized URL (strip query + trailing slash), the canonical identity used everywhere.
  - `art_url_from_id(art_id: str | int | None) -> str | None` — builds a bcbits art URL, or `None`.

- [ ] **Step 1: Create scaffolding files**

Create empty `bandcamp_reco/__init__.py`, `tests/__init__.py`, `tests/fixtures/.gitkeep`.

Create `requirements.txt`:
```
requests>=2.31
beautifulsoup4>=4.12
pytest>=8.0
```

- [ ] **Step 2: Write the failing test**

`tests/test_models.py`:
```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.models'`

- [ ] **Step 4: Write minimal implementation**

`bandcamp_reco/models.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Album:
    item_id: str
    album_id: str | None
    title: str
    artist: str
    url: str
    art_url: str | None
    tags: tuple[str, ...] = ()


def album_key(album: "Album") -> str:
    return album.url.split("?")[0].rstrip("/")


def art_url_from_id(art_id) -> str | None:
    if not art_id:
        return None
    return f"https://f4.bcbits.com/img/a{art_id}_16.jpg"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/ tests/ requirements.txt
git commit -m "feat: add Album model, album_key, art_url helper"
```

---

### Task 2: Config

**Files:**
- Create: `bandcamp_reco/config.py`
- Create: `config.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass class Config` with fields `username: str`, `supporters_per_album: int`, `max_fans: int`, `max_albums_per_fan: int`, `top_n: int`, `request_delay: float`, `cache_path: str`, `output_path: str`.
  - `DEFAULTS: dict` — the default values.
  - `load_config(path: str | None = None) -> Config` — reads a TOML file if it exists, overlaying onto `DEFAULTS`; missing file or missing keys fall back to defaults.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from bandcamp_reco.config import load_config, Config


def test_load_config_uses_defaults_when_file_missing(tmp_path):
    cfg = load_config(str(tmp_path / "nope.toml"))
    assert cfg.username == "jmaskell"
    assert cfg.top_n == 50
    assert cfg.request_delay == 0.7


def test_load_config_overlays_file_values(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('username = "someone"\ntop_n = 10\n')
    cfg = load_config(str(p))
    assert cfg.username == "someone"
    assert cfg.top_n == 10
    # untouched keys keep defaults
    assert cfg.max_fans == 500
    assert isinstance(cfg, Config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.config'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/config.py`:
```python
import os
import tomllib
from dataclasses import dataclass


@dataclass
class Config:
    username: str
    supporters_per_album: int
    max_fans: int
    max_albums_per_fan: int
    top_n: int
    request_delay: float
    cache_path: str
    output_path: str


DEFAULTS = {
    "username": "jmaskell",
    "supporters_per_album": 30,
    "max_fans": 500,
    "max_albums_per_fan": 200,
    "top_n": 50,
    "request_delay": 0.7,
    "cache_path": "cache.db",
    "output_path": "recommendations.html",
}


def load_config(path: str | None = None) -> Config:
    values = dict(DEFAULTS)
    path = path or "config.toml"
    if os.path.exists(path):
        with open(path, "rb") as f:
            values.update(tomllib.load(f))
    return Config(**{k: values[k] for k in DEFAULTS})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Create the default config file**

`config.toml`:
```toml
# Bandcamp recommendations config
username = "jmaskell"

# How many supporters (fans) to sample per owned album
supporters_per_album = 30
# Overall cap on distinct fans whose collections we fetch
max_fans = 500
# Per-fan cap on albums read from their collection
max_albums_per_fan = 200
# How many recommendations to render
top_n = 50

# Base seconds between requests (jitter is added on top)
request_delay = 0.7

cache_path = "cache.db"
output_path = "recommendations.html"
```

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/config.py config.toml tests/test_config.py
git commit -m "feat: add config loader with TOML overlay over defaults"
```

---

### Task 3: SQLite read-through cache

**Files:**
- Create: `bandcamp_reco/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Cache`:
    - `__init__(self, path: str)` — opens/creates the SQLite db and the `kv` table.
    - `get(self, namespace: str, key: str) -> dict | list | None` — returns the stored JSON value or `None` if absent.
    - `set(self, namespace: str, key: str, value) -> None` — JSON-serializes and upserts.
    - `close(self) -> None`.

- [ ] **Step 1: Write the failing test**

`tests/test_cache.py`:
```python
from bandcamp_reco.cache import Cache


def test_get_missing_returns_none(tmp_path):
    c = Cache(str(tmp_path / "c.db"))
    assert c.get("profile", "jmaskell") is None
    c.close()


def test_set_then_get_roundtrips(tmp_path):
    c = Cache(str(tmp_path / "c.db"))
    c.set("profile", "jmaskell", {"fan_id": 42, "items": [1, 2, 3]})
    assert c.get("profile", "jmaskell") == {"fan_id": 42, "items": [1, 2, 3]}
    c.close()


def test_set_overwrites(tmp_path):
    c = Cache(str(tmp_path / "c.db"))
    c.set("ns", "k", {"v": 1})
    c.set("ns", "k", {"v": 2})
    assert c.get("ns", "k") == {"v": 2}
    c.close()


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "c.db")
    c1 = Cache(path)
    c1.set("ns", "k", {"v": 1})
    c1.close()
    c2 = Cache(path)
    assert c2.get("ns", "k") == {"v": 1}
    c2.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.cache'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/cache.py`:
```python
import json
import sqlite3


class Cache:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv ("
            "  namespace TEXT NOT NULL,"
            "  key TEXT NOT NULL,"
            "  value TEXT NOT NULL,"
            "  PRIMARY KEY (namespace, key)"
            ")"
        )
        self._conn.commit()

    def get(self, namespace: str, key: str):
        row = self._conn.execute(
            "SELECT value FROM kv WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, namespace: str, key: str, value) -> None:
        self._conn.execute(
            "INSERT INTO kv (namespace, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(namespace, key) DO UPDATE SET value = excluded.value",
            (namespace, key, json.dumps(value)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cache.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/cache.py tests/test_cache.py
git commit -m "feat: add SQLite read-through cache"
```

---

### Task 4: Polite HTTP layer + circuit breaker

**Files:**
- Create: `bandcamp_reco/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class CircuitBreakerTripped(Exception)`.
  - `class FetchError(Exception)`.
  - `class Fetcher`:
    - `__init__(self, delay=0.7, jitter=0.3, max_retries=4, breaker_threshold=2, backoff_ceiling=30.0, session=None)`.
    - `get(self, url: str, **kwargs) -> requests.Response`.
    - `post_json(self, url: str, json_body: dict) -> dict` — POSTs JSON, returns parsed response JSON.
  - Behavior: throttle (delay + random jitter) before every request; on 429/5xx retry with exponential backoff capped at `backoff_ceiling`; after `breaker_threshold` consecutive 429s raise `CircuitBreakerTripped`; reset the consecutive-429 counter on any non-429 response.

- [ ] **Step 1: Write the failing test**

`tests/test_fetch.py`:
```python
import pytest
from bandcamp_reco.fetch import Fetcher, CircuitBreakerTripped


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self._responses.pop(0)

    def post(self, url, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("bandcamp_reco.fetch.time.sleep", lambda *_: None)
    monkeypatch.setattr("bandcamp_reco.fetch.random.uniform", lambda *_: 0.0)


def test_get_returns_response_on_200():
    session = FakeSession([FakeResponse(200, text="ok")])
    f = Fetcher(session=session)
    resp = f.get("http://x")
    assert resp.text == "ok"
    assert session.calls == 1


def test_retries_on_500_then_succeeds():
    session = FakeSession([FakeResponse(500), FakeResponse(200, text="ok")])
    f = Fetcher(session=session)
    assert f.get("http://x").text == "ok"
    assert session.calls == 2


def test_circuit_breaker_trips_after_two_consecutive_429():
    session = FakeSession([FakeResponse(429), FakeResponse(429)])
    f = Fetcher(session=session, breaker_threshold=2)
    with pytest.raises(CircuitBreakerTripped):
        f.get("http://x")


def test_429_counter_resets_on_success():
    session = FakeSession([FakeResponse(429), FakeResponse(200, text="ok"),
                           FakeResponse(429), FakeResponse(200, text="ok2")])
    f = Fetcher(session=session, breaker_threshold=2)
    assert f.get("http://x").text == "ok"
    assert f.get("http://y").text == "ok2"


def test_post_json_returns_parsed_body():
    session = FakeSession([FakeResponse(200, json_data={"items": []})])
    f = Fetcher(session=session)
    assert f.post_json("http://x", {"q": 1}) == {"items": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.fetch'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/fetch.py`:
```python
import random
import time

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


class CircuitBreakerTripped(Exception):
    pass


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, delay=0.7, jitter=0.3, max_retries=4,
                 breaker_threshold=2, backoff_ceiling=30.0, session=None):
        self.delay = delay
        self.jitter = jitter
        self.max_retries = max_retries
        self.breaker_threshold = breaker_threshold
        self.backoff_ceiling = backoff_ceiling
        self._session = session or requests.Session()
        self._consecutive_429 = 0

    def get(self, url: str, **kwargs):
        return self._request("get", url, **kwargs)

    def post_json(self, url: str, json_body: dict) -> dict:
        resp = self._request("post", url, json=json_body)
        return resp.json()

    def _throttle(self):
        time.sleep(self.delay + random.uniform(0.0, self.jitter))

    def _backoff(self, attempt):
        time.sleep(min(self.delay * (2 ** attempt), self.backoff_ceiling))

    def _request(self, method_name, url, **kwargs):
        method = getattr(self._session, method_name)
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        for attempt in range(self.max_retries + 1):
            self._throttle()
            resp = method(url, headers=headers, **kwargs)
            if resp.status_code == 429:
                self._consecutive_429 += 1
                if self._consecutive_429 >= self.breaker_threshold:
                    raise CircuitBreakerTripped(
                        f"{self._consecutive_429} consecutive 429s; stopping"
                    )
                self._backoff(attempt)
                continue
            if 500 <= resp.status_code < 600:
                self._backoff(attempt)
                continue
            self._consecutive_429 = 0
            resp.raise_for_status()
            return resp
        raise FetchError(f"exhausted retries for {url}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/fetch.py tests/test_fetch.py
git commit -m "feat: add polite HTTP fetcher with backoff and circuit breaker"
```

---

### Task 5: Collection — parse profile blob + page collection items

**Files:**
- Create: `bandcamp_reco/collection.py`
- Test: `tests/test_collection.py`

**Interfaces:**
- Consumes: `Fetcher` (`get`, `post_json`), `Cache` (`get`, `set`), `Album`, `album_key`, `art_url_from_id`.
- Produces:
  - `parse_pagedata_blob(html: str) -> dict` — extracts and JSON-parses the `#pagedata` `data-blob`.
  - `raw_to_album(raw: dict) -> Album | None` — normalizes one raw collection item to an `Album` (returns `None` for non-album items).
  - `get_collection(username: str, fetcher, cache, max_items: int | None = None) -> list[Album]` — the user's (or any fan's) owned albums, read-through cache under namespace `"collection"`.

- [ ] **Step 1: Write the failing test**

`tests/test_collection.py`:
```python
import json
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

    def get(self, url, **kw):
        class R:
            text = self._html
        R.text = self._html
        return R()

    def post_json(self, url, json_body):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.collection'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/collection.py`:
```python
import json

from bs4 import BeautifulSoup

from .models import Album, art_url_from_id

COLLECTION_API = "https://bandcamp.com/api/fancollection/1/collection_items"
PROFILE_URL = "https://bandcamp.com/{username}"


def parse_pagedata_blob(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(id="pagedata")
    if node is None or not node.get("data-blob"):
        return {}
    return json.loads(node["data-blob"])


def _is_album(raw: dict) -> bool:
    return (raw.get("item_type") or raw.get("tralbum_type")) in ("album", "a")


def raw_to_album(raw: dict) -> Album | None:
    if not _is_album(raw):
        return None
    art = raw.get("item_art_id") or raw.get("art_id")
    return Album(
        item_id=str(raw.get("item_id") or raw.get("tralbum_id") or raw.get("id") or ""),
        album_id=str(raw["album_id"]) if raw.get("album_id") else None,
        title=raw.get("item_title") or raw.get("title") or "",
        artist=raw.get("band_name") or "",
        url=raw.get("item_url") or raw.get("url") or "",
        art_url=art_url_from_id(art),
    )


def _albums_from_item_cache(blob: dict) -> list[Album]:
    cache = (blob.get("item_cache") or {}).get("collection") or {}
    out = []
    for raw in cache.values():
        album = raw_to_album(raw)
        if album:
            out.append(album)
    return out


def get_collection(username, fetcher, cache, max_items=None) -> list[Album]:
    cached = cache.get("collection", username)
    if cached is not None:
        albums = [Album(**a) | None for a in cached]  # placeholder; replaced below
    blob = _load_profile_blob(username, fetcher, cache)
    if not blob:
        return []
    fan_id = (blob.get("fan_data") or {}).get("fan_id")
    albums = _albums_from_item_cache(blob)
    cdata = blob.get("collection_data") or {}
    token = cdata.get("last_token")
    item_count = cdata.get("item_count", len(albums))
    while (token and fan_id and len(albums) < item_count
           and (max_items is None or len(albums) < max_items)):
        page = fetcher.post_json(
            COLLECTION_API,
            {"fan_id": fan_id, "older_than_token": token, "count": 50},
        )
        new = [raw_to_album(r) for r in page.get("items", [])]
        albums.extend(a for a in new if a)
        token = page.get("last_token")
        if not page.get("more_available"):
            break
    if max_items is not None:
        albums = albums[:max_items]
    return albums


def _load_profile_blob(username, fetcher, cache) -> dict:
    cached = cache.get("profile_blob", username)
    if cached is not None:
        return cached
    html = fetcher.get(PROFILE_URL.format(username=username)).text
    blob = parse_pagedata_blob(html)
    cache.set("profile_blob", username, blob)
    return blob
```

> NOTE: delete the dead `cached`/placeholder lines at the top of `get_collection` — they were a stray. The real cache used here is `profile_blob` via `_load_profile_blob`. The function should begin directly with `blob = _load_profile_blob(...)`. (Caching of the *page* is what saves requests; the assembled `Album` list is cheap to rebuild.)

- [ ] **Step 4: Clean up the stray lines**

Edit `get_collection` so its body starts at `blob = _load_profile_blob(username, fetcher, cache)` — remove the three placeholder lines referencing `cache.get("collection", ...)` and `Album(**a) | None`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_collection.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/collection.py tests/test_collection.py
git commit -m "feat: add collection fetching (profile blob + collection items)"
```

---

### Task 6: Supporters — parse album page (supporters + tags)

**Files:**
- Create: `bandcamp_reco/supporters.py`
- Test: `tests/test_supporters.py`

**Interfaces:**
- Consumes: `Fetcher`, `Cache`, `Album`, `parse_pagedata_blob` (from `collection.py`).
- Produces:
  - `@dataclass class AlbumPageInfo` with `tralbum_id: str | None`, `tags: tuple[str, ...]`, `supporter_usernames: list[str]`.
  - `parse_album_page(html: str) -> AlbumPageInfo` — pure parse of an album page.
  - `get_album_page(album: Album, fetcher, cache) -> AlbumPageInfo` — read-through cache (namespace `"album_page"`, key = `album.url`).
  - `get_supporters(album: Album, fetcher, cache, limit: int) -> list[str]` — up to `limit` supporter usernames.

- [ ] **Step 1: Write the failing test**

`tests/test_supporters.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_supporters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.supporters'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/supporters.py`:
```python
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .collection import parse_pagedata_blob
from .models import Album


@dataclass
class AlbumPageInfo:
    tralbum_id: str | None
    tags: tuple[str, ...]
    supporter_usernames: list[str]


def parse_album_page(html: str) -> AlbumPageInfo:
    blob = parse_pagedata_blob(html)
    tralbum_id = blob.get("tralbum_id") or blob.get("id")
    if tralbum_id is not None:
        tralbum_id = str(tralbum_id)

    supporters = []
    for s in blob.get("supporters") or []:
        name = s.get("username") or s.get("name")
        if name:
            supporters.append(name)

    soup = BeautifulSoup(html, "html.parser")
    tags = tuple(
        a.get_text(strip=True)
        for a in soup.select("a.tag")
        if a.get_text(strip=True)
    )
    return AlbumPageInfo(tralbum_id=tralbum_id, tags=tags,
                         supporter_usernames=supporters)


def get_album_page(album: Album, fetcher, cache) -> AlbumPageInfo:
    cached = cache.get("album_page", album.url)
    if cached is not None:
        return AlbumPageInfo(
            tralbum_id=cached["tralbum_id"],
            tags=tuple(cached["tags"]),
            supporter_usernames=list(cached["supporter_usernames"]),
        )
    html = fetcher.get(album.url).text
    info = parse_album_page(html)
    cache.set("album_page", album.url, {
        "tralbum_id": info.tralbum_id,
        "tags": list(info.tags),
        "supporter_usernames": info.supporter_usernames,
    })
    return info


def get_supporters(album: Album, fetcher, cache, limit: int) -> list[str]:
    info = get_album_page(album, fetcher, cache)
    return info.supporter_usernames[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_supporters.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/supporters.py tests/test_supporters.py
git commit -m "feat: add album-page parsing for supporters and tags"
```

---

### Task 7: Fans — fetch sampled fans' collections

**Files:**
- Create: `bandcamp_reco/fans.py`
- Test: `tests/test_fans.py`

**Interfaces:**
- Consumes: `get_collection` (from `collection.py`), `Album`, `CircuitBreakerTripped` (from `fetch.py`).
- Produces:
  - `get_fan_collections(usernames: list[str], fetcher, cache, max_fans: int, max_albums_per_fan: int) -> dict[str, list[Album]]` — maps each sampled fan username to their albums. De-dupes usernames, caps at `max_fans`, caps each fan's albums at `max_albums_per_fan`, skips fans that error, and stops cleanly (returning what it has) if the circuit breaker trips.

- [ ] **Step 1: Write the failing test**

`tests/test_fans.py`:
```python
import bandcamp_reco.fans as fans
from bandcamp_reco.models import Album
from bandcamp_reco.fetch import CircuitBreakerTripped


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fans.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.fans'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/fans.py`:
```python
from .collection import get_collection
from .fetch import CircuitBreakerTripped


def get_fan_collections(usernames, fetcher, cache, max_fans, max_albums_per_fan):
    result = {}
    seen = set()
    for username in usernames:
        if len(result) >= max_fans:
            break
        if username in seen:
            continue
        seen.add(username)
        try:
            albums = get_collection(
                username, fetcher, cache, max_items=max_albums_per_fan
            )
        except CircuitBreakerTripped:
            break
        except Exception:
            continue
        result[username] = albums
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fans.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/fans.py tests/test_fans.py
git commit -m "feat: add fan-collection sampling with caps and breaker handling"
```

---

### Task 8: Score — rank candidates

**Files:**
- Create: `bandcamp_reco/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: `Album`, `album_key` (from `models.py`).
- Produces:
  - `@dataclass class Recommendation` with `album: Album`, `score: float`, `fan_count: int`, `typical_shared: int`, `why: str`.
  - `score_candidates(owned_keys: set[str], fan_albums: dict[str, list[Album]], top_n: int) -> list[Recommendation]` — implements `final(c) = (Σ affinity over owners) / sqrt(owner_count)`, excludes owned albums, returns top `top_n` sorted by `score` descending.

- [ ] **Step 1: Write the failing test**

`tests/test_score.py`:
```python
import math
from bandcamp_reco.models import Album, album_key
from bandcamp_reco.score import score_candidates, Recommendation


def _album(url):
    return Album(item_id=url, album_id=None, title=url.split("/")[-1],
                 artist="A", url=url, art_url=None)


OWNED = {f"https://own/{i}" for i in range(10)}


def test_excludes_owned_albums():
    owned_albums = [_album(u) for u in OWNED]
    fan_albums = {"f1": owned_albums + [_album("https://cand/x")]}
    recs = score_candidates(OWNED, fan_albums, top_n=50)
    keys = {album_key(r.album) for r in recs}
    assert keys == {"https://cand/x"}


def test_high_affinity_niche_beats_popular_low_affinity():
    owned = [_album(u) for u in OWNED]
    # superfan shares all 10 owned albums, owns niche candidate N
    superfan = owned + [_album("https://cand/N")]
    # three dr-ive-by fans each share only 1 owned album, all own popular P
    drivebys = {
        f"d{i}": [_album("https://own/0"), _album("https://cand/P")]
        for i in range(3)
    }
    fan_albums = {"super": superfan, **drivebys}
    recs = score_candidates(OWNED, fan_albums, top_n=10)
    ranked = [album_key(r.album) for r in recs]
    assert ranked[0] == "https://cand/N"  # niche, high-affinity wins
    assert "https://cand/P" in ranked


def test_recommendation_fields_and_why():
    owned = [_album(u) for u in OWNED]
    fan_albums = {
        "f1": owned[:5] + [_album("https://cand/x")],
        "f2": owned[:3] + [_album("https://cand/x")],
    }
    recs = score_candidates(OWNED, fan_albums, top_n=10)
    rec = recs[0]
    assert isinstance(rec, Recommendation)
    assert rec.fan_count == 2
    # affinities 5 and 3 -> score 8, count 2 -> final 8/sqrt(2)
    assert math.isclose(rec.score, 8 / math.sqrt(2), rel_tol=1e-6)
    assert rec.typical_shared == 4  # round(mean([5,3]))
    assert "2 fans" in rec.why
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.score'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/score.py`:
```python
import math
from dataclasses import dataclass

from .models import Album, album_key


@dataclass
class Recommendation:
    album: Album
    score: float
    fan_count: int
    typical_shared: int
    why: str


def score_candidates(owned_keys, fan_albums, top_n) -> list[Recommendation]:
    # affinity per fan = how many of YOUR albums they also own
    affinity = {}
    fan_keys = {}
    for fan, albums in fan_albums.items():
        keys = {album_key(a) for a in albums}
        fan_keys[fan] = keys
        affinity[fan] = len(keys & owned_keys)

    # aggregate candidates (albums you don't own)
    agg: dict[str, dict] = {}
    for fan, albums in fan_albums.items():
        for album in albums:
            k = album_key(album)
            if k in owned_keys:
                continue
            entry = agg.setdefault(
                k, {"album": album, "score": 0.0, "count": 0, "shared": []}
            )
            entry["score"] += affinity[fan]
            entry["count"] += 1
            entry["shared"].append(affinity[fan])

    recs = []
    for entry in agg.values():
        count = entry["count"]
        final = entry["score"] / math.sqrt(count) if count else 0.0
        typical = round(sum(entry["shared"]) / count) if count else 0
        why = (
            f"Owned by {count} fans who each share "
            f"~{typical} albums with your collection."
        )
        recs.append(Recommendation(
            album=entry["album"], score=final, fan_count=count,
            typical_shared=typical, why=why,
        ))

    recs.sort(key=lambda r: r.score, reverse=True)
    return recs[:top_n]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_score.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/score.py tests/test_score.py
git commit -m "feat: add candidate scoring with affinity weighting and dampening"
```

---

### Task 9: Render — HTML output

**Files:**
- Create: `bandcamp_reco/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `Recommendation` (from `score.py`), `Album`.
- Produces:
  - `render_html(recommendations: list[Recommendation], username: str) -> str` — full standalone HTML (inline CSS), all dynamic fields HTML-escaped.
  - `write_html(html: str, path: str) -> None`.

- [ ] **Step 1: Write the failing test**

`tests/test_render.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.render'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/render.py`:
```python
from html import escape

from .score import Recommendation

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bandcamp recommendations for {username}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem auto;
          max-width: 760px; color: #222; }}
  h1 {{ font-size: 1.4rem; }}
  .rec {{ display: flex; gap: 1rem; padding: 1rem 0; border-top: 1px solid #eee; }}
  .rec img {{ width: 100px; height: 100px; object-fit: cover; background: #f3f3f3; }}
  .meta {{ flex: 1; }}
  .title {{ font-weight: 600; }}
  .artist {{ color: #555; }}
  .tags {{ color: #888; font-size: 0.85rem; margin-top: 0.25rem; }}
  .why {{ color: #777; font-size: 0.85rem; margin-top: 0.25rem; }}
  a {{ color: #1a6; text-decoration: none; }}
</style>
</head>
<body>
<h1>Recommendations for {username}</h1>
<p>{count} albums, ranked by how much taste their owners share with you.</p>
{rows}
</body>
</html>
"""

_ROW = """<div class="rec">
  {img}
  <div class="meta">
    <div class="title"><a href="{url}">{title}</a></div>
    <div class="artist">{artist}</div>
    <div class="tags">{tags}</div>
    <div class="why">{why}</div>
  </div>
</div>"""


def _row(rec: Recommendation) -> str:
    a = rec.album
    img = (f'<img src="{escape(a.art_url)}" alt="">' if a.art_url
           else '<div class="rec-noart"></div>')
    return _ROW.format(
        img=img,
        url=escape(a.url),
        title=escape(a.title),
        artist=escape(a.artist),
        tags=escape(", ".join(a.tags)),
        why=escape(rec.why),
    )


def render_html(recommendations, username: str) -> str:
    rows = "\n".join(_row(r) for r in recommendations)
    return _PAGE.format(username=escape(username),
                        count=len(recommendations), rows=rows)


def write_html(html: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_render.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/render.py tests/test_render.py
git commit -m "feat: add HTML rendering of recommendations"
```

---

### Task 10: Orchestration + CLI

**Files:**
- Create: `bandcamp_reco/main.py`
- Create: `recommend.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything above — `load_config`, `Config`, `Cache`, `Fetcher`, `get_collection`, `get_supporters`, `get_album_page`, `get_fan_collections`, `score_candidates`, `render_html`, `write_html`, `album_key`.
- Produces:
  - `run(config: Config, fetcher, cache) -> list[Recommendation]` — executes the pipeline end to end, also enriching the top-`top_n` candidates with tags via `get_album_page`, writes the HTML, and returns the recommendations.
  - `main(argv: list[str] | None = None) -> int` — parses args (`--config`, `--top-n`, `--limit`), builds real `Cache`/`Fetcher`, calls `run`, prints the output path.

- [ ] **Step 1: Write the failing test**

`tests/test_main.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.main'`

- [ ] **Step 3: Write minimal implementation**

`bandcamp_reco/main.py`:
```python
import argparse
import dataclasses

from .cache import Cache
from .collection import get_collection
from .config import load_config
from .fans import get_fan_collections
from .fetch import Fetcher, CircuitBreakerTripped
from .models import album_key
from .render import render_html, write_html
from .score import score_candidates
from .supporters import get_supporters, get_album_page


def run(config, fetcher, cache):
    owned = get_collection(config.username, fetcher, cache)
    owned_keys = {album_key(a) for a in owned}

    # collect candidate supporters across owned albums
    supporter_usernames = []
    try:
        for album in owned:
            supporter_usernames.extend(
                get_supporters(album, fetcher, cache,
                               limit=config.supporters_per_album)
            )
    except CircuitBreakerTripped:
        pass  # proceed with whatever we gathered; cache holds progress

    fan_albums = get_fan_collections(
        supporter_usernames, fetcher, cache,
        max_fans=config.max_fans,
        max_albums_per_fan=config.max_albums_per_fan,
    )

    recs = score_candidates(owned_keys, fan_albums, top_n=config.top_n)
    recs = _enrich_tags(recs, fetcher, cache)

    html = render_html(recs, username=config.username)
    write_html(html, config.output_path)
    return recs


def _enrich_tags(recs, fetcher, cache):
    enriched = []
    for rec in recs:
        try:
            info = get_album_page(rec.album, fetcher, cache)
            album = dataclasses.replace(rec.album, tags=tuple(info.tags))
            enriched.append(dataclasses.replace(rec, album=album))
        except Exception:
            enriched.append(rec)
    return enriched


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bandcamp recommendations")
    parser.add_argument("--config", default=None)
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None,
                        help="dry run: cap owned albums processed")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.top_n is not None:
        config = dataclasses.replace(config, top_n=args.top_n)

    cache = Cache(config.cache_path)
    fetcher = Fetcher(delay=config.request_delay)
    try:
        recs = run(config, fetcher, cache)
    finally:
        cache.close()
    print(f"Wrote {len(recs)} recommendations to {config.output_path}")
    return 0
```

> NOTE on `--limit`: thread it through by replacing `owned = get_collection(...)` with
> `owned = get_collection(config.username, fetcher, cache, max_items=args_limit)` only in `main` by
> passing `config` plus an optional `limit` arg into `run`. To keep `run` testable, add a
> keyword `limit: int | None = None` to `run`, pass it as `max_items` to the user's
> `get_collection`, and forward `args.limit` from `main`. Add this in Step 3 implementation.

- [ ] **Step 4: Add the `limit` passthrough**

Update `run` signature to `def run(config, fetcher, cache, limit=None):` and change the first line to `owned = get_collection(config.username, fetcher, cache, max_items=limit)`. In `main`, call `run(config, fetcher, cache, limit=args.limit)`.

- [ ] **Step 5: Create the entry point**

`recommend.py`:
```python
import sys

from bandcamp_reco.main import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS (1 passed)

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -v`
Expected: PASS (all tests across all files green)

- [ ] **Step 8: Commit**

```bash
git add bandcamp_reco/main.py recommend.py tests/test_main.py
git commit -m "feat: wire pipeline orchestration and CLI entry point"
```

---

### Task 11: Live validation, fixture refresh & README

This task has no unit test — it validates the parsers against the **real** Bandcamp site (whose JSON shapes are unofficial) and documents usage. Do it carefully and politely.

**Files:**
- Create: `README.md`
- Modify (if live shapes differ): `bandcamp_reco/collection.py`, `bandcamp_reco/supporters.py`, and the corresponding fixtures/tests.

- [ ] **Step 1: Install dependencies**

Run: `python -m pip install -r requirements.txt`
Expected: requests, beautifulsoup4, pytest installed.

- [ ] **Step 2: Smoke-test collection parsing against the live profile**

Run:
```bash
python -c "from bandcamp_reco.fetch import Fetcher; from bandcamp_reco.cache import Cache; from bandcamp_reco.collection import get_collection; c=Cache('cache.db'); albums=get_collection('jmaskell', Fetcher(), c, max_items=5); print(len(albums)); [print(a.artist, '-', a.title, a.url) for a in albums]; c.close()"
```
Expected: prints up to 5 real albums from the jmaskell collection with sane artist/title/URL.
**If it prints 0 or garbage:** the live `data-blob` keys differ from the fixture. Fetch the page once (`Fetcher().get('https://bandcamp.com/jmaskell').text`), inspect the `#pagedata` `data-blob` JSON, update `raw_to_album` / `_albums_from_item_cache` / `get_collection` key names to match, refresh the fixture in `tests/test_collection.py`, and re-run `pytest tests/test_collection.py`.

- [ ] **Step 3: Smoke-test album-page parsing (supporters + tags)**

Using one real album URL from Step 2's output, run:
```bash
python -c "from bandcamp_reco.fetch import Fetcher; from bandcamp_reco.cache import Cache; from bandcamp_reco.supporters import get_album_page; from bandcamp_reco.models import Album; c=Cache('cache.db'); a=Album(item_id='',album_id=None,title='',artist='',url='REPLACE_WITH_REAL_ALBUM_URL',art_url=None); info=get_album_page(a, Fetcher(), c); print('tags:', info.tags); print('supporters:', info.supporter_usernames[:10]); c.close()"
```
Expected: prints real tags and a list of supporter usernames.
**If supporters is empty:** the live album `data-blob` stores collectors under a different key (e.g. nested under `tracks`/`current`, or only fetchable via the `tralbumcollectors` thumbs API). Inspect the real `data-blob`, update `parse_album_page` to read the correct key, refresh the fixture in `tests/test_supporters.py`, and re-run `pytest tests/test_supporters.py`. If only the thumbs API exposes the full list, add a `get_supporters` branch that POSTs to `https://bandcamp.com/api/tralbumcollectors/2/thumbs` with `{"tralbum_type":"a","tralbum_id":info.tralbum_id,"count":limit}` and reads usernames from `results`.

- [ ] **Step 4: Full dry run end to end**

Run: `python recommend.py --limit 5 --top-n 15`
Expected: completes within a couple of minutes, prints `Wrote N recommendations to recommendations.html`.

- [ ] **Step 5: Eyeball the output**

Run: `open recommendations.html`
Expected: a browsable page of albums you don't own, each with artist/title, tags, a "why", and a working Bandcamp link. Sanity-check that none are albums you already own and the "why" counts look plausible.

- [ ] **Step 6: Confirm the full suite still passes**

Run: `python -m pytest -v`
Expected: all green (including any fixtures you refreshed).

- [ ] **Step 7: Write the README**

`README.md`:
```markdown
# Bandcamp Recommendations

Reads your **public** Bandcamp collection, finds fans whose taste overlaps
yours, and ranks albums they own that you don't — output as a browsable HTML page.

## Setup

    python -m pip install -r requirements.txt

## Usage

    python recommend.py                 # full run, uses config.toml
    python recommend.py --limit 5       # quick dry run (cap owned albums)
    python recommend.py --top-n 100     # render more recommendations

Open `recommendations.html` in your browser when it finishes.

## Config

Edit `config.toml` — your `username`, sampling caps, request delay, output path.

## How it works

1. Reads your collection from `bandcamp.com/<username>`.
2. For each album, finds other fans who bought it ("supported by").
3. Reads those fans' public collections.
4. Scores albums you don't own by how much taste their owners share with you,
   damping for raw popularity.
5. Renders the top results to `recommendations.html`.

## Notes

- Read-only and login-free — it only reads public pages.
- Everything is cached in `cache.db`, so re-runs are fast and resumable. If
  Bandcamp rate-limits you, the run stops cleanly; just run it again later.
- Bandcamp's data shapes are unofficial; if the site changes, the parsers in
  `collection.py` / `supporters.py` may need a small update.
```

- [ ] **Step 8: Commit**

```bash
git add README.md bandcamp_reco/ tests/
git commit -m "docs: add README; validate parsers against live Bandcamp"
```

---

## Self-Review

**1. Spec coverage:**
- Public collection scrape → Tasks 5, 11. ✓
- Fans-also-bought collaborative engine → Tasks 6 (supporters), 7 (fan collections), 8 (scoring). ✓
- Affinity scoring + sqrt popularity dampening + "why" string → Task 8. ✓
- Ranked HTML output with art/artist/title/tags/why/buy-link → Task 9; tag enrichment → Task 10. ✓
- SQLite read-through cache, resumable → Task 3, used in Tasks 5/6/7. ✓
- Polite HTTP: single-threaded, delay+jitter, backoff, circuit breaker → Task 4; breaker handled gracefully in Tasks 7 and 10. ✓
- Config (username + caps) → Task 2. ✓
- Parser unit tests on fixtures, scoring tests, cache tests, `--limit` dry run → Tasks 3/5/6/8/10/11. ✓
- Risk note (unofficial endpoints) → Task 11 validation. ✓

**2. Placeholder scan:** No "TBD/TODO/handle edge cases" left as instructions. The two `NOTE` blocks (Task 5 stray-line cleanup, Task 10 `--limit` passthrough) are explicit follow-up steps with concrete edits, each followed by a dedicated step — not placeholders. Task 11's `REPLACE_WITH_REAL_ALBUM_URL` is intentional (depends on live data discovered in Step 2).

**3. Type consistency:**
- `Album` fields and `album_key` used identically in Tasks 1, 5, 6, 7, 8, 9, 10. ✓
- `Fetcher.get`/`post_json`, `Cache.get`/`set` signatures consistent across consumers. ✓
- `get_collection(username, fetcher, cache, max_items=None)` called consistently in Tasks 7 and 10. ✓
- `Recommendation` fields (`album`, `score`, `fan_count`, `typical_shared`, `why`) produced in Task 8 and consumed in Task 9. ✓
- `AlbumPageInfo` (`tralbum_id`, `tags`, `supporter_usernames`) produced in Task 6 and consumed in Task 10's `_enrich_tags`. ✓
