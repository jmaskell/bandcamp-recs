# Apple Music Availability + Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For each recommended album, check whether it is on Apple Music (via the public iTunes Search API), link to it when available, and let the page filter by availability — with a way to flag wrong matches for later debugging.

**Architecture:** A new `apple_music.py` module searches the keyless iTunes Search API and matches results to Bandcamp albums. After the candidate pool is built, `main.py` looks it up — throttled (~3s/request) and resumable, caching each result in SQLite — annotates each pool item with an availability state, and the page renders links, two filter checkboxes, and a localStorage-backed flag/export UI. The whole feature is additive: with the feature disabled, the page is identical to today.

**Tech Stack:** Python 3.11+, `requests`, `beautifulsoup4`, stdlib `difflib`/`unicodedata`, `pytest`. No new dependency.

## Global Constraints

- Python 3.11+ (the codebase already uses `tomllib`).
- **No new dependency** — the iTunes Search API is a plain `requests` GET.
- Data source is the public iTunes Search API: `https://itunes.apple.com/search`, params `term`, `entity=album`, `media=music`, `country`, `limit=10`. No auth.
- `country` defaults to `"gb"`; `request_delay` defaults to `3.0` seconds (the API allows ~20 requests/minute).
- Matching is **precision-leaning**: similarity threshold `0.85`; when unsure, return `unavailable`, never guess.
- Apple Music failures must **never** break a run. Rate-limiting (HTTP 403/429) stops the Apple phase cleanly and resumes from cache next run.
- All Apple Music UI is guarded by an `apple_enabled` flag so the page is behaviorally/visually identical to today when the feature is off (the guarded markup/CSS/JS ship but stay hidden and inert; raw bytes differ, nothing renders or runs).
- Cache namespace is `"apple_music"`, keyed by `album_key_from_url(item["url"])`. Only definitive results (`available`/`unavailable`) are cached; albums not reached stay `unknown` and are looked up on a later run.
- Match existing test conventions: dict-backed `StubCache`, `FakeSession`/`FakeResponse`, `monkeypatch`, `tmp_path`.
- Run tests with `python -m pytest`.

---

## File Structure

- Create: `bandcamp_reco/apple_music.py` — iTunes search client, matching, resumable lookup.
- Modify: `bandcamp_reco/models.py` — add `album_key_from_url(url)` helper.
- Modify: `bandcamp_reco/config.py` — parse `[apple_music]` into `AppleMusicConfig`.
- Modify: `bandcamp_reco/main.py` — lookup phase, annotate pool, pass `apple_enabled` to render.
- Modify: `bandcamp_reco/render.py` — Apple link, two filter checkboxes, flag/export UI, all guarded.
- Modify: `config.toml` — `[apple_music]` block.
- Modify: `README.md` — Apple Music section.
- Create: `tests/test_apple_music.py`.
- Modify: `tests/test_config.py`, `tests/test_models.py`, `tests/test_main.py`, `tests/test_render.py`.

---

## Task 1: Matching logic

Pure functions: normalize strings, match iTunes search results to a Bandcamp album. No network.

**Files:**
- Create: `bandcamp_reco/apple_music.py`
- Test: `tests/test_apple_music.py`

**Interfaces:**
- Produces:
  - `AppleMatch` — `@dataclass(frozen=True)` with `status: str` (`"available"` | `"unavailable"`), `url: str | None`, `name: str | None`, `artist: str | None`.
  - `normalize(text: str) -> str`
  - `match_album(artist: str, title: str, results: list[dict]) -> AppleMatch` where each `result` dict has flat keys `collectionName`, `artistName`, `collectionViewUrl` (the iTunes Search API shape).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_apple_music.py`:

```python
from bandcamp_reco.apple_music import normalize, match_album, AppleMatch


def _result(name, artist, url="https://music.apple.com/gb/album/x/1"):
    return {"collectionName": name, "artistName": artist, "collectionViewUrl": url}


def test_normalize_strips_brackets_diacritics_and_punctuation():
    assert normalize("Sǽ (Deluxe Edition)") == "sae"
    assert normalize("Album - EP") == "album"
    assert normalize("A/B & C!") == "a b c"


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bandcamp_reco.apple_music'`.

- [ ] **Step 3: Write the implementation**

Create `bandcamp_reco/apple_music.py`:

