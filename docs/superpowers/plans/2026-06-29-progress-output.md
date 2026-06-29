# Terminal progress output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show what the recommender script is doing and how far along it is, via phase headers and tqdm progress bars over the long loop phases.

**Architecture:** A thin `bandcamp_reco/progress.py` wraps tqdm behind a `Reporter` (phase headers + a `bar()` context manager). The three functions that own loops gain one optional `reporter` parameter defaulting to a silent no-op, and `main` builds the real reporter, threads it down, and drives the crawl loop + phase headers. Presentation-only and additive — the default no-op keeps every existing test green.

**Tech Stack:** Python 3.11+, pytest, tqdm (new dependency), stdlib (`sys`, `contextlib`).

## Global Constraints

- **Additive, presentation-only.** No recommendation logic and no output file changes. With progress disabled the script behaves exactly as today. Every existing test must stay green.
- **New dependency:** `tqdm>=4.0` — the only new dependency.
- **Progress goes to stderr; the final `Wrote recommendations to …` line stays on stdout.**
- **Default reporter is a silent no-op** (`NULL_REPORTER`). Bars auto-disable when not a TTY (tqdm `disable=None`). A `--quiet` flag forces everything off.
- **Phase header format:** `→ <label>` printed to stderr.
- **Fan-collections bar counts fans actually fetched against `max_fans`** (not raw usernames considered).
- **The Apple Music bar appears only when Apple Music is enabled.**
- **Use the project venv** for all commands: `.venv/bin/python`.

---

### Task 1: The `progress.py` reporter module

**Files:**
- Create: `bandcamp_reco/progress.py`
- Create: `tests/test_progress.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `tqdm`.
- Produces:
  - `class Reporter` with `__init__(self, enabled=True)`, `phase(self, label)`, and `bar(self, total, label)` (a context manager yielding a handle with `.update(n=1)`).
  - `NULL_REPORTER` — a module-level `Reporter(enabled=False)` used as the default for loop functions.
  - `make_reporter(quiet: bool) -> Reporter` — returns `Reporter(enabled=not quiet)`.

- [ ] **Step 1: Add the dependency and install it**

Append to `requirements.txt`:

```
tqdm>=4.0
```

Then install into the project venv:

Run: `.venv/bin/python -m pip install "tqdm>=4.0"`
Expected: tqdm installs (or "Requirement already satisfied").

- [ ] **Step 2: Write the failing tests**

Create `tests/test_progress.py`:

```python
from bandcamp_reco.progress import Reporter, NULL_REPORTER, make_reporter


def test_disabled_reporter_is_silent(capsys):
    r = Reporter(enabled=False)
    r.phase("Reading your collection")
    with r.bar(10, "Crawling") as bar:
        bar.update()
        bar.update(2)
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""


def test_enabled_phase_writes_header_to_stderr(capsys):
    r = Reporter(enabled=True)
    r.phase("Crawling supporters")
    out, err = capsys.readouterr()
    assert "Crawling supporters" in err
    assert out == ""   # progress never goes to stdout


def test_enabled_bar_is_usable_and_does_not_raise(capsys):
    r = Reporter(enabled=True)
    with r.bar(3, "Reading fan collections") as bar:
        bar.update()
        bar.update()
        bar.update()
    # Under pytest stderr is not a TTY, so tqdm disable=None suppresses the bar;
    # we assert the seam works without raising and never writes stdout.
    out, _ = capsys.readouterr()
    assert out == ""


def test_null_reporter_is_disabled():
    assert NULL_REPORTER.enabled is False
    with NULL_REPORTER.bar(5, "x") as bar:
        bar.update()  # no-op, must not raise


def test_make_reporter_quiet_flag():
    assert make_reporter(quiet=True).enabled is False
    assert make_reporter(quiet=False).enabled is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_progress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bandcamp_reco.progress'`

- [ ] **Step 4: Implement `progress.py`**

Create `bandcamp_reco/progress.py`:

