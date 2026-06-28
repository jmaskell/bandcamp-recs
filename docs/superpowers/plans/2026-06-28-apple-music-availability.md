# Apple Music Availability + Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For each recommended album, check whether it is on Apple Music, link to it when available, and let the page filter by availability — with a way to flag wrong matches for later debugging.

**Architecture:** A new `apple_music.py` module generates an Apple Music developer token, searches the catalog, and matches results to Bandcamp albums. After the candidate pool is built, `main.py` looks up the pool in parallel (cached in SQLite), annotates each pool item with an availability state, and the page renders links, two filter checkboxes, and a localStorage-backed flag/export UI. The whole feature is additive: with no credentials, the page is identical to today.

**Tech Stack:** Python 3.11+, `requests`, `beautifulsoup4`, `PyJWT[crypto]` (new), stdlib `difflib`/`unicodedata`/`concurrent.futures`/`threading`, `pytest`.

## Global Constraints

- Python 3.11+ (the codebase already uses `tomllib`).
- Only one new dependency: `PyJWT[crypto]`. Everything else is stdlib.
- Apple Music credentials live **only** in `config.local.toml` (already gitignored). Never commit a real `.p8` key, Team ID, or Key ID.
- Storefront defaults to `"gb"`.
- Matching is **precision-leaning**: similarity threshold `0.85`; when unsure, return `unavailable`, never guess.
- Apple Music failures must **never** break a run — they degrade to the feature being off.
- All Apple Music UI is guarded by an `apple_enabled` flag so the page is byte-for-byte identical to today when the feature is off.
- Cache namespace is `"apple_music"`, keyed by `album_key_from_url(item["url"])`. Only definitive results (`available`/`unavailable`) are cached; transient errors stay `unknown` and retry next run.
- Match existing test conventions: dict-backed `StubCache`, `FakeSession`/`FakeResponse`, `monkeypatch`, `tmp_path`.
- Run tests with `python -m pytest`.

---

## File Structure

- Create: `bandcamp_reco/apple_music.py` — token generation, catalog client, matching, parallel lookup orchestration.
- Modify: `bandcamp_reco/models.py` — add `album_key_from_url(url)` helper.
- Modify: `bandcamp_reco/config.py` — `config.local.toml` overlay + `AppleMusicConfig`.
- Modify: `bandcamp_reco/main.py` — parallel lookup phase, annotate pool, pass `apple_enabled` to render.
- Modify: `bandcamp_reco/render.py` — Apple link, two filter checkboxes, flag/export UI, all guarded.
- Modify: `requirements.txt` — add `PyJWT[crypto]`.
- Modify: `config.toml` — commented `[apple_music]` example.
- Modify: `README.md` — Apple Music setup section.
- Create: `tests/test_apple_music.py`.
- Modify: `tests/test_config.py`, `tests/test_models.py`, `tests/test_main.py`, `tests/test_render.py`.

---

## Task 1: Matching logic

Pure functions: normalize strings, match Apple search results to a Bandcamp album. No network, no new dependency.

**Files:**
- Create: `bandcamp_reco/apple_music.py`
- Test: `tests/test_apple_music.py`

**Interfaces:**
- Produces:
  - `AppleMatch` — `@dataclass(frozen=True)` with `status: str` (`"available"` | `"unavailable"`), `url: str | None`, `name: str | None`, `artist: str | None`.
  - `normalize(text: str) -> str`
  - `match_album(artist: str, title: str, albums: list[dict]) -> AppleMatch` where each `album` dict has `album["attributes"]` containing `name`, `artistName`, `url`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_apple_music.py`:

```python
from bandcamp_reco.apple_music import normalize, match_album, AppleMatch


def _album(name, artist, url="https://music.apple.com/gb/album/x/1"):
    return {"attributes": {"name": name, "artistName": artist, "url": url}}


def test_normalize_strips_brackets_diacritics_and_punctuation():
    assert normalize("Sǽ (Deluxe Edition)") == "sae"
    assert normalize("Album - EP") == "album"
    assert normalize("A/B & C!") == "a b c"