```python
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

TITLE_THRESHOLD = 0.85
ARTIST_THRESHOLD = 0.85
_COMPILATION_ARTISTS = {"various artists", "various", "va", ""}

_BRACKETS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_SUFFIX = re.compile(r"\s*[-–—]\s*(ep|single|lp)\s*$")
_NONALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class AppleMatch:
    status: str            # "available" | "unavailable"
    url: str | None
    name: str | None
    artist: str | None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = _BRACKETS.sub("", text)
    text = _SUFFIX.sub("", text)
    text = _NONALNUM.sub(" ", text)
    return text.strip()


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def match_album(artist: str, title: str, results: list[dict]) -> AppleMatch:
    want_artist = normalize(artist)
    want_title = normalize(title)
    is_comp = want_artist in _COMPILATION_ARTISTS

    best = None
    best_score = 0.0
    for r in results:
        title_score = _ratio(want_title, normalize(r.get("collectionName", "")))
        if title_score < TITLE_THRESHOLD:
            continue
        if is_comp:
            artist_score = 0.0
        else:
            artist_score = _ratio(want_artist, normalize(r.get("artistName", "")))
            if artist_score < ARTIST_THRESHOLD:
                continue
        combined = title_score + artist_score
        if combined > best_score:
            best_score = combined
            best = r

    if best is None:
        return AppleMatch(status="unavailable", url=None, name=None, artist=None)
    return AppleMatch(
        status="available",
        url=best.get("collectionViewUrl"),
        name=best.get("collectionName"),
        artist=best.get("artistName"),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/apple_music.py tests/test_apple_music.py
git commit -m "feat: Apple Music (iTunes) album matching logic"
```

---

## Task 2: Config — AppleMusicConfig

Parse an `[apple_music]` table from `config.toml` into an optional `AppleMusicConfig`. No secrets, no overlay.

**Files:**
- Modify: `bandcamp_reco/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `AppleMusicConfig` — `@dataclass` with `enabled: bool`, `country: str`, `request_delay: float`.
  - `Config.apple_music: AppleMusicConfig | None` (defaults to `None`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`, and update the import line at the top to:

```python
from bandcamp_reco.config import load_config, Config, AppleMusicConfig
```

Then add:

```python
def test_apple_music_config_parsed_from_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'username = "me"\n'
        "[apple_music]\n"
        "enabled = true\n"
        'country = "us"\n'
        "request_delay = 2.0\n"
    )
    cfg = load_config(str(p))
    assert cfg.username == "me"
    assert cfg.apple_music is not None
    assert cfg.apple_music.country == "us"
    assert cfg.apple_music.request_delay == 2.0


def test_apple_music_config_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('username = "me"\n[apple_music]\n')  # empty section
    cfg = load_config(str(p))
    assert cfg.apple_music is not None
    assert cfg.apple_music.country == "gb"        # default
    assert cfg.apple_music.request_delay == 3.0   # default


def test_apple_music_config_absent_when_no_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('username = "me"\n')
    cfg = load_config(str(p))
    assert cfg.apple_music is None


def test_apple_music_config_none_when_disabled(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('username = "me"\n[apple_music]\nenabled = false\n')
    cfg = load_config(str(p))
    assert cfg.apple_music is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'AppleMusicConfig'`.

- [ ] **Step 3: Write the implementation**

Replace the entire contents of `bandcamp_reco/config.py` with:

```python
import os
import tomllib
from dataclasses import dataclass


@dataclass
class AppleMusicConfig:
    enabled: bool
    country: str
    request_delay: float


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
    affinity_cap: int
    max_per_source: int
    hide_owned_sources: bool
    apple_music: AppleMusicConfig | None = None


DEFAULTS = {
    "username": "jmaskell",
    "supporters_per_album": 30,
    "max_fans": 500,
    "max_albums_per_fan": 200,
    "top_n": 50,
    "request_delay": 0.7,
    "cache_path": "cache.db",
    "output_path": "recommendations.html",
    "affinity_cap": 4,
    "max_per_source": 2,
    "hide_owned_sources": False,
}


def _parse_apple(section) -> AppleMusicConfig | None:
    # `section is None` means no [apple_music] table at all; an empty table
    # parses to {} (falsy) but should still yield a default-enabled config.
    if section is None or not section.get("enabled", True):
        return None
    return AppleMusicConfig(
        enabled=True,
        country=section.get("country", "gb"),
        request_delay=float(section.get("request_delay", 3.0)),
    )


def load_config(path: str | None = None) -> Config:
    values = dict(DEFAULTS)
    raw: dict = {}
    path = path or "config.toml"
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        values.update(raw)
    base = {k: values[k] for k in DEFAULTS}
    return Config(apple_music=_parse_apple(raw.get("apple_music")), **base)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (existing 2 + new 4 = 6 passed).

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/config.py tests/test_config.py
git commit -m "feat: parse [apple_music] config section"
```

