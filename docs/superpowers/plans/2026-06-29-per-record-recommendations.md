# Per-record recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick one record from their collection and see albums similar to it ("fans who bought this also bought these"), browsable in the existing HTML page.

**Architecture:** Keep the seed-record→supporters link the pipeline currently discards, then reuse `score.candidate_pool` per seed to build each record's pool. Normalize the results into a deduped album table plus per-record references, embed them in the page, and let the existing client-side re-rank engine drive a new "By record" view via a `currentPool()` accessor. Purely additive — the whole-collection view is untouched.

**Tech Stack:** Python 3.11+ (stdlib `tomllib`, `dataclasses`, `json`), pytest, vanilla HTML/CSS/JS in a single rendered file. No new dependencies.

## Global Constraints

- **Purely additive.** The whole-collection view and its output are unchanged; with no per-record data the page renders exactly as before. Every existing test must stay green.
- **Collaborative, album-level, discovery-only.** Similarity is fan-ownership overlap; candidates are albums the user does **not** own.
- **No new network crawl.** Per-record data is built from the same `fan_albums` a full run already fetches.
- **Per-fan weight is the global affinity** (count of the user's whole collection a fan owns), capped by `affinity_cap` — identical to the global view. Achieved by reusing `candidate_pool` with the full `owned_keys`.
- **Defaults:** `per_record_pool_size = 60`, `per_record_min_fans = 2`.
- **Normalized embed:** `OWNED_RECORDS` (pickable records), `ALBUMS` (deduped album metadata keyed by album key), `BYRECORD` (per-record refs into `ALBUMS`).
- **No new dependencies.** Follow existing patterns; tests assert on the rendered HTML string (no JS test harness in this repo).

---

### Task 1: Config — per-record settings

**Files:**
- Modify: `bandcamp_reco/config.py`
- Modify: `config.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.per_record_pool_size: int` (default 60), `Config.per_record_min_fans: int` (default 2); both overridable from `config.toml` top-level keys.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_per_record_settings_default_and_override(tmp_path):
    cfg = load_config(str(tmp_path / "nope.toml"))
    assert cfg.per_record_pool_size == 60
    assert cfg.per_record_min_fans == 2

    p = tmp_path / "config.toml"
    p.write_text("per_record_pool_size = 25\nper_record_min_fans = 3\n")
    cfg2 = load_config(str(p))
    assert cfg2.per_record_pool_size == 25
    assert cfg2.per_record_min_fans == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_per_record_settings_default_and_override -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'per_record_pool_size'`

- [ ] **Step 3: Add the fields and defaults**

In `bandcamp_reco/config.py`, add two fields to the `Config` dataclass. They MUST go after the last non-default field (`hide_owned_sources`) and before `apple_music`:

```python
    hide_owned_sources: bool
    per_record_pool_size: int = 60
    per_record_min_fans: int = 2
    apple_music: AppleMusicConfig | None = None
```

Then add the two keys to the `DEFAULTS` dict (after `"hide_owned_sources": False,`):

```python
    "hide_owned_sources": False,
    "per_record_pool_size": 60,
    "per_record_min_fans": 2,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (all config tests, including the new one)

- [ ] **Step 5: Document the settings in config.toml**

In `config.toml`, after the `hide_owned_sources = false` line (and its comment block), add:

```toml
# --- Per-record recommendations ("By record" view) ---
# Max similar albums embedded per owned record (the main page-size lever).
per_record_pool_size = 60
# Min fans (of a record) who must own a candidate for it to appear in that
# record's similar list.
per_record_min_fans = 2
```

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/config.py config.toml tests/test_config.py
git commit -m "feat: config for per-record recommendations (pool size, min fans)"
```

---

### Task 2: `score.per_record_pools`

**Files:**
- Modify: `bandcamp_reco/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: existing `candidate_pool(owned_keys, fan_albums, get_tags=None, min_fans=2, pool_size=400)`.
- Produces:
  ```
  per_record_pools(owned_keys: set[str],
                   seed_supporters: dict[str, list[str]],
                   fan_albums: dict[str, list[Album]],
                   get_tags=None, min_fans=2, pool_size=60) -> dict[str, list[dict]]
  ```
  Maps each seed record's album key to that record's candidate-pool items (same dict shape `candidate_pool` returns). Records whose pool is empty are omitted.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_score.py` (note the new import on the existing import line):

```python
# at top: extend the existing score import
from bandcamp_reco.score import (
    score_candidates, candidate_pool, Recommendation, per_record_pools,
)


def test_per_record_pools_restricts_to_seed_fans():
    owned = {"https://own/a", "https://own/b"}
    fans = {
        "f1": [_album("https://own/a"), _album("https://c.bandcamp.com/album/x")],
        "f2": [_album("https://own/a"), _album("https://c.bandcamp.com/album/x")],
        "f3": [_album("https://own/b"), _album("https://d.bandcamp.com/album/y")],
    }
    seed_supporters = {
        "https://own/a": ["f1", "f2"],
        "https://own/b": ["f3"],
    }
    pools = per_record_pools(owned, seed_supporters, fans, min_fans=2)
    # record A: candidate x owned by both of A's fans -> present
    assert set(pools["https://own/a"][0]["hist"]) == {"1"}
    assert {it["url"] for it in pools["https://own/a"]} == {"https://c.bandcamp.com/album/x"}
    # record B: only one fan, y owned by 1 < min_fans=2 -> empty pool -> omitted
    assert "https://own/b" not in pools


def test_per_record_pools_skips_unfetched_fans():
    owned = {"https://own/a"}
    fans = {"f1": [_album("https://own/a"), _album("https://c.bandcamp.com/album/x")]}
    # f2 was never fetched (e.g. beyond max_fans); it must be ignored, not crash
    seed_supporters = {"https://own/a": ["f1", "f2"]}
    pools = per_record_pools(owned, seed_supporters, fans, min_fans=1)
    assert {it["url"] for it in pools["https://own/a"]} == {"https://c.bandcamp.com/album/x"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_score.py::test_per_record_pools_restricts_to_seed_fans -v`
Expected: FAIL — `ImportError: cannot import name 'per_record_pools'`

- [ ] **Step 3: Implement `per_record_pools`**

Append to `bandcamp_reco/score.py`:

```python
def per_record_pools(owned_keys, seed_supporters, fan_albums, get_tags=None,
                     min_fans=2, pool_size=60):
    """For each seed record (its album key -> the usernames who support it),
    build the candidate pool from ONLY that record's fans, reusing
    candidate_pool. Each fan is still weighted by their affinity against the
    user's whole `owned_keys`. Records whose pool is empty are omitted.

    Returns {seed_album_key: [pool item, ...]} (same item shape as
    candidate_pool)."""
    result = {}
    for seed_key, usernames in seed_supporters.items():
        sub_fans = {u: fan_albums[u] for u in usernames if u in fan_albums}
        items = candidate_pool(owned_keys, sub_fans, get_tags=get_tags,
                               min_fans=min_fans, pool_size=pool_size)
        if items:
            result[seed_key] = items
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_score.py -v`
Expected: PASS (all score tests)

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/score.py tests/test_score.py
git commit -m "feat: per_record_pools — per-seed candidate pools from one record's fans"
```

---

### Task 3: `score.normalize_per_record`

**Files:**
- Modify: `bandcamp_reco/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: the `{seed_key: [pool item]}` map from `per_record_pools`; existing `album_key_from_url` from `bandcamp_reco.models`.
- Produces:
  ```
  normalize_per_record(per_record: dict[str, list[dict]]) -> tuple[dict, dict]
  ```
  Returns `(albums, by_record)` where:
  - `albums`: `{album_key: {title, artist, url, art, source, tags}}` — each candidate stored once (no `hist`/`fans`).
  - `by_record`: `{seed_key: [{"a": album_key, "h": hist, "f": fans}, ...]}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_score.py` (extend the score import to include `normalize_per_record`):

```python
from bandcamp_reco.score import (
    score_candidates, candidate_pool, Recommendation, per_record_pools,
    normalize_per_record,
)


def test_normalize_per_record_dedupes_albums():
    per_record = {
        "https://own/a": [
            {"title": "X", "artist": "AX", "url": "https://c.bandcamp.com/album/x",
             "art": "ax", "source": "c", "tags": ["house"],
             "hist": {"1": 2}, "fans": 2},
        ],
        "https://own/b": [
            {"title": "X", "artist": "AX", "url": "https://c.bandcamp.com/album/x",
             "art": "ax", "source": "c", "tags": ["house"],
             "hist": {"2": 1}, "fans": 1},
        ],
    }
    albums, by_record = normalize_per_record(per_record)
    # the shared album appears once, metadata only (no per-record fields)
    assert list(albums) == ["https://c.bandcamp.com/album/x"]
    assert albums["https://c.bandcamp.com/album/x"]["title"] == "X"
    assert "hist" not in albums["https://c.bandcamp.com/album/x"]
    assert "fans" not in albums["https://c.bandcamp.com/album/x"]
    # each record references it with its own histogram + fan count
    assert by_record["https://own/a"] == [
        {"a": "https://c.bandcamp.com/album/x", "h": {"1": 2}, "f": 2}]
    assert by_record["https://own/b"] == [
        {"a": "https://c.bandcamp.com/album/x", "h": {"2": 1}, "f": 1}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_score.py::test_normalize_per_record_dedupes_albums -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_per_record'`

- [ ] **Step 3: Implement `normalize_per_record`**

First extend the import at the top of `bandcamp_reco/score.py`:

```python
from .models import Album, album_key, album_source, album_key_from_url
```

Then append to `bandcamp_reco/score.py`:

```python
def normalize_per_record(per_record):
    """Split per-record pools into a deduped album table and per-record refs.

    Returns (albums, by_record):
      albums:    {album_key: {title, artist, url, art, source, tags}}
      by_record: {seed_key: [{"a": album_key, "h": hist, "f": fans}, ...]}

    Each candidate album's metadata is stored once in `albums`; every record
    references it by key with its own histogram and fan count, so a popular
    album similar to many records is embedded only once."""
    albums = {}
    by_record = {}
    for seed_key, items in per_record.items():
        refs = []
        for it in items:
            k = album_key_from_url(it["url"])
            if k not in albums:
                albums[k] = {
                    "title": it["title"], "artist": it["artist"],
                    "url": it["url"], "art": it["art"],
                    "source": it["source"], "tags": it["tags"],
                }
            refs.append({"a": k, "h": it["hist"], "f": it["fans"]})
        by_record[seed_key] = refs
    return albums, by_record
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_score.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bandcamp_reco/score.py tests/test_score.py
git commit -m "feat: normalize_per_record — deduped ALBUMS table + per-record refs"
```

---

### Task 4: Render the "By record" view

**Files:**
- Modify: `bandcamp_reco/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `albums` and `by_record` from `normalize_per_record`; an `owned_records` list of `{key, title, artist, art, url}`.
- Produces: `render_html(pool, username, defaults, owned_sources=(), apple_enabled=False, owned_records=(), albums=None, by_record=None) -> str`. Embeds `OWNED_RECORDS`, `ALBUMS`, `BYRECORD`; adds a "By record" tab, record picker, selected-record header, and a `currentPool()`-style accessor the existing engine ranks. With no per-record data the new UI stays hidden and the page is unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_render.py`:

```python
def _owned_records():
    return [{"key": "https://own/a", "title": "My Record", "artist": "Me",
             "art": "", "url": "https://own/a"}]


def _albums():
    return {"https://c.bandcamp.com/album/x": {
        "title": "Candidate", "artist": "CA",
        "url": "https://c.bandcamp.com/album/x", "art": "",
        "source": "c", "tags": ["house"]}}


def _by_record():
    return {"https://own/a": [
        {"a": "https://c.bandcamp.com/album/x", "h": {"2": 3}, "f": 3}]}


def test_render_embeds_per_record_view():
    html = render_html(_pool(), username="u", defaults=DEFAULTS,
                       owned_records=_owned_records(), albums=_albums(),
                       by_record=_by_record())
    assert "OWNED_RECORDS" in html
    assert "ALBUMS" in html
    assert "BYRECORD" in html
    assert 'id="tabRecord"' in html          # the "By record" tab exists
    assert 'id="recordPicker"' in html        # the collection picker exists
    assert "My Record" in html                # the pickable record is embedded
    assert "https://c.bandcamp.com/album/x" in html  # its similar album


def test_render_per_record_absent_by_default():
    html = render_html(_pool(), username="u", defaults=DEFAULTS)
    # empty per-record data embeds as empty containers; the JS keeps the tab hidden
    assert "const OWNED_RECORDS = [];" in html
    assert "const ALBUMS = {};" in html
    assert "const BYRECORD = {};" in html


def test_render_per_record_data_is_valid_json():
    html = render_html(_pool(), username="u", defaults=DEFAULTS,
                       owned_records=_owned_records(), albums=_albums(),
                       by_record=_by_record())
    marker = "const BYRECORD = "
    start = html.index(marker) + len(marker)
    end = html.index(";\n", start)
    data = json.loads(html[start:end].replace("<\\/", "</"))
    assert data["https://own/a"][0]["f"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_render.py::test_render_embeds_per_record_view tests/test_render.py::test_render_per_record_absent_by_default -v`
Expected: FAIL — `TypeError: render_html() got an unexpected keyword argument 'owned_records'` (first) and missing-substring assertion (second).

- [ ] **Step 3: Implement — apply all six edits below to `bandcamp_reco/render.py`**

**Edit 3a — add CSS.** After the line `  .reset { font-size: 0.8rem; }` insert:

```css
  .viewtabs { display: flex; gap: 0.5rem; margin: 1rem 0 0.5rem; }
  .tab { background: #f3f3f3; border: 1px solid #e2e2e2; border-radius: 999px;
         padding: 0.3rem 0.9rem; font: inherit; font-size: 0.85rem; color: #555; cursor: pointer; }
  .tab.on { background: #1a6; border-color: #1a6; color: #fff; }
  #recordSearch { width: 100%; box-sizing: border-box; padding: 0.5rem 0.7rem;
                  border: 1px solid #ddd; border-radius: 8px; font: inherit; margin: 0.5rem 0; }
  .rec.pick { cursor: pointer; }
  .rec.pick:hover { background: #fafafa; }
  #recordHeader { display: flex; gap: 1rem; align-items: center; margin: 1rem 0;
                  padding: 0.75rem; background: #fafafa; border: 1px solid #eee; border-radius: 8px; }
  #recordHeader img, #recordHeader .noart { width: 64px; height: 64px; }
  .simlabel { color: #999; font-size: 0.75rem; }
```

**Edit 3b — add the tabs/picker/header HTML and wrap the results.** After the intro paragraph (the line ending `<a href="#" class="reset" id="reset">reset</a>.</p>`) insert:

```html

<div class="viewtabs" id="viewtabs" style="display:none">
  <button class="tab on" id="tabAll" type="button">Whole collection</button>
  <button class="tab" id="tabRecord" type="button">By record</button>
</div>
<div id="recordPicker" style="display:none">
  <input type="text" id="recordSearch" placeholder="Search your collection&hellip;" autocomplete="off">
  <p class="count" id="pickerCount"></p>
  <div id="recordList"></div>
</div>
<div id="recordHeader" style="display:none"></div>
<div id="results">
```

Then, to close that `#results` wrapper, change the recs container line:

```html
<div id="recs"></div>
```

to:

```html
<div id="recs"></div>
</div>
```

**Edit 3c — add per-record consts, state and helpers.** After the line `const APPLE_ENABLED = __APPLE_ENABLED__;` insert:

```javascript
const OWNED_RECORDS = __OWNED_RECORDS__;
const ALBUMS = __ALBUMS__;
const BYRECORD = __BYRECORD__;

let CURRENT = POOL;     // the pool the engine currently ranks
let mode = "all";       // "all" | "record"
let selectedKey = null; // selected owned-record key in "by record" mode

function poolForRecord(key) {
  return (BYRECORD[key] || []).map((ref) => {
    const meta = ALBUMS[ref.a] || {};
    return Object.assign({}, meta, { hist: ref.h, fans: ref.f });
  });
}

function applyMode() {
  const recordMode = mode === "record";
  el("recordPicker").style.display = (recordMode && !selectedKey) ? "" : "none";
  el("recordHeader").style.display = (recordMode && selectedKey) ? "" : "none";
  el("results").style.display = (recordMode && !selectedKey) ? "none" : "";
  el("tabAll").className = "tab" + (recordMode ? "" : " on");
  el("tabRecord").className = "tab" + (recordMode ? " on" : "");
}

function renderRecordHeader(r) {
  const h = el("recordHeader");
  h.textContent = "";
  if (r.art) {
    const img = document.createElement("img");
    img.src = r.art; img.alt = ""; img.loading = "lazy";
    h.appendChild(img);
  } else {
    const ph = document.createElement("div"); ph.className = "noart"; h.appendChild(ph);
  }
  const meta = document.createElement("div"); meta.className = "meta";
  const lab = document.createElement("div"); lab.className = "simlabel"; lab.textContent = "Similar to";
  const title = document.createElement("div"); title.className = "title";
  const a = document.createElement("a");
  a.href = r.url; a.textContent = r.title; a.target = "_blank"; a.rel = "noopener";
  title.appendChild(a);
  const artist = document.createElement("div"); artist.className = "artist"; artist.textContent = r.artist;
  const back = document.createElement("a");
  back.href = "#"; back.className = "reset"; back.textContent = "← back to my records";
  back.addEventListener("click", (e) => { e.preventDefault(); selectedKey = null; applyMode(); });
  meta.appendChild(lab); meta.appendChild(title); meta.appendChild(artist); meta.appendChild(back);
  h.appendChild(meta);
}

function renderPicker() {
  const q = el("recordSearch").value.trim().toLowerCase();
  const matches = OWNED_RECORDS.filter((r) =>
    !q || r.title.toLowerCase().includes(q) || r.artist.toLowerCase().includes(q));
  el("pickerCount").textContent =
    OWNED_RECORDS.length + " of your records have enough data" +
    (q ? " · " + matches.length + " match" : "");
  const list = el("recordList");
  list.textContent = "";
  for (const r of matches) {
    const wrap = document.createElement("div");
    wrap.className = "rec pick";
    if (r.art) {
      const img = document.createElement("img");
      img.src = r.art; img.alt = ""; img.loading = "lazy";
      wrap.appendChild(img);
    } else {
      const ph = document.createElement("div"); ph.className = "noart"; wrap.appendChild(ph);
    }
    const meta = document.createElement("div"); meta.className = "meta";
    const t = document.createElement("div"); t.className = "title"; t.textContent = r.title;
    const ar = document.createElement("div"); ar.className = "artist"; ar.textContent = r.artist;
    meta.appendChild(t); meta.appendChild(ar);
    wrap.appendChild(meta);
    wrap.addEventListener("click", () => selectRecord(r.key));
    list.appendChild(wrap);
  }
}

function selectRecord(key) {
  selectedKey = key;
  CURRENT = poolForRecord(key);
  const r = OWNED_RECORDS.find((x) => x.key === key);
  if (r) renderRecordHeader(r);
  applyMode();
  render();
}
```

**Edit 3d — make the scorer read the current pool.** Replace:

```javascript
  return POOL.map((item) => {
```

with:

```javascript
  return CURRENT.map((item) => {
```

**Edit 3e — make the count read the current pool, and the why-text seed-aware.** Replace:

```javascript
  el("count").textContent = rows.length + " of " + POOL.length +
    " candidate albums shown.";
```

with:

```javascript
  el("count").textContent = rows.length + " of " + CURRENT.length +
    " candidate albums shown.";
```

Then replace the whole `whyText` function:

```javascript
function whyText(fans, typical) {
  const albWord = typical === 1 ? "album" : "albums";
  const head = fans === 1 ? "1 fan who shares" : fans + " fans who each share";
  return "Owned by " + head + " ~" + typical + " " + albWord + " with your collection.";
}
```

with:

```javascript
function whyText(fans, typical) {
  const albWord = typical === 1 ? "album" : "albums";
  const who = mode === "record" ? " of this record" : "";
  const head = fans === 1 ? "1 fan" + who + " who shares"
                          : fans + " fans" + who + " who each share";
  return "Owned by " + head + " ~" + typical + " " + albWord + " with your collection.";
}
```

**Edit 3f — wire up the tabs.** Immediately before the final two lines:

```javascript
applyDefaults();
render();
```

insert:

```javascript
if (OWNED_RECORDS.length) {
  el("viewtabs").style.display = "";
  el("tabAll").addEventListener("click", () => {
    mode = "all"; selectedKey = null; CURRENT = POOL; applyMode(); render();
  });
  el("tabRecord").addEventListener("click", () => {
    mode = "record"; renderPicker(); applyMode();
  });
  el("recordSearch").addEventListener("input", renderPicker);
}
```

- [ ] **Step 4: Update `render_html` to embed the new data**

Replace the whole `render_html` function:

```python
def render_html(pool: list[dict], username: str, defaults: dict,
                owned_sources=(), apple_enabled: bool = False) -> str:
    """Render the interactive recommendations page. `pool` is the candidate
    data from score.candidate_pool; the page re-ranks it client-side from the
    control values, seeded by `defaults`. `owned_sources` is the set of
    labels/artists the user already owns, for the "hide owned" filter."""
    def embed(value) -> str:
        # JSON, made safe to sit inside a <script> tag (can't break out via </).
        return json.dumps(value).replace("</", "<\\/")

    return (
        _PAGE
        .replace("__POOL__", embed(pool))
        .replace("__DEFAULTS__", embed(defaults))
        .replace("__OWNED_SOURCES__", embed(sorted(owned_sources)))
        .replace("__USERNAME_TEXT__", _html_escape(username))
        .replace("__APPLE_ENABLED__", "true" if apple_enabled else "false")
    )
```

with:

```python
def render_html(pool: list[dict], username: str, defaults: dict,
                owned_sources=(), apple_enabled: bool = False,
                owned_records=(), albums=None, by_record=None) -> str:
    """Render the interactive recommendations page. `pool` is the candidate
    data from score.candidate_pool; the page re-ranks it client-side from the
    control values, seeded by `defaults`. `owned_sources` is the set of
    labels/artists the user already owns, for the "hide owned" filter.

    `owned_records`, `albums`, and `by_record` power the "By record" view:
    the user's pickable records, a deduped album-metadata table, and per-record
    references into it. Omit them and the per-record UI stays hidden."""
    def embed(value) -> str:
        # JSON, made safe to sit inside a <script> tag (can't break out via </).
        return json.dumps(value).replace("</", "<\\/")

    return (
        _PAGE
        .replace("__POOL__", embed(pool))
        .replace("__DEFAULTS__", embed(defaults))
        .replace("__OWNED_SOURCES__", embed(sorted(owned_sources)))
        .replace("__OWNED_RECORDS__", embed(list(owned_records)))
        .replace("__ALBUMS__", embed(albums or {}))
        .replace("__BYRECORD__", embed(by_record or {}))
        .replace("__USERNAME_TEXT__", _html_escape(username))
        .replace("__APPLE_ENABLED__", "true" if apple_enabled else "false")
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_render.py -v`
Expected: PASS — the new tests pass and all existing render tests (including `test_render_neutralizes_script_breakout_in_data`, which still expects exactly one `</script>`) stay green.

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/render.py tests/test_render.py
git commit -m "feat: 'By record' view — picker, selected-record header, currentPool engine"
```

---

### Task 5: Wire per-record data through the run

**Files:**
- Modify: `bandcamp_reco/main.py`
- Modify: `README.md`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `per_record_pools`, `normalize_per_record` (Tasks 2–3); the extended `render_html` (Task 4); `config.per_record_pool_size`, `config.per_record_min_fans` (Task 1); existing `album_key`, `cached_tags`, `_apply_apple_music`.
- Produces: `run()` builds `seed_supporters`, the normalized per-record data, and `owned_records`, then passes them to `render_html`. Apple Music enrichment runs once over the union of the global pool and the deduped per-record albums.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_run_embeds_per_record_data(tmp_path, monkeypatch):
    _base_stubs(monkeypatch, [_album("https://own/1")])
    main_mod.run(_cfg(tmp_path), fetcher=None, cache=None)
    html = (tmp_path / "out.html").read_text()
    # the seed record is pickable, and the per-record structures are embedded
    assert "OWNED_RECORDS" in html
    assert "BYRECORD" in html
    assert "https://own/1" in html      # the seed record (in OWNED_RECORDS)
    assert "https://cand/x" in html     # its similar album (in ALBUMS)
```

`_base_stubs` already returns two supporters (`fan1`, `fan2`) who both own `https://cand/x`, so the seed `https://own/1` gets a non-empty pool under the default `per_record_min_fans = 2`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py::test_run_embeds_per_record_data -v`
Expected: FAIL — `OWNED_RECORDS` is not yet embedded (substring assertion fails).

- [ ] **Step 3: Extend the score import in main.py**

Replace:

```python
from .score import score_candidates, candidate_pool
```

with:

```python
from .score import (
    score_candidates, candidate_pool, per_record_pools, normalize_per_record,
)
```

- [ ] **Step 4: Keep the seed→supporters link in the crawl loop**

Replace this block:

```python
    # collect candidate supporters across the crawled owned albums
    supporter_usernames = []
    for album in crawl_albums:
        try:
            supporter_usernames.extend(
                get_supporters(album, fetcher, cache,
                               limit=config.supporters_per_album)
            )
        except CircuitBreakerTripped:
            break
        except Exception:
            continue

    # You are a supporter of your own albums; never sample yourself as a fan
    # (your collection is all owned, and would otherwise dominate the results).
    supporter_usernames = [u for u in supporter_usernames if u != config.username]
```

with:

```python
    # Collect supporters per crawled owned album, keeping the link between each
    # seed record and its supporters (the "by record" view needs it). You are a
    # supporter of your own albums; never sample yourself as a fan (your
    # collection is all owned, and would otherwise dominate the results).
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

    supporter_usernames = [u for seed in seed_supporters.values() for u in seed]
```

- [ ] **Step 5: Build, normalize, enrich, and render the per-record data**

Replace this block:

```python
    defaults = {
        "affinity_cap": config.affinity_cap,
        "max_per_source": config.max_per_source,
        "top_n": config.top_n,
        "min_fans": 2,
        "hide_owned_sources": config.hide_owned_sources,
    }
    # Labels/artists (Bandcamp sources) you already own music from, so the page
    # can offer to filter them out for pure discovery.
    owned_sources = sorted({album_source(a.url) for a in owned})
    apple_enabled = _apply_apple_music(config, pool, cache)
    html = render_html(pool, username=config.username, defaults=defaults,
                       owned_sources=owned_sources, apple_enabled=apple_enabled)
    write_html(html, config.output_path)
    return recs
```

with:

```python
    # Per-record "by this one" data: each owned record's similar albums, built
    # from only that record's fans, then normalized into a shared album table.
    per_record = per_record_pools(
        owned_keys, seed_supporters, fan_albums,
        get_tags=lambda u: cached_tags(u, cache),
        min_fans=config.per_record_min_fans,
        pool_size=config.per_record_pool_size,
    )
    albums, by_record = normalize_per_record(per_record)
    # Only records that produced at least one candidate are pickable.
    owned_records = [
        {"key": album_key(a), "title": a.title, "artist": a.artist,
         "art": a.art_url or "", "url": a.url}
        for a in owned if album_key(a) in by_record
    ]

    defaults = {
        "affinity_cap": config.affinity_cap,
        "max_per_source": config.max_per_source,
        "top_n": config.top_n,
        "min_fans": 2,
        "hide_owned_sources": config.hide_owned_sources,
    }
    # Labels/artists (Bandcamp sources) you already own music from, so the page
    # can offer to filter them out for pure discovery.
    owned_sources = sorted({album_source(a.url) for a in owned})

    # Enrich Apple Music once over the union of the global pool and every unique
    # per-record album, so each album is looked up at most once (cached) and both
    # views show the link. The album dicts are shared by reference, so mutating
    # them here updates the embedded ALBUMS table too.
    apple_enabled = _apply_apple_music(config, pool + list(albums.values()), cache)
    html = render_html(
        pool, username=config.username, defaults=defaults,
        owned_sources=owned_sources, apple_enabled=apple_enabled,
        owned_records=owned_records, albums=albums, by_record=by_record,
    )
    write_html(html, config.output_path)
    return recs
```

- [ ] **Step 6: Run the main tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS — the new test passes and all existing run tests (Apple enabled/disabled/failure, `--limit` exclusion, self-not-sampled) stay green.

- [ ] **Step 7: Document the feature in README.md**

In `README.md`, after the "## How it works" section (before "## Notes"), add:

```markdown
## Pick a record (similar records)

The page has two views, switchable at the top:

- **Whole collection** — the default: albums ranked by how much taste their
  owners share with your entire collection.
- **By record** — pick any one record from your collection and see albums its
  fans also bought ("people who bought this also bought these"). Use the search
  box to find a record, click it, and the same controls re-rank just that
  record's similar albums. Only records with enough supporter data are listed.

This needs no extra run or network: it is built from the same fan data a full
run already gathers. Tune `per_record_pool_size` / `per_record_min_fans` in
`config.toml` to trade page size against depth.
```

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS — every test green.

- [ ] **Step 9: Commit**

```bash
git add bandcamp_reco/main.py README.md tests/test_main.py
git commit -m "feat: wire per-record recommendations through the run + docs"
```

---

## Self-Review

**1. Spec coverage**

| Spec item | Task |
| --- | --- |
| Keep seed→supporters link (was discarded) | Task 5 (crawl loop) |
| Per-record pools reuse `candidate_pool`, full-collection affinity weight | Task 2 |
| Discovery-only (exclude owned) | Inherited from `candidate_pool` (Task 2) |
| Normalized `OWNED` / `ALBUMS` / `BYRECORD` embed | Tasks 3 (build) + 4 (embed) |
| Apple Music lookups once per unique album | Task 5 (union enrichment) |
| Browse-in-page: tab, picker + search, selected-record header, shared controls | Task 4 |
| Per-record "why" text gains seed context | Task 4 (Edit 3e) |
| Thin/empty records omitted; "M of your N records have enough data" | Task 2 (omit empty) + Task 5 (`owned_records` filter) + Task 4 (`pickerCount`) |
| `--limit` only first N pickable | Inherited — `seed_supporters` only holds crawled albums (Task 5) |
| Config `per_record_pool_size` (60), `per_record_min_fans` (2) | Task 1 |
| Purely additive; global view + existing tests unchanged | All tasks keep `POOL` path intact; default-empty embeds |

No gaps.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows complete code.

**3. Type consistency:** `per_record_pools(owned_keys, seed_supporters, fan_albums, get_tags, min_fans, pool_size) -> {seed_key: [item]}` (Task 2) feeds `normalize_per_record(per_record) -> (albums, by_record)` (Task 3), consumed by `render_html(..., owned_records, albums, by_record)` (Task 4) and assembled in `run()` (Task 5). Ref shape `{"a","h","f"}` and album-table keys (`album_key_from_url`) match across Tasks 3, 4 (`poolForRecord`), and the JSON-validity test. `owned_records` item shape `{key,title,artist,art,url}` matches between Task 5 (build) and Task 4 (`renderPicker`/`renderRecordHeader`). Config field names match between Task 1 and Task 5.