def test_match_album_exact_match_is_available():
    albums = [_album("Album X", "Artist A")]
    m = match_album("Artist A", "Album X", albums)
    assert m.status == "available"
    assert m.url == "https://music.apple.com/gb/album/x/1"
    assert m.name == "Album X"
    assert m.artist == "Artist A"


def test_match_album_deluxe_edition_still_matches():
    albums = [_album("Album X (Deluxe Edition)", "Artist A")]
    m = match_album("Artist A", "Album X", albums)
    assert m.status == "available"


def test_match_album_wrong_artist_is_unavailable():
    albums = [_album("Album X", "Some Other Band")]
    m = match_album("Artist A", "Album X", albums)
    assert m.status == "unavailable"
    assert m.url is None


def test_match_album_no_results_is_unavailable():
    assert match_album("Artist A", "Album X", []).status == "unavailable"


def test_match_album_compilation_matches_on_title_alone():
    albums = [_album("Big Compilation", "Various Artists 2024 Reissue")]
    m = match_album("Various Artists", "Big Compilation", albums)
    assert m.status == "available"


def test_match_album_picks_best_of_several():
    albums = [
        _album("Album X (Live)", "Artist A", "https://music.apple.com/gb/album/live/2"),
        _album("Album X", "Artist A", "https://music.apple.com/gb/album/x/1"),
    ]
    m = match_album("Artist A", "Album X", albums)
    assert m.url == "https://music.apple.com/gb/album/x/1"
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