---

## Task 3: iTunes Search client

A small client that calls the iTunes Search API with its own throttle and turns rate-limiting (403/429) into a clean signal.

**Files:**
- Modify: `bandcamp_reco/apple_music.py`
- Test: `tests/test_apple_music.py`

**Interfaces:**
- Produces:
  - `AppleRateLimited(Exception)`, `AppleSearchError(Exception)`.
  - `AppleMusicClient(*, session=None, delay=3.0, jitter=0.3, max_retries=2, backoff_ceiling=10.0)`.
  - `AppleMusicClient.search_album(artist, title, country) -> list[dict]` — the iTunes `results` list, or `[]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_apple_music.py`:

```python
import pytest

from bandcamp_reco.apple_music import AppleMusicClient, AppleRateLimited


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("bandcamp_reco.apple_music.time.sleep", lambda *_: None)
    monkeypatch.setattr("bandcamp_reco.apple_music.random.uniform", lambda *_: 0.0)


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: FAIL with `ImportError: cannot import name 'AppleMusicClient'`.

- [ ] **Step 3: Write the implementation**

Add to `bandcamp_reco/apple_music.py` — add `import time`, `import random`, and `import requests` to the imports at the top, then add:

```python
SEARCH_URL = "https://itunes.apple.com/search"


class AppleRateLimited(Exception):
    pass


class AppleSearchError(Exception):
    pass


class AppleMusicClient:
    def __init__(self, *, session=None, delay=3.0, jitter=0.3,
                 max_retries=2, backoff_ceiling=10.0):
        self._session = session or requests.Session()
        self.delay = delay
        self.jitter = jitter
        self.max_retries = max_retries
        self.backoff_ceiling = backoff_ceiling

    def _throttle(self):
        time.sleep(self.delay + random.uniform(0.0, self.jitter))

    def _backoff(self, attempt):
        time.sleep(min(self.delay * (2 ** attempt), self.backoff_ceiling))

    def search_album(self, artist, title, country) -> list[dict]:
        params = {"term": f"{artist} {title}".strip(), "country": country,
                  "media": "music", "entity": "album", "limit": 10}
        for attempt in range(self.max_retries + 1):
            self._throttle()
            resp = self._session.get(SEARCH_URL, params=params)
            if resp.status_code in (403, 429):
                raise AppleRateLimited()
            if 500 <= resp.status_code < 600:
                if attempt >= self.max_retries:
                    raise AppleSearchError(f"server error {resp.status_code}")
                self._backoff(attempt)
                continue
            resp.raise_for_status()
            data = resp.json() or {}
            return data.get("results") or []
        raise AppleSearchError("exhausted retries")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: PASS (all 10 passed).

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/apple_music.py tests/test_apple_music.py
git commit -m "feat: iTunes Search API client"
```

---

## Task 4: Throttled, resumable lookup

Walk the pool serially, skip cached albums, cache each result immediately, and stop cleanly on rate-limiting so a later run resumes from the cache.

**Files:**
- Modify: `bandcamp_reco/models.py`
- Modify: `bandcamp_reco/apple_music.py`
- Test: `tests/test_models.py`, `tests/test_apple_music.py`

**Interfaces:**
- Consumes: `match_album` (Task 1), `AppleRateLimited` (Task 3), `AppleMatch` (Task 1).
- Produces:
  - `models.album_key_from_url(url: str) -> str`.
  - `lookup_pool(pool, client, cache, country) -> dict[str, AppleMatch]` — keyed by `album_key_from_url(item["url"])`. Each `pool` item is a dict with at least `url`, `artist`, `title`.

- [ ] **Step 1: Write the failing test for the models helper**

Append to `tests/test_models.py`:

```python
def test_album_key_from_url_strips_query_and_trailing_slash():
    from bandcamp_reco.models import album_key_from_url
    assert (album_key_from_url("https://x.bandcamp.com/album/y/?from=1")
            == "https://x.bandcamp.com/album/y")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'album_key_from_url'`.

- [ ] **Step 3: Add the models helper**

In `bandcamp_reco/models.py`, replace the existing `album_key` function:

```python
def album_key(album: "Album") -> str:
    return album.url.split("?")[0].rstrip("/")
