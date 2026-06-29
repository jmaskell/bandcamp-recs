# Apple Music availability + filter

## Goal

For each recommended album, check whether it exists on Apple Music and, if so,
link to it there. Add filters to show or hide albums by Apple Music
availability, plus a way to flag wrong matches for later debugging.

This is purely additive: a run with the feature disabled behaves exactly as it
does today.

## Revision note

Originally specced against the **official Apple Music API** (developer token via
a MusicKit key). That key turned out to be unavailable, so this design uses the
**public iTunes Search API** instead — keyless, free, no credentials. The
trade-off is a much stricter rate limit (~20 requests/minute), which is handled
by throttling and resuming across runs rather than by parallelism.

## Decisions

- **Data source:** the public **iTunes Search API**
  (`GET https://itunes.apple.com/search?term=...&entity=album&country=gb`).
  Keyless, no auth, no signup. A result's `collectionViewUrl` is the Apple Music
  link.
- **Country:** `gb` (UK), stored in config so it can be changed later.
- **Filter UI:** two combining checkboxes — "Hide albums on Apple Music" and
  "Hide albums not on Apple Music".
- **Lookups are throttled and resumable**, not parallel: ~3s between requests to
  stay under the rate limit; every result cached in SQLite; if the API starts
  rate-limiting (HTTP 403), the Apple phase stops cleanly and resumes next run.
- **Enabled via config** (`[apple_music]` in `config.toml`); with no such section,
  or `enabled = false`, the feature is off and the page is unchanged.

## Architecture

```
bandcamp_reco/
  apple_music.py   NEW: iTunes search client, matching, resumable lookup
  config.py        extend: parse [apple_music] settings
  main.py          extend: lookup phase, annotate pool items
  score.py         unchanged shape; pool items gain "apple" fields in main
  render.py        extend: render link + two filter checkboxes + flag UI
```

### `apple_music.py`

- `AppleMusicClient` — holds a `requests` session and a throttle;
  `search_album(artist, title, country)` queries the iTunes Search API and
  returns the `results` list.
- `lookup_pool(pool, client, cache, country)` — orchestration: walk the pool,
  skip albums already in the cache, search + match each uncached album,
  **cache each result immediately** (so partial progress survives), and stop
  cleanly if the API rate-limits. Returns a map of `album_key -> AppleMatch`.
- Matching helpers (normalization + confidence check) live here.

### Why a separate client, not the existing `Fetcher`

The iTunes Search API needs its own throttle (~3s vs the Bandcamp `Fetcher`'s
0.7s) and treats rate-limiting differently — it returns HTTP **403** when you
exceed ~20 requests/minute, which the Bandcamp `Fetcher` would treat as a fatal
4xx. So Apple lookups use a dedicated client that turns 403 into a clean
"stop and resume next run" signal.

## Performance

- The pool is the right unit to check: capped at 400 albums, versus tens of
  thousands of raw fan albums. Lookups happen **after** the pool is built and
  scored.
- Every result is cached in SQLite, so it is a one-time cost; re-runs skip
  already-checked albums.
- The iTunes Search API allows ~20 requests/minute. At ~3s per request, a full
  cold pool of ~400 albums takes ~15-20 minutes. This matches the tool's
  existing behaviour: it already runs slowly, caches everything, and is designed
  to be re-run. If the API rate-limits mid-run, the Apple phase stops cleanly and
  the next run continues from the cache.
- **No parallelism.** With a ~20/min limit, concurrent requests would trip the
  limiter (403) and get throttled harder; serial throttling is correct here.

## Matching logic

Precision-leaning: when unsure, mark unavailable rather than guess. A false
"available" produces a wrong link; a false "unavailable" pollutes the "not on
Apple Music" list with albums that are actually there.

Per album:

1. **Normalize** both Bandcamp and iTunes strings: lowercase, strip diacritics
   (NFKD), drop bracketed/parenthetical qualifiers (`(Deluxe Edition)`,
   `[2020 Remaster]`), drop trailing ` - EP` / ` - Single`, collapse
   punctuation and whitespace.
2. **Query** the iTunes Search API with `entity=album`, `country`,
   `term = "<artist> <title>"`, `limit=10`.
3. **Confirm** against each returned result (`collectionName`, `artistName`,
   `collectionViewUrl`). Accept the best one where **both** normalized artist
   **and** normalized title clear a similarity threshold: exact normalized
   match, or `difflib.SequenceMatcher` ratio >= ~0.85 (stdlib, no new
   dependency). First confident match wins -> `available` plus its
   `collectionViewUrl`. No confident match -> `unavailable`.