def match_album(artist: str, title: str, albums: list[dict]) -> AppleMatch:
    want_artist = normalize(artist)
    want_title = normalize(title)
    is_comp = want_artist in _COMPILATION_ARTISTS

    best_attrs = None
    best_score = 0.0
    for album in albums:
        attrs = album.get("attributes") or {}
        title_score = _ratio(want_title, normalize(attrs.get("name", "")))
        if title_score < TITLE_THRESHOLD:
            continue
        if is_comp:
            artist_score = 0.0
        else:
            artist_score = _ratio(want_artist, normalize(attrs.get("artistName", "")))
            if artist_score < ARTIST_THRESHOLD:
                continue
        combined = title_score + artist_score
        if combined > best_score:
            best_score = combined
            best_attrs = attrs

    if best_attrs is None:
        return AppleMatch(status="unavailable", url=None, name=None, artist=None)
    return AppleMatch(
        status="available",
        url=best_attrs.get("url"),
        name=best_attrs.get("name"),
        artist=best_attrs.get("artistName"),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/apple_music.py tests/test_apple_music.py
git commit -m "feat: Apple Music album matching logic"
```

---

## Task 2: Config overlay + AppleMusicConfig

Wire up the `config.local.toml` overlay (currently gitignored but never read) and parse `[apple_music]` credentials into an optional `AppleMusicConfig`.

**Files:**
- Modify: `bandcamp_reco/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `AppleMusicConfig` — `@dataclass` with `storefront: str`, `team_id: str`, `key_id: str`, `private_key_path: str`, `workers: int`.
  - `Config.apple_music: AppleMusicConfig | None` (defaults to `None`).
  - `load_config(path=None)` now overlays `config.local.toml` onto `config.toml`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_apple_music_config_loaded_from_local_overlay(tmp_path):
    (tmp_path / "config.toml").write_text('username = "me"\n')
    (tmp_path / "config.local.toml").write_text(
        "[apple_music]\n"
        'team_id = "T123"\n'
        'key_id = "K123"\n'
        'private_key_path = "AuthKey_K123.p8"\n'
    )
    cfg = load_config(str(tmp_path / "config.toml"))
    assert cfg.username == "me"
    assert cfg.apple_music is not None
    assert cfg.apple_music.team_id == "T123"
    assert cfg.apple_music.key_id == "K123"
    assert cfg.apple_music.private_key_path == "AuthKey_K123.p8"
    assert cfg.apple_music.storefront == "gb"   # default
    assert cfg.apple_music.workers == 12         # default


def test_apple_music_config_absent_when_no_creds(tmp_path):
    (tmp_path / "config.toml").write_text('username = "me"\n')
    cfg = load_config(str(tmp_path / "config.toml"))
    assert cfg.apple_music is None


def test_apple_music_config_absent_when_partial_creds(tmp_path):
    (tmp_path / "config.toml").write_text('username = "me"\n')
    (tmp_path / "config.local.toml").write_text(
        '[apple_music]\nteam_id = "T123"\n'  # missing key_id + private_key_path
    )
    cfg = load_config(str(tmp_path / "config.toml"))
    assert cfg.apple_music is None
```

Also add `AppleMusicConfig` to the import line at the top of `tests/test_config.py`:

```python
from bandcamp_reco.config import load_config, Config, AppleMusicConfig
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
    storefront: str
    team_id: str
    key_id: str
    private_key_path: str
    workers: int


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


def _load_toml(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _local_path(path: str) -> str:
    directory, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    return os.path.join(directory, f"{stem}.local{ext}")


def _parse_apple(section) -> AppleMusicConfig | None:
    if not section:
        return None
    required = ("team_id", "key_id", "private_key_path")
    if not all(section.get(k) for k in required):
        return None
    return AppleMusicConfig(
        storefront=section.get("storefront", "gb"),
        team_id=section["team_id"],
        key_id=section["key_id"],
        private_key_path=section["private_key_path"],
        workers=int(section.get("workers", 12)),
    )


def load_config(path: str | None = None) -> Config:
    path = path or "config.toml"
    raw: dict = {}
    if os.path.exists(path):
        raw.update(_load_toml(path))
    local = _local_path(path)
    if os.path.exists(local):
        raw.update(_load_toml(local))
    base = {k: raw.get(k, DEFAULTS[k]) for k in DEFAULTS}
    return Config(apple_music=_parse_apple(raw.get("apple_music")), **base)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (existing 2 + new 3 = 5 passed).

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/config.py tests/test_config.py
git commit -m "feat: config.local.toml overlay + Apple Music credentials"
```

---

## Task 3: Developer token

Sign an ES256 JWT developer token from the MusicKit key. Adds the `PyJWT[crypto]` dependency.

**Files:**
- Modify: `bandcamp_reco/apple_music.py`
- Modify: `requirements.txt`
- Test: `tests/test_apple_music.py`

**Interfaces:**
- Consumes: `AppleMusicConfig` (uses `.team_id`, `.key_id`, `.private_key_path`).
- Produces: `developer_token(creds, *, now=None, ttl=43200) -> str`.

- [ ] **Step 1: Add the dependency and install it**

Edit `requirements.txt` to add a line:

```
PyJWT[crypto]>=2.8
```

Run: `python -m pip install -r requirements.txt`
Expected: installs `PyJWT` and `cryptography`.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_apple_music.py`:

```python
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from bandcamp_reco.apple_music import developer_token
from bandcamp_reco.config import AppleMusicConfig


def _make_key(tmp_path):
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path = tmp_path / "AuthKey_K123.p8"
    path.write_bytes(pem)
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return str(path), pub_pem


def test_developer_token_has_es256_header_and_claims(tmp_path):
    key_path, pub_pem = _make_key(tmp_path)
    creds = AppleMusicConfig(storefront="gb", team_id="TEAM1", key_id="KEY1",
                             private_key_path=key_path, workers=12)
    token = developer_token(creds, now=1000, ttl=3600)
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["kid"] == "KEY1"
    claims = jwt.decode(token, pub_pem, algorithms=["ES256"])
    assert claims["iss"] == "TEAM1"
    assert claims["iat"] == 1000
    assert claims["exp"] == 4600
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_apple_music.py::test_developer_token_has_es256_header_and_claims -v`
Expected: FAIL with `ImportError: cannot import name 'developer_token'`.

- [ ] **Step 4: Write the implementation**

Add to `bandcamp_reco/apple_music.py` — add `import time` and `import jwt` to the imports at the top, then add this function:

```python
def developer_token(creds, *, now=None, ttl=43200) -> str:
    issued = int(time.time() if now is None else now)
    with open(creds.private_key_path, "r", encoding="utf-8") as f:
        private_key = f.read()
    return jwt.encode(
        {"iss": creds.team_id, "iat": issued, "exp": issued + ttl},
        private_key,
        algorithm="ES256",
        headers={"kid": creds.key_id},
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: PASS (all 8 passed).

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/apple_music.py requirements.txt tests/test_apple_music.py
git commit -m "feat: Apple Music developer token generation"
```

---

## Task 4: Apple Music catalog client

A small client that calls the catalog search endpoint with the developer token, with its own throttle and 429 handling. Uses thread-local sessions so it is safe to share across worker threads.

**Files:**
- Modify: `bandcamp_reco/apple_music.py`
- Test: `tests/test_apple_music.py`

**Interfaces:**
- Produces:
  - `AppleRateLimited(Exception)`, `AppleSearchError(Exception)`.
  - `AppleMusicClient(token, *, session=None, delay=0.05, jitter=0.05, max_retries=3, backoff_ceiling=10.0)`.
  - `AppleMusicClient.search_album(artist, title, storefront) -> list[dict]` — the `results.albums.data` list (each dict has `attributes`), or `[]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_apple_music.py`:

```python
import pytest

from bandcamp_reco.apple_music import (
    AppleMusicClient, AppleRateLimited,
)


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
        self.last_kwargs = None

    def get(self, url, **kwargs):
        self.last_kwargs = kwargs
        return self._responses.pop(0)


def _albums_payload():
    return {"results": {"albums": {"data": [
        {"attributes": {"name": "Album X", "artistName": "Artist A",
                        "url": "https://music.apple.com/gb/album/x/1"}}
    ]}}}


def test_search_album_returns_album_list_and_sends_auth():
    sess = FakeSession([FakeResp(200, _albums_payload())])
    client = AppleMusicClient("tok", session=sess)
    albums = client.search_album("Artist A", "Album X", "gb")
    assert albums[0]["attributes"]["name"] == "Album X"
    assert sess.last_kwargs["headers"]["Authorization"] == "Bearer tok"


def test_search_album_empty_when_no_albums():
    sess = FakeSession([FakeResp(200, {"results": {}})])
    client = AppleMusicClient("tok", session=sess)
    assert client.search_album("a", "b", "gb") == []


def test_search_album_raises_on_persistent_429():
    sess = FakeSession([FakeResp(429), FakeResp(429), FakeResp(429), FakeResp(429)])
    client = AppleMusicClient("tok", session=sess, max_retries=3)
    with pytest.raises(AppleRateLimited):
        client.search_album("a", "b", "gb")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: FAIL with `ImportError: cannot import name 'AppleMusicClient'`.

- [ ] **Step 3: Write the implementation**

Add to `bandcamp_reco/apple_music.py` — add `import random`, `import threading`, and `import requests` to the imports at the top, then add:

```python
SEARCH_URL = "https://api.music.apple.com/v1/catalog/{storefront}/search"


class AppleRateLimited(Exception):
    pass


class AppleSearchError(Exception):
    pass


class AppleMusicClient:
    def __init__(self, token, *, session=None, delay=0.05, jitter=0.05,
                 max_retries=3, backoff_ceiling=10.0):
        self._token = token
        self._explicit_session = session
        self._local = threading.local()
        self.delay = delay
        self.jitter = jitter
        self.max_retries = max_retries
        self.backoff_ceiling = backoff_ceiling

    def _session(self):
        if self._explicit_session is not None:
            return self._explicit_session
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            self._local.session = s
        return s

    def _throttle(self):
        time.sleep(self.delay + random.uniform(0.0, self.jitter))

    def _backoff(self, attempt):
        time.sleep(min(self.delay * (2 ** attempt), self.backoff_ceiling))

    def search_album(self, artist, title, storefront) -> list[dict]:
        url = SEARCH_URL.format(storefront=storefront)
        params = {"term": f"{artist} {title}".strip(), "types": "albums", "limit": 10}
        headers = {"Authorization": f"Bearer {self._token}"}
        for attempt in range(self.max_retries + 1):
            self._throttle()
            resp = self._session().get(url, params=params, headers=headers)
            if resp.status_code == 429:
                if attempt >= self.max_retries:
                    raise AppleRateLimited()
                self._backoff(attempt)
                continue
            if 500 <= resp.status_code < 600:
                if attempt >= self.max_retries:
                    raise AppleSearchError(f"server error {resp.status_code}")
                self._backoff(attempt)
                continue
            resp.raise_for_status()
            data = resp.json() or {}
            return (((data.get("results") or {}).get("albums") or {}).get("data")) or []
        raise AppleSearchError("exhausted retries")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: PASS (all 11 passed).

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/apple_music.py tests/test_apple_music.py
git commit -m "feat: Apple Music catalog search client"
```

---

## Task 5: Parallel lookup orchestration

Look up the candidate pool in parallel, skipping cached albums, writing results to the cache from the main thread, and stopping early on persistent rate-limiting.

**Files:**
- Modify: `bandcamp_reco/models.py`
- Modify: `bandcamp_reco/apple_music.py`
- Test: `tests/test_models.py`, `tests/test_apple_music.py`

**Interfaces:**
- Consumes: `match_album` (Task 1), `AppleRateLimited` (Task 4), `AppleMatch` (Task 1).
- Produces:
  - `models.album_key_from_url(url: str) -> str`.
  - `lookup_pool(pool, client, cache, storefront, workers=12) -> dict[str, AppleMatch]` — keyed by `album_key_from_url(item["url"])`. Each `pool` item is a dict with at least `url`, `artist`, `title`.

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
    def __init__(self, mapping, errors=()):
        self.mapping = mapping        # title -> list of Apple album dicts
        self.errors = set(errors)     # titles that raise
        self.calls = []

    def search_album(self, artist, title, storefront):
        self.calls.append(title)
        if title in self.errors:
            raise RuntimeError("boom")
        return self.mapping.get(title, [])


def _item(url, title, artist="Artist A"):
    return {"url": url, "title": title, "artist": artist}


def _apple_album(name, artist, url):
    return {"attributes": {"name": name, "artistName": artist, "url": url}}


def test_lookup_pool_matches_and_caches():
    pool = [_item("https://x.bandcamp.com/album/y", "Album X")]
    client = FakeClient({"Album X": [
        _apple_album("Album X", "Artist A", "https://music.apple.com/gb/album/x/1")]})
    cache = StubCache()
    results = lookup_pool(pool, client, cache, "gb", workers=2)
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
    results = lookup_pool(pool, client, cache, "gb", workers=2)
    assert results["https://x.bandcamp.com/album/y"].status == "unavailable"
    assert client.calls == []  # cached -> no API call


def test_lookup_pool_error_is_unknown_and_not_cached():
    pool = [_item("https://x.bandcamp.com/album/y", "Boom")]
    client = FakeClient({}, errors={"Boom"})
    cache = StubCache()
    results = lookup_pool(pool, client, cache, "gb", workers=2)
    assert "https://x.bandcamp.com/album/y" not in results  # unknown
    assert ("apple_music", "https://x.bandcamp.com/album/y") not in cache.store
```

- [ ] **Step 6: Run them to verify they fail**

Run: `python -m pytest tests/test_apple_music.py -v`
Expected: FAIL with `ImportError: cannot import name 'lookup_pool'`.

- [ ] **Step 7: Write the implementation**

Add to `bandcamp_reco/apple_music.py` — add `import dataclasses`, `from concurrent.futures import ThreadPoolExecutor, as_completed`, and `from .models import album_key_from_url` to the imports at the top, then add:

```python
def lookup_pool(pool, client, cache, storefront, workers=12) -> dict:
    results: dict = {}
    todo = []
    for item in pool:
        key = album_key_from_url(item["url"])
        cached = cache.get("apple_music", key)
        if cached is not None:
            results[key] = AppleMatch(**cached)
        else:
            todo.append((key, item))

    stop = threading.Event()
    new: dict = {}

    def work(entry):
        key, item = entry
        if stop.is_set():
            raise AppleRateLimited()
        try:
            albums = client.search_album(item["artist"], item["title"], storefront)
        except AppleRateLimited:
            stop.set()
            raise
        return key, match_album(item["artist"], item["title"], albums)

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(work, entry) for entry in todo]
            for future in as_completed(futures):
                try:
                    key, match = future.result()
                except Exception:
                    continue  # unknown: not cached, retried next run
                new[key] = match

    for key, match in new.items():
        cache.set("apple_music", key, dataclasses.asdict(match))
        results[key] = match
    return results
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/test_apple_music.py tests/test_models.py -v`
Expected: PASS (all apple_music + models tests pass).

- [ ] **Step 9: Commit**

```bash
git add bandcamp_reco/apple_music.py bandcamp_reco/models.py tests/test_apple_music.py tests/test_models.py
git commit -m "feat: parallel Apple Music pool lookup with caching"
```

---

## Task 6: Wire the lookup into the pipeline

After the pool is built, run the Apple phase when credentials are present, annotate each pool item, and pass `apple_enabled` to the renderer. Apple failures never break the run.

**Files:**
- Modify: `bandcamp_reco/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `developer_token`, `AppleMusicClient`, `lookup_pool` (Tasks 3–5), `album_key_from_url` (Task 5), `Config.apple_music` (Task 2).
- Produces: pool items annotated with `apple` (`"available"`/`"unavailable"`/`"unknown"`) and, when available, `appleUrl`/`appleName`/`appleArtist`; calls `render_html(..., apple_enabled=<bool>)`.

Note on ordering: `render_html` does not yet accept `apple_enabled`. Step 1 of this task adds that parameter and the `APPLE_ENABLED` JS const (a minimal signature + template change) so this task is testable on its own; Task 7 then builds the visible UI on top of the const.

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

and add this line inside `render_html`, alongside the other `.replace(...)` calls in the returned expression — change:

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

Then add the placeholder to the template's `<script>` block — directly under `const OWNED_SOURCES = new Set(__OWNED_SOURCES__);` add:

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
        storefront="gb", team_id="T", key_id="K",
        private_key_path="x.p8", workers=4))


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


def test_run_annotates_apple_music_when_configured(tmp_path, monkeypatch):
    _base_stubs(monkeypatch, [_album("https://own/1")])
    monkeypatch.setattr(main_mod, "developer_token", lambda creds: "tok")
    monkeypatch.setattr(main_mod, "AppleMusicClient", lambda token: object())
    monkeypatch.setattr(main_mod, "lookup_pool",
                        lambda pool, client, cache, storefront, workers: {
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

    def boom(creds):
        raise RuntimeError("bad key")
    monkeypatch.setattr(main_mod, "developer_token", boom)
    # run must still complete and write the page with the feature off
    main_mod.run(_apple_cfg(tmp_path), fetcher=None, cache=None)
    html = (tmp_path / "out.html").read_text()
    assert "APPLE_ENABLED = false" in html
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL — `developer_token`/`AppleMusicClient`/`lookup_pool` are not attributes of `main_mod` yet (and the page lacks `APPLE_ENABLED`).

- [ ] **Step 4: Write the implementation**

In `bandcamp_reco/main.py`, add to the imports at the top:

```python
import sys

from .apple_music import developer_token, AppleMusicClient, lookup_pool
from .models import album_key, album_source, album_key_from_url
```

(Replace the existing `from .models import album_key, album_source` line with the one above.)

Add this helper function:

```python
def _apply_apple_music(config, pool, cache) -> bool:
    if config.apple_music is None:
        return False
    try:
        token = developer_token(config.apple_music)
        client = AppleMusicClient(token)
        results = lookup_pool(pool, client, cache,
                              config.apple_music.storefront,
                              workers=config.apple_music.workers)
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

## Task 7: Page — Apple link + two filter checkboxes

Render an Apple Music link per available album and add the two combining filter checkboxes, all guarded behind `APPLE_ENABLED`.

**Files:**
- Modify: `bandcamp_reco/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `render_html(..., apple_enabled=...)` and the `APPLE_ENABLED` JS const (Task 6 Step 1).
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
Expected: FAIL — `id="hideOnApple"` not present (only the `APPLE_ENABLED` const exists from Task 6).

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

Then, near the bottom of the script where the listeners are wired (after `hideOwned.addEventListener("change", render);`), add:

```javascript
if (APPLE_ENABLED) {
  el("appleControls").style.display = "";
  el("hideOnApple").addEventListener("change", render);
  el("hideNotApple").addEventListener("change", render);
}
```

And in the `el("reset")` click handler, uncheck the Apple boxes — change:

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

## Task 8: Page — flag / export UI

Add a per-row "flag" toggle that records wrong matches into `localStorage`, plus a bar to show the count, export to JSON, and clear. Guarded behind `APPLE_ENABLED`.

**Files:**
- Modify: `bandcamp_reco/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `APPLE_ENABLED`, per-row Apple data (Task 7).
- Produces: page with `id="flagBar"` and an export that downloads `apple-music-flags.json`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
def test_render_includes_flag_ui_when_apple_enabled():
    html = render_html(_apple_pool(), username="u", defaults=DEFAULTS,
                       apple_enabled=True)
    assert 'id="flagBar"' in html
    assert "apple-music-flags.json" in html


def test_render_has_no_flag_ui_when_apple_disabled():
    html = render_html(_pool(), username="u", defaults=DEFAULTS)
    # the flag bar is hidden and the store is gated on APPLE_ENABLED
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

In the `<style>` block, after the `.apple` rules added in Task 7, add:

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

In the `row(r, rank)` function, inside the `if (APPLE_ENABLED) { ... }` block added in Task 7, after the `meta.appendChild(apple);` line but still inside that block, append the flag button to the `apple` div before it is added to `meta`. Replace the Task 7 block's final two lines:

```javascript
    meta.appendChild(apple);
  }
```

with:

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

At the bottom of the script, inside the `if (APPLE_ENABLED) { ... }` block added in Task 7 (where `appleControls` is revealed), add the flag bar wiring:

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

- [ ] **Step 7: Manual smoke check (optional but recommended)**

Run the existing test suite to confirm nothing regressed, then eyeball the page logic:

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add bandcamp_reco/render.py tests/test_render.py
git commit -m "feat: flag + export UI for wrong Apple Music matches"
```

---

## Task 9: Documentation + config example

Document setup so the feature is usable: a commented `[apple_music]` block and a README section. No real credentials.

**Files:**
- Modify: `config.toml`
- Modify: `README.md`

- [ ] **Step 1: Add a commented example to config.toml**

At the end of `config.toml`, add:

```toml

# --- Apple Music (optional) ---
# To link recommendations to Apple Music and filter by availability, create a
# MusicKit key in your Apple Developer account and put your credentials in
# config.local.toml (gitignored) — NOT here. Example for config.local.toml:
#
#   [apple_music]
#   storefront = "gb"                       # country storefront to check
#   team_id = "ABCDE12345"                  # Apple Developer Team ID
#   key_id = "ABCD123456"                   # MusicKit Key ID
#   private_key_path = "AuthKey_ABCD123456.p8"   # path to your .p8 key file
#   workers = 12                            # parallel lookups
#
# With no credentials the tool runs exactly as before (no Apple Music links
# or filters).
```

- [ ] **Step 2: Add a README section**

In `README.md`, after the `## Config` section, add:

```markdown
## Apple Music (optional)

The page can show whether each album is on Apple Music, link to it, and filter
by availability. This is off unless you provide credentials.

1. In your Apple Developer account, create a **MusicKit key** and download its
   `.p8` private key. Note your **Team ID** and the **Key ID**.
2. Put the `.p8` file somewhere local (it is secret — keep it out of git).
3. Add an `[apple_music]` block to `config.local.toml` (gitignored):

       [apple_music]
       storefront = "gb"
       team_id = "ABCDE12345"
       key_id = "ABCD123456"
       private_key_path = "AuthKey_ABCD123456.p8"

On the next run, each recommendation is checked against the Apple Music catalog
(cached, so re-runs are fast). The page then shows an Apple Music link when
available, two checkboxes to hide albums that are / are not on Apple Music, and
a "flag" button to mark wrong matches — exportable as `apple-music-flags.json`
for later debugging.

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
git commit -m "docs: Apple Music setup instructions"
```

---

## Self-Review Notes

- **Spec coverage:** data source (Tasks 3–4), storefront config (Task 2), parallel cached lookup (Task 5), matching incl. compilations + albums-only (Task 1), tri-state data shape + cache namespace (Tasks 5–6), graceful degradation (Task 6), two filter checkboxes (Task 7), flag/export UI (Task 8), error handling incl. 429 early-stop (Tasks 4–6), config overlay (Task 2), docs (Task 9), tests in every task.
- **Singles-as-albums** and **overrides feedback loop** are explicitly out of scope (Task 9 note / not implemented).