```

with:

```python
def album_key_from_url(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def album_key(album: "Album") -> str:
    return album_key_from_url(album.url)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Write the failing tests for lookup_pool**

Append to `tests/test_apple_music.py`:

```python
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
```

- [ ] **Step 6: Run them to verify they fail**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: FAIL with `ImportError: cannot import name 'lookup_pool'`.

- [ ] **Step 7: Write the implementation**

Add to `bandcamp_reco/apple_music.py` — add `import dataclasses` and `from .models import album_key_from_url` to the imports at the top, then add:

```python
def lookup_pool(pool, client, cache, country) -> dict:
    results: dict = {}
    for item in pool:
        key = album_key_from_url(item["url"])
        cached = cache.get("apple_music", key)
        if cached is not None:
            results[key] = AppleMatch(**cached)
            continue
        try:
            found = client.search_album(item["artist"], item["title"], country)
        except AppleRateLimited:
            break  # stop cleanly; remaining albums stay unknown, resume next run
        except Exception:
            continue  # unknown: not cached, retried next run
        match = match_album(item["artist"], item["title"], found)
        cache.set("apple_music", key, dataclasses.asdict(match))
        results[key] = match
    return results
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/test_apple_music.py tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add bandcamp_reco/apple_music.py bandcamp_reco/models.py tests/test_apple_music.py tests/test_models.py
git commit -m "feat: throttled resumable Apple Music pool lookup"
```

---

## Task 5: Wire the lookup into the pipeline

After the pool is built, run the Apple phase when enabled, annotate each pool item, and pass `apple_enabled` to the renderer. Apple failures never break the run.

**Files:**
- Modify: `bandcamp_reco/render.py` (signature only, Step 1)
- Modify: `bandcamp_reco/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `AppleMusicClient`, `lookup_pool` (Tasks 3–4), `album_key_from_url` (Task 4), `Config.apple_music` (Task 2).
- Produces: pool items annotated with `apple` (`"available"`/`"unavailable"`/`"unknown"`) and, when available, `appleUrl`/`appleName`/`appleArtist`; calls `render_html(..., apple_enabled=<bool>)`.

Note on ordering: `render_html` does not yet accept `apple_enabled`. Step 1 adds that parameter and the `APPLE_ENABLED` JS const (a minimal signature + template change) so this task is testable on its own; Task 6 then builds the visible UI on top of the const.

- [ ] **Step 1: Add the `apple_enabled` parameter to render_html (signature only)**

In `bandcamp_reco/render.py`, change the `render_html` signature from:

```python
def render_html(pool: list[dict], username: str, defaults: dict,
                owned_sources=()) -> str:
```

to:

```python
def render_html(pool: list[dict], username: str, defaults: dict,
                owned_sources=(), apple_enabled: bool = False) -> str:
```

and change the end of the returned expression from:

```python
        .replace("__USERNAME_TEXT__", _html_escape(username))
    )
```

to:

```python
        .replace("__USERNAME_TEXT__", _html_escape(username))
        .replace("__APPLE_ENABLED__", "true" if apple_enabled else "false")
    )
```

Then, in the template's `<script>` block, directly under `const OWNED_SOURCES = new Set(__OWNED_SOURCES__);` add:

```javascript
const APPLE_ENABLED = __APPLE_ENABLED__;
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_main.py` — add these imports at the top:

```python
import dataclasses
from bandcamp_reco.config import AppleMusicConfig
from bandcamp_reco.apple_music import AppleMatch
```

Then append the tests:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL — `AppleMusicClient`/`lookup_pool` are not attributes of `main_mod` yet.

- [ ] **Step 4: Write the implementation**

In `bandcamp_reco/main.py`, add to the imports at the top:

```python
import sys