Edge cases:

- **Compilations** (`Various Artists` / empty artist): accept on a strong title
  match alone, since the artist field will not line up.
- **Singles posted as Bandcamp "albums":** v1 searches albums only
  (`entity=album`). Something that exists on Apple only as a single reads as
  unavailable. Known limitation, not handled in v1.
- **Store presence vs streaming:** the iTunes Search API reflects the iTunes
  Store catalog for a country, which closely tracks Apple Music availability but
  is not a guarantee of streaming rights. Treated as a good-enough proxy.

The threshold and normalization rules are constants in `apple_music.py` for easy
tuning, and this is the most heavily unit-tested piece.

## Data shape

Per pool item, added in `main.py` after the lookup phase:

- `apple`: `"available"` | `"unavailable"` | `"unknown"` (unknown = not yet
  checked this run, e.g. the phase stopped on rate-limit before reaching it).
- `appleUrl`: the Apple Music link (only when available).
- `appleName` / `appleArtist`: what iTunes matched, for flag/debug context.

Cache namespace `apple_music`, keyed by `album_key` (the same key the rest of the
pipeline uses). Only definitive results (`available` / `unavailable`) are cached;
albums not reached stay `unknown` and are looked up on a later run.

## Config

Add an `[apple_music]` table to `config.toml` (no secrets, so it lives in the
committed config):

```toml
[apple_music]
enabled = true
country = "gb"
request_delay = 3.0   # seconds between iTunes lookups (~20/min limit)
```

Parsed into an optional `AppleMusicConfig`; `None` (feature off) when the section
is absent or `enabled = false`. No new dependency — the iTunes Search API is a
plain `requests` GET.

## Page UI (`render.py`)

All Apple Music UI is guarded behind an `apple_enabled` flag so the page is
behaviorally and visually identical to today when the feature is off. (The
guarded markup/CSS/JS still ship in the template but stay hidden and inert, so
the raw bytes differ; nothing renders or runs.)

- **Per row:** an "Apple Music" link when available (subtle, next to the
  Bandcamp link), plus a "flag" toggle.
- **Two combining checkboxes** by the existing "Hide owned" toggle:
  - "Hide albums on Apple Music" -> filters out `apple === "available"`.
  - "Hide albums not on Apple Music" -> keeps only `apple === "available"`
    (so `unknown` is also hidden, since there is no confirmed link).

  Both reset-able and default off. With both checked the list is empty
  (an accepted consequence of the combination).
- **Flag / debug list** (the page is a self-contained `file://` page, so there
  is no backend to POST to):
  - The flag toggle records the album's full context — Bandcamp title/artist/
    URL, the verdict, and the matched Apple name/artist/URL — into
    `localStorage`, so flags survive reloads and re-runs.
  - A small bar shows the flag count with "Export" (downloads
    `apple-music-flags.json`) and "Clear".
  - Carrying the matched Apple name/artist into the export makes each entry
    self-explanatory ("flagged *A by B* — matched *X by Y*"), covering both
    error kinds without separate buttons.
  - v1 is capture + export only. The export format is shaped so a future
    `overrides` file could feed corrections back into the run; that feedback
    loop is out of scope here.

## Error handling

Apple failures never break recommendations:

- Feature off (no `[apple_music]` section or `enabled = false`) -> page renders
  as today.
- Per-album lookup error (network/parse) -> mark `unknown`, do not cache,
  continue to the next album.
- Rate-limited (HTTP 403/429) -> stop the Apple phase cleanly, leave the rest
  `unknown`, still render, and resume from the cache on the next run.

## Testing

- **Matching:** fixture-based unit tests against iTunes-shaped results (clean /
  deluxe / EP / various-artists / no-result), no network.
- **Client:** `search_album` hits the iTunes endpoint with the right params and
  returns the `results` list; 403 raises the rate-limit signal.
- **`lookup_pool`:** injected fake client + in-memory cache -> cache-skip,
  per-album caching, error -> `unknown`, rate-limit stops the phase with the
  remainder left unknown.
- **Config:** `[apple_music]` parsed; absent / `enabled = false` -> `None`.
- **Render:** checkboxes / links / flag markup present when enabled, absent when
  not.

## Out of scope (v1)

- Matching singles/tracks (albums only).
- Feeding flagged corrections back into the run via an overrides file.
- Countries other than the configured one (single country per run).