```python
import sys
from contextlib import contextmanager

from tqdm import tqdm


class _NullBar:
    """A no-op progress handle used when reporting is disabled."""

    def update(self, n=1):
        pass


class Reporter:
    """Presents pipeline progress. Wraps tqdm so nothing else imports it.

    `enabled=False` makes every method a no-op (the default for library
    functions, so they stay silent and testable). Bars additionally auto-
    disable when stderr is not a TTY (tqdm `disable=None`), so pipes and CI
    logs stay clean even when enabled."""

    def __init__(self, enabled=True):
        self.enabled = enabled

    def phase(self, label):
        if self.enabled:
            print(f"→ {label}", file=sys.stderr, flush=True)

    @contextmanager
    def bar(self, total, label):
        if not self.enabled:
            yield _NullBar()
            return
        bar = tqdm(total=total, desc=label, file=sys.stderr, disable=None)
        try:
            yield bar
        finally:
            bar.close()


NULL_REPORTER = Reporter(enabled=False)


def make_reporter(quiet):
    return Reporter(enabled=not quiet)
```

(`→` is the `→` arrow; the enabled tqdm object already exposes `.update(n=1)`, matching `_NullBar`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_progress.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/progress.py tests/test_progress.py requirements.txt
git commit -m "feat: progress.py reporter (tqdm wrapper) + tqdm dependency"
```

---

### Task 2: Fan-collections progress bar

**Files:**
- Modify: `bandcamp_reco/fans.py`
- Test: `tests/test_fans.py`

**Interfaces:**
- Consumes: `Reporter` and `NULL_REPORTER` from `bandcamp_reco.progress`.
- Produces: `get_fan_collections(usernames, fetcher, cache, max_fans, max_albums_per_fan, reporter=NULL_REPORTER)` — unchanged return value (`{username: [Album]}`); now advances a bar (`total=max_fans`) once per fan actually fetched.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fans.py`:

```python
from bandcamp_reco.progress import Reporter


def test_get_fan_collections_accepts_reporter(monkeypatch):
    def fake_get_collection(username, fetcher, cache, max_items=None):
        return [_album(f"https://x/{username}")]

    monkeypatch.setattr(fans, "get_collection", fake_get_collection)
    result = fans.get_fan_collections(
        ["a", "b"], fetcher=None, cache=None,
        max_fans=10, max_albums_per_fan=100, reporter=Reporter(enabled=True),
    )
    assert set(result.keys()) == {"a", "b"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fans.py::test_get_fan_collections_accepts_reporter -v`
Expected: FAIL — `TypeError: get_fan_collections() got an unexpected keyword argument 'reporter'`

- [ ] **Step 3: Implement the bar**

Replace the entire contents of `bandcamp_reco/fans.py`:

```python
from .collection import get_collection
from .fetch import CircuitBreakerTripped
from .progress import NULL_REPORTER


def get_fan_collections(usernames, fetcher, cache, max_fans, max_albums_per_fan,
                        reporter=NULL_REPORTER):
    result = {}
    seen = set()
    with reporter.bar(max_fans, "Reading fan collections") as bar:
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
            bar.update()
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_fans.py -v`
Expected: PASS — the new test plus all three existing fan tests (dedup/cap, skip-erroring, circuit-breaker) stay green.

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/fans.py tests/test_fans.py
git commit -m "feat: progress bar for fan-collection reads (counts fetched fans)"
```

---

### Task 3: Apple Music lookup progress bar

**Files:**
- Modify: `bandcamp_reco/apple_music.py`
- Test: `tests/test_apple_music.py`

**Interfaces:**
- Consumes: `NULL_REPORTER` from `bandcamp_reco.progress`; `Reporter` (in tests).
- Produces: `lookup_pool(pool, client, cache, country, reporter=NULL_REPORTER) -> dict` — unchanged return value; now advances a bar (`total=len(pool)`) once per pool item reached.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_apple_music.py` (reuses the existing `FakeClient`, `StubCache`, `_item`, `_itunes_result` helpers):

```python
from bandcamp_reco.progress import Reporter


def test_lookup_pool_accepts_reporter():
    pool = [_item("https://x.bandcamp.com/album/y", "Album X")]
    client = FakeClient({"Album X": [
        _itunes_result("Album X", "Artist A", "https://music.apple.com/gb/album/x/1")]})
    cache = StubCache()
    results = lookup_pool(pool, client, cache, "gb", reporter=Reporter(enabled=True))
    assert results["https://x.bandcamp.com/album/y"].status == "available"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_apple_music.py::test_lookup_pool_accepts_reporter -v`
Expected: FAIL — `TypeError: lookup_pool() got an unexpected keyword argument 'reporter'`

- [ ] **Step 3: Implement the bar**

In `bandcamp_reco/apple_music.py`, add the import near the top (next to `from .models import album_key_from_url`):

```python
from .progress import NULL_REPORTER
```

Then replace the entire `lookup_pool` function:

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

with:

```python
def lookup_pool(pool, client, cache, country, reporter=NULL_REPORTER) -> dict:
    results: dict = {}
    with reporter.bar(len(pool), "Checking Apple Music") as bar:
        for item in pool:
            bar.update()
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

(`bar.update()` at the top of the loop counts each item reached, so a rate-limit `break` simply leaves the bar at a partial count.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_apple_music.py -v`
Expected: PASS — the new test plus all existing `lookup_pool` tests (match/cache, skip-cached, error-unknown, stop-on-rate-limit) stay green.

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/apple_music.py tests/test_apple_music.py
git commit -m "feat: progress bar for Apple Music lookups"
```

---

### Task 4: Wire phases + `--quiet` into the pipeline

**Files:**
- Modify: `bandcamp_reco/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `make_reporter`, `NULL_REPORTER` from `bandcamp_reco.progress`; the `reporter=`-accepting `get_fan_collections` (Task 2) and `lookup_pool` (Task 3); `Reporter` (in tests).
- Produces: `run(config, fetcher, cache, limit=None, reporter=NULL_REPORTER)` emits phase headers + a supporter-crawl bar and threads the reporter to `get_fan_collections` and `_apply_apple_music`. `_apply_apple_music(config, pool, cache, reporter=NULL_REPORTER)`. `main` adds a `--quiet` flag and builds the reporter via `make_reporter`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main.py`:

```python
from bandcamp_reco.progress import Reporter


def test_run_emits_phase_headers_with_enabled_reporter(tmp_path, monkeypatch, capsys):
    _base_stubs(monkeypatch, [_album("https://own/1")])
    main_mod.run(_cfg(tmp_path), fetcher=None, cache=None,
                 reporter=Reporter(enabled=True))
    err = capsys.readouterr().err
    assert "Reading your collection" in err
    assert "Scoring recommendations" in err
    assert "Writing page" in err


def test_run_silent_with_default_reporter(tmp_path, monkeypatch, capsys):
    _base_stubs(monkeypatch, [_album("https://own/1")])
    main_mod.run(_cfg(tmp_path), fetcher=None, cache=None)
    err = capsys.readouterr().err
    assert "→" not in err  # no phase-header arrows
    assert "Reading your collection" not in err


def _fake_pipeline_for_main(monkeypatch, tmp_path, captured):
    def fake_run(config, fetcher, cache, limit=None, reporter=None):
        captured["reporter"] = reporter
        return []
    monkeypatch.setattr(main_mod, "run", fake_run)
    monkeypatch.setattr(main_mod, "load_config", lambda path: _cfg(tmp_path))
    monkeypatch.setattr(main_mod, "Cache",
                        lambda path: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(main_mod, "Fetcher", lambda delay: object())


def test_main_quiet_passes_disabled_reporter(tmp_path, monkeypatch):
    captured = {}
    _fake_pipeline_for_main(monkeypatch, tmp_path, captured)
    assert main_mod.main(["--quiet"]) == 0
    assert captured["reporter"].enabled is False


def test_main_default_passes_enabled_reporter(tmp_path, monkeypatch):
    captured = {}
    _fake_pipeline_for_main(monkeypatch, tmp_path, captured)
    assert main_mod.main([]) == 0
    assert captured["reporter"].enabled is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_main.py::test_run_emits_phase_headers_with_enabled_reporter tests/test_main.py::test_main_quiet_passes_disabled_reporter -v`
Expected: FAIL — `run()` rejects `reporter=` (TypeError) and `main(["--quiet"])` errors on the unknown flag (SystemExit).

- [ ] **Step 3: Add the progress import to main.py**

In `bandcamp_reco/main.py`, after the line `from .render import render_html, write_html`, add:

```python
from .progress import make_reporter, NULL_REPORTER
```

- [ ] **Step 4: Thread the reporter through `_apply_apple_music`**

Replace:

```python
def _apply_apple_music(config, pool, cache) -> bool:
    if config.apple_music is None:
        return False
    try:
        client = AppleMusicClient(delay=config.apple_music.request_delay)
        results = lookup_pool(pool, client, cache, config.apple_music.country)
```

with:

```python
def _apply_apple_music(config, pool, cache, reporter=NULL_REPORTER) -> bool:
    if config.apple_music is None:
        return False
    try:
        client = AppleMusicClient(delay=config.apple_music.request_delay)
        results = lookup_pool(pool, client, cache, config.apple_music.country,
                              reporter=reporter)
```

- [ ] **Step 5: Add the reporter param, phase headers, and crawl bar to `run`**

Replace:

```python
def run(config, fetcher, cache, limit=None):
    try:
        owned = get_collection(config.username, fetcher, cache)
    except CircuitBreakerTripped:
        owned = []
```

with:

```python
def run(config, fetcher, cache, limit=None, reporter=NULL_REPORTER):
    reporter.phase("Reading your collection")
    try:
        owned = get_collection(config.username, fetcher, cache)
    except CircuitBreakerTripped:
        owned = []
```

Replace the supporter-crawl loop:

```python
    seed_supporters: dict[str, list[str]] = {}
    for album in crawl_albums:
        try:
            sup = get_supporters(album, fetcher, cache,
                                 limit=config.supporters_per_album)
        except CircuitBreakerTripped:
            break
        except Exception:
            continue
        seed_supporters[album_key(album)] = [u for u in sup if u != config.username]
```

with:

```python
    seed_supporters: dict[str, list[str]] = {}
    with reporter.bar(len(crawl_albums), "Crawling supporters") as bar:
        for album in crawl_albums:
            try:
                sup = get_supporters(album, fetcher, cache,
                                     limit=config.supporters_per_album)
            except CircuitBreakerTripped:
                break
            except Exception:
                continue
            seed_supporters[album_key(album)] = [u for u in sup if u != config.username]
            bar.update()
```

Replace the `get_fan_collections` call:

```python
    fan_albums = get_fan_collections(
        supporter_usernames, fetcher, cache,
        max_fans=config.max_fans,
        max_albums_per_fan=config.max_albums_per_fan,
    )
```

with:

```python
    fan_albums = get_fan_collections(
        supporter_usernames, fetcher, cache,
        max_fans=config.max_fans,
        max_albums_per_fan=config.max_albums_per_fan,
        reporter=reporter,
    )
```

Add the scoring phase header — replace:

```python
    recs = score_candidates(
        owned_keys, fan_albums, top_n=config.top_n,
        affinity_cap=config.affinity_cap,
        max_per_source=config.max_per_source,
    )
```

with:

```python
    reporter.phase("Scoring recommendations")
    recs = score_candidates(
        owned_keys, fan_albums, top_n=config.top_n,
        affinity_cap=config.affinity_cap,
        max_per_source=config.max_per_source,
    )
```

Thread the reporter into the Apple call — replace:

```python
    apple_enabled = _apply_apple_music(config, pool + list(albums.values()), cache)
```

with:

```python
    apple_enabled = _apply_apple_music(config, pool + list(albums.values()), cache,
                                       reporter=reporter)
```

Add the writing phase header — replace:

```python
    html = render_html(
        pool, username=config.username, defaults=defaults,
        owned_sources=owned_sources, apple_enabled=apple_enabled,
        owned_records=owned_records, albums=albums, by_record=by_record,
    )
    write_html(html, config.output_path)
```

with:

```python
    reporter.phase("Writing page")
    html = render_html(
        pool, username=config.username, defaults=defaults,
        owned_sources=owned_sources, apple_enabled=apple_enabled,
        owned_records=owned_records, albums=albums, by_record=by_record,
    )
    write_html(html, config.output_path)
```

- [ ] **Step 6: Add the `--quiet` flag and build the reporter in `main`**

Replace:

```python
    parser.add_argument("--limit", type=int, default=None,
                        help="faster sample: crawl supporters for only the first "
                             "N owned albums (your full collection is still "
                             "excluded from results)")
    args = parser.parse_args(argv)
```

with:

```python
    parser.add_argument("--limit", type=int, default=None,
                        help="faster sample: crawl supporters for only the first "
                             "N owned albums (your full collection is still "
                             "excluded from results)")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress progress output")
    args = parser.parse_args(argv)
```

Replace:

```python
    cache = Cache(config.cache_path)
    fetcher = Fetcher(delay=config.request_delay)
    try:
        recs = run(config, fetcher, cache, limit=args.limit)
    finally:
        cache.close()
```

with:

```python
    cache = Cache(config.cache_path)
    fetcher = Fetcher(delay=config.request_delay)
    reporter = make_reporter(quiet=args.quiet)
    try:
        recs = run(config, fetcher, cache, limit=args.limit, reporter=reporter)
    finally:
        cache.close()
```

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — the four new tests plus every existing test (the existing `test_main` Apple/`--limit`/self-fan tests call `run`/`_apply_apple_music` without `reporter`, so the defaults keep them green).

- [ ] **Step 8: Commit**

```bash
git add bandcamp_reco/main.py tests/test_main.py
git commit -m "feat: phase headers + crawl bar + --quiet flag in the pipeline"
```

---

## Self-Review

**1. Spec coverage**

| Spec item | Task |
| --- | --- |
| `progress.py` with `Reporter` (`phase`, `bar`), `NULL_REPORTER`, `make_reporter` | Task 1 |
| tqdm dependency added | Task 1 |
| Phase header format `→ <label>` to stderr | Task 1 (impl) + Task 4 (use) |
| Bars auto-disable when not a TTY (`disable=None`) | Task 1 |
| Fan-collections bar counts fetched fans vs `max_fans` | Task 2 |
| Apple bar, only when Apple Music enabled | Task 3 (bar) + Task 4 (`_apply_apple_music` returns early when disabled) |
| Crawl-supporters bar (`total=len(crawl_albums)`) | Task 4 |
| Phase headers: reading collection, scoring, writing | Task 4 |
| `--quiet` flag forces off; result line stays on stdout | Task 4 |
| Default no-op keeps existing tests green | Tasks 2–4 (default `reporter=NULL_REPORTER`) |
| Tests: disabled silent, enabled header, make_reporter, behavior preserved | Tasks 1–4 |

No gaps. (The `_enrich_tags` network step is covered by the "Scoring recommendations" phase header per the spec's phase mapping — no separate bar, by design.)

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows complete code.

**3. Type consistency:** `Reporter.bar(total, label)` yields a handle with `.update(n=1)` (Task 1), used identically in `fans.py` (Task 2), `apple_music.py` (Task 3), and the crawl loop (Task 4). `reporter=NULL_REPORTER` is the default on `get_fan_collections` (Task 2), `lookup_pool` (Task 3), `run`, and `_apply_apple_music` (Task 4). `make_reporter(quiet)` (Task 1) is called only in `main` (Task 4). The `→` phase-header arrow is consistent between the impl (Task 1) and the silent-case test assertion (Task 4).