from .apple_music import AppleMusicClient, lookup_pool
from .models import album_key, album_source, album_key_from_url
```

(Replace the existing `from .models import album_key, album_source` line with the one above.)

Add this helper function:

```python
def _apply_apple_music(config, pool, cache) -> bool:
    if config.apple_music is None:
        return False
    try:
        client = AppleMusicClient(delay=config.apple_music.request_delay)
        results = lookup_pool(pool, client, cache, config.apple_music.country)
    except Exception as exc:
        print(f"Apple Music: disabled ({exc})", file=sys.stderr)
        return False
    for item in pool:
        match = results.get(album_key_from_url(item["url"]))
        if match is None:
            item["apple"] = "unknown"
        elif match.status == "available":
            item["apple"] = "available"
            item["appleUrl"] = match.url or ""
            item["appleName"] = match.name or ""
            item["appleArtist"] = match.artist or ""
        else:
            item["apple"] = "unavailable"
    return True
```

In `run()`, replace:

```python
    html = render_html(pool, username=config.username, defaults=defaults,
                       owned_sources=owned_sources)
```

with:

```python
    apple_enabled = _apply_apple_music(config, pool, cache)
    html = render_html(pool, username=config.username, defaults=defaults,
                       owned_sources=owned_sources, apple_enabled=apple_enabled)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS (existing 4 + new 3 = 7 passed).

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/main.py bandcamp_reco/render.py tests/test_main.py
git commit -m "feat: wire Apple Music lookup into the pipeline"
```

---

## Task 6: Page — Apple link + two filter checkboxes

Render an Apple Music link per available album and add the two combining filter checkboxes, all guarded behind `APPLE_ENABLED`.

**Files:**
- Modify: `bandcamp_reco/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `render_html(..., apple_enabled=...)` and the `APPLE_ENABLED` JS const (Task 5 Step 1).
- Produces: page with `id="appleControls"`, `id="hideOnApple"`, `id="hideNotApple"`, and per-row Apple Music link.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py`:

```python
def _apple_pool():
    p = _pool()
    p[0]["apple"] = "available"
    p[0]["appleUrl"] = "https://music.apple.com/gb/album/z/123"
    p[0]["appleName"] = "Weird & Wonderful"
    p[0]["appleArtist"] = "Cool Band"
    return p


def test_render_apple_disabled_when_not_requested():
    html = render_html(_pool(), username="u", defaults=DEFAULTS)
    assert "APPLE_ENABLED = false" in html


def test_render_apple_enabled_embeds_controls_and_data():
    html = render_html(_apple_pool(), username="u", defaults=DEFAULTS,
                       apple_enabled=True)
    assert "APPLE_ENABLED = true" in html
    assert 'id="hideOnApple"' in html
    assert 'id="hideNotApple"' in html
    assert "https://music.apple.com/gb/album/z/123" in html
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_render.py -v`
Expected: FAIL — `id="hideOnApple"` not present.

- [ ] **Step 3: Add the filter checkboxes markup**

In `bandcamp_reco/render.py`, in the `_PAGE` template, immediately after the existing owned-sources toggle:

```html
<label class="toggle"><input type="checkbox" id="hideOwned"> Hide labels/artists I already
own music from <span class="hint" id="ownedCount"></span></label>
```

add:

```html
<div id="appleControls" style="display:none">
  <label class="toggle"><input type="checkbox" id="hideOnApple"> Hide albums on Apple Music</label>
  <label class="toggle"><input type="checkbox" id="hideNotApple"> Hide albums not on Apple Music</label>
