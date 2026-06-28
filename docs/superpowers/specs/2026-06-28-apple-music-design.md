# Apple Music availability + filter

## Goal

For each recommended album, check whether it exists on Apple Music and, if so,
link to it there. Add filters to show or hide albums by Apple Music
availability, plus a way to flag wrong matches for later debugging.

This is purely additive: a run with no Apple Music credentials behaves exactly
as it does today.

## Decisions

- **Data source:** the official Apple Music API catalog search
  (`GET /v1/catalog/{storefront}/search?types=albums`), authenticated with a
  developer token. Catalog reads need only the developer token — no user login
  — which preserves the tool's login-free spirit.
- **Storefront:** `gb` (UK), stored in config so it can be changed later.
- **Filter UI:** two combining checkboxes — "Hide albums on Apple Music" and
  "Hide albums not on Apple Music".
- **Credentials:** live in `config.local.toml` (already gitignored).
- **Lookups run in parallel** over the candidate pool, cached in SQLite.

## Architecture

```
bandcamp_reco/
  apple_music.py   NEW: token generation, client, catalog lookup, matching
  config.py        extend: load config.local.toml overlay + Apple Music settings
  main.py          extend: parallel lookup phase, annotate pool items
  score.py         unchanged shape; pool items gain "apple" fields in main
  render.py        extend: render link + two filter checkboxes + flag UI
```

### `apple_music.py`

- `developer_token(creds)` — signs an ES256 JWT from the `.p8` key, Team ID and
  Key ID, valid ~12h, generated once per run, reused (read-only string) across
  worker threads. New dependency: `PyJWT[crypto]`.
- `AppleMusicClient` — holds the token and a `requests` session;
  `search_album(artist, title, storefront)` queries catalog search.
- `lookup_pool(pool, creds, cache, storefront, workers)` — orchestration: read
  cache on the main thread to find uncached albums, dispatch those through a
  `ThreadPoolExecutor`, collect results, write them to the cache **from the main
  thread**, and return a map of `album_key -> result`.
- Matching helpers (normalization + confidence check) live here.

### Why a separate client, not the existing `Fetcher`

The Bandcamp `Fetcher` uses a deliberately slow serial throttle (0.7s + jitter)
because scraping Bandcamp too fast trips its rate limiter, and it carries a
shared `_consecutive_429` counter that is not thread-safe. The Apple Music API
is a separate, authenticated host with generous catalog-read limits that
tolerate concurrency. So Apple lookups use their own client (own session, light
throttle, own 429 backoff) and run concurrently.

## Performance

- The pool is the right unit to check: capped at 400 albums, versus tens of
  thousands of raw fan albums. Lookups happen **after** the pool is built and
  scored (the pool isn't known until then).
- Every result is cached in SQLite, so it is a one-time cost; re-runs skip
  already-checked albums.
- Cold run: ~400 lookups through a thread pool (8-16 workers) is roughly
  10-30 seconds, versus ~5 minutes if run serially at the Bandcamp throttle.
- Speculative mid-crawl overlap is intentionally **not** done: the pool isn't
  known until scoring finishes, so it would waste API calls on albums that don't
  qualify. Internal parallelism is the lever that matters.

## Matching logic

Precision-leaning: when unsure, mark unavailable rather than guess. A false
"available" produces a wrong link; a false "unavailable" pollutes the "not on
Apple Music" list with albums that are actually there.

Per album:

1. **Normalize** both Bandcamp and Apple strings: lowercase, strip diacritics
   (NFKD), drop bracketed/parenthetical qualifiers (`(Deluxe Edition)`,
   `[2020 Remaster]`), drop trailing ` - EP` / ` - Single`, collapse
   punctuation and whitespace.
2. **Query** catalog search with `types=albums`, `term = "<artist> <title>"`,
   `limit=10`.
3. **Confirm** against each returned album. Accept the best result where **both**
   normalized artist **and** normalized title clear a similarity threshold:
   exact normalized match, or `difflib.SequenceMatcher` ratio >= ~0.85 (stdlib,
   no new dependency). First confident match wins -> `available` plus its
   `music.apple.com` URL. No confident match -> `unavailable`.

Edge cases:

- **Compilations** (`Various Artists` / empty artist): accept on a strong title
  match alone, since the artist field will not line up.
- **Singles posted as Bandcamp "albums":** v1 searches albums only. Something
  that exists on Apple only as a single reads as unavailable. Known limitation,
  not handled in v1.

The threshold and normalization rules are constants in `apple_music.py` for easy
tuning, and this is the most heavily unit-tested piece.

## Data shape

Per pool item, added in `main.py` after the lookup phase:

- `apple`: `"available"` | `"unavailable"` | `"unknown"` (unknown = lookup
  errored this run).
- `appleUrl`: the `music.apple.com` link (only when available).
- `appleName` / `appleArtist`: what Apple matched, for flag/debug context.

Cache namespace `apple_music`, keyed by `album_key` (the same key the rest of the
pipeline uses). Only definitive results (`available` / `unavailable`) are cached;
transient errors stay `unknown` and retry next run.

## Config

- Wire up the `config.local.toml` overlay: load `config.toml`, then overlay
  `config.local.toml` if present. (It is gitignored today but never read.)
- New `[apple_music]` table:

  ```toml
  [apple_music]
  storefront = "gb"
  team_id = "ABCDE12345"
  key_id = "ABCD123456"
  private_key_path = "AuthKey_ABCD123456.p8"
  workers = 12
  ```

  Parsed into an optional `AppleMusicConfig`; `None` (feature off) when
  credentials are absent.
- `requirements.txt`: add `PyJWT[crypto]`.

## Page UI (`render.py`)

All Apple Music UI is guarded behind an `apple_enabled` flag so the page is
identical to today when the feature is off.

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

- No/invalid credentials -> feature disabled, one-line stderr notice, page
  renders as today.
- Token signing failure -> caught, feature disabled, notice.
- Per-album lookup error -> mark `unknown`, do not cache, continue (a dead
  worker does not kill the pool).
- Persistent Apple 429s -> back off, then stop the Apple phase early, mark the
  rest `unknown`, and still render.

## Testing

- **Matching:** fixture-based unit tests (clean / deluxe / EP / various-artists /
  no-result), no network.
- **Token:** assert ES256 JWT header and claims (`kid`, `iss`, `iat`/`exp`)
  using a throwaway test EC key; no real key committed.
- **`lookup_pool`:** injected fake client + in-memory cache -> cache-skip,
  parallel collection, error -> `unknown`, writes happen on the main thread.
- **Config:** overlay merge; `AppleMusicConfig` present/absent.
- **Render:** checkboxes / links / flag markup present when enabled, absent when
  not.

## Out of scope (v1)

- Matching singles/tracks (albums only).
- Feeding flagged corrections back into the run via an overrides file.
- Storefronts other than the configured one (single storefront per run).