</div>
```

- [ ] **Step 4: Add the Apple link CSS**

In the `<style>` block, after the `.why { ... }` rule, add:

```css
  .apple { font-size: 0.8rem; margin-top: 0.25rem; }
  .apple a { color: #fa2d6c; }
  .apple .na { color: #bbb; }
```

- [ ] **Step 5: Render the Apple link per row**

In the `row(r, rank)` function, after the block that appends `why` to `meta`:

```javascript
  const why = document.createElement("div");
  why.className = "why"; why.textContent = whyText(r.fans, r.typical);
  meta.appendChild(why);
```

add:

```javascript
  if (APPLE_ENABLED) {
    const apple = document.createElement("div");
    apple.className = "apple";
    if (it.apple === "available" && it.appleUrl) {
      const al = document.createElement("a");
      al.href = it.appleUrl; al.textContent = "Apple Music";
      al.target = "_blank"; al.rel = "noopener";
      apple.appendChild(al);
    } else {
      const na = document.createElement("span");
      na.className = "na"; na.textContent = "Not on Apple Music";
      apple.appendChild(na);
    }
    meta.appendChild(apple);
  }
```

- [ ] **Step 6: Apply the filters and reveal the controls**

In the `render()` function, after:

```javascript
  if (hideOwned.checked) {
    rows = rows.filter((r) => !OWNED_SOURCES.has(r.item.source));
  }
```

add:

```javascript
  if (APPLE_ENABLED) {
    if (el("hideOnApple").checked) {
      rows = rows.filter((r) => r.item.apple !== "available");
    }
    if (el("hideNotApple").checked) {
      rows = rows.filter((r) => r.item.apple === "available");
    }
  }
```

Then, after `hideOwned.addEventListener("change", render);`, add:

```javascript
if (APPLE_ENABLED) {
  el("appleControls").style.display = "";
  el("hideOnApple").addEventListener("change", render);
  el("hideNotApple").addEventListener("change", render);
}
```

And change the reset handler from:

```javascript
el("reset").addEventListener("click", (e) => { e.preventDefault(); applyDefaults(); render(); });
```

to:

```javascript
el("reset").addEventListener("click", (e) => {
  e.preventDefault();
  applyDefaults();
  if (APPLE_ENABLED) { el("hideOnApple").checked = false; el("hideNotApple").checked = false; }
  render();
});
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_render.py -v`
Expected: PASS (existing + 2 new).

- [ ] **Step 8: Commit**

```bash
git add bandcamp_reco/render.py tests/test_render.py
git commit -m "feat: Apple Music link + availability filter checkboxes"
```

---

## Task 7: Page — flag / export UI

Add a per-row "flag" toggle that records wrong matches into `localStorage`, plus a bar to show the count, export to JSON, and clear. Guarded behind `APPLE_ENABLED`.

**Files:**
- Modify: `bandcamp_reco/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `APPLE_ENABLED`, per-row Apple data (Task 6).
- Produces: page with `id="flagBar"` and an export that downloads `apple-music-flags.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py`:

```python
def test_render_includes_flag_ui_when_apple_enabled():
    html = render_html(_apple_pool(), username="u", defaults=DEFAULTS,
                       apple_enabled=True)
    assert 'id="flagBar"' in html
    assert "apple-music-flags.json" in html


def test_render_has_no_apple_flag_when_disabled():
    html = render_html(_pool(), username="u", defaults=DEFAULTS)
    assert "APPLE_ENABLED = false" in html
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_render.py -v`
Expected: FAIL — `id="flagBar"` not present.

- [ ] **Step 3: Add the flag bar markup**

In the `_PAGE` template, immediately before `<div id="recs"></div>`, add:

```html
<div id="flagBar" style="display:none; font-size:0.85rem; color:#666; margin:0.5rem 0;">
  <span id="flagCount">0 flagged</span>
  &mdash; <a href="#" id="flagExport">Export</a>
  &middot; <a href="#" id="flagClear">Clear</a>
</div>
```

- [ ] **Step 4: Add the flag CSS**

In the `<style>` block, after the `.apple` rules added in Task 6, add:

```css
  .flag { background: none; border: none; cursor: pointer; color: #bbb;
          font-size: 0.85rem; padding: 0; margin-left: 0.5rem; }
  .flag.on { color: #fa2d6c; }
```

- [ ] **Step 5: Add the flag store and wiring**

In the `<script>`, after the `const hideOwned = el("hideOwned");` line (so `el` is already defined), add the flag store:

```javascript
const FLAG_KEY = "bandcampAppleFlags";

function loadFlags() {
  try { return JSON.parse(localStorage.getItem(FLAG_KEY)) || {}; }
  catch (e) { return {}; }
}
function saveFlags(flags) {
  localStorage.setItem(FLAG_KEY, JSON.stringify(flags));
}
function updateFlagCount() {
  const n = Object.keys(loadFlags()).length;
  el("flagCount").textContent = n + " flagged";
}
function toggleFlag(item) {
  const flags = loadFlags();
  if (flags[item.url]) {
    delete flags[item.url];
  } else {
    flags[item.url] = {
      title: item.title, artist: item.artist, url: item.url,
      apple: item.apple || "unknown", appleUrl: item.appleUrl || "",
      appleName: item.appleName || "", appleArtist: item.appleArtist || "",
    };
  }
  saveFlags(flags);
  updateFlagCount();
  return !!flags[item.url];
}
```

In the `row(r, rank)` function, change the end of the `if (APPLE_ENABLED) { ... }` block added in Task 6 from:

```javascript
    meta.appendChild(apple);
  }
```

to:

```javascript
    const flagged = !!loadFlags()[it.url];
    const fb = document.createElement("button");
    fb.className = "flag" + (flagged ? " on" : "");
    fb.textContent = flagged ? "⚑ flagged" : "⚐ flag";
    fb.title = "Flag a wrong Apple Music match";
    fb.addEventListener("click", () => {
      const on = toggleFlag(it);
      fb.className = "flag" + (on ? " on" : "");
      fb.textContent = on ? "⚑ flagged" : "⚐ flag";
    });
    apple.appendChild(fb);
    meta.appendChild(apple);
  }
```

In the `if (APPLE_ENABLED) { ... }` block near the bottom (where `appleControls` is revealed), add the flag bar wiring:

```javascript
  el("flagBar").style.display = "";
  updateFlagCount();
  el("flagExport").addEventListener("click", (e) => {
    e.preventDefault();
    const data = JSON.stringify(Object.values(loadFlags()), null, 2);
    const blob = new Blob([data], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "apple-music-flags.json";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  el("flagClear").addEventListener("click", (e) => {
    e.preventDefault();
    localStorage.removeItem(FLAG_KEY);
    updateFlagCount();
    render();
  });
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_render.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite to confirm nothing regressed**

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add bandcamp_reco/render.py tests/test_render.py
git commit -m "feat: flag + export UI for wrong Apple Music matches"
```

---

## Task 8: Documentation + config block

Document setup and turn the feature on by default for this repo.

**Files:**
- Modify: `config.toml`
- Modify: `README.md`

- [ ] **Step 1: Add the [apple_music] block to config.toml**

At the end of `config.toml`, add:

```toml

# --- Apple Music (optional) ---
# Link recommendations to Apple Music and filter by availability, using the
# free public iTunes Search API (no account or key needed). Set enabled = false
# to turn it off and render the page exactly as before.
[apple_music]
enabled = true
country = "gb"          # Apple storefront/country to check
request_delay = 3.0     # seconds between lookups (the API allows ~20/min)
```

- [ ] **Step 2: Add a README section**

In `README.md`, after the `## Config` section, add:

```markdown
## Apple Music (optional)

The page can show whether each album is on Apple Music, link to it, and filter
by availability. It uses the free public iTunes Search API — no account or key
needed. Configure it in `config.toml`:

    [apple_music]
    enabled = true
    country = "gb"
    request_delay = 3.0

On a run, each recommendation is checked against the iTunes catalog and cached,
so re-runs are fast. The iTunes API allows only ~20 lookups/minute, so a first
full run adds time and may be rate-limited partway through — that is fine: it
stops cleanly and the next run resumes from the cache, just like the Bandcamp
crawl.

The page then shows an Apple Music link when available, two checkboxes to hide
albums that are / are not on Apple Music, and a "flag" button to mark wrong
matches — exportable as `apple-music-flags.json` for later debugging.

**Notes:** matching is deliberately strict (when unsure it reports "not on Apple
Music"), and only albums are matched — something that exists on Apple only as a
single will read as unavailable.
```

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add config.toml README.md
git commit -m "docs: Apple Music setup + enable by default"
```

---

## Self-Review Notes

- **Spec coverage:** data source / iTunes client (Task 3), country config (Task 2), throttled + resumable whole-pool lookup with per-album caching and rate-limit stop (Task 4), matching incl. compilations + albums-only (Task 1), tri-state data shape + cache namespace (Tasks 4–5), feature-off degradation (Tasks 2, 5), two filter checkboxes (Task 6), flag/export UI (Task 7), error handling incl. 403 rate-limit (Tasks 3–5), docs + enable-by-default (Task 8), tests in every task.
- **No credentials / no PyJWT:** the feature is keyless; nothing to install or store.
- **Out of scope:** singles-as-albums and the overrides feedback loop are explicitly not implemented.
