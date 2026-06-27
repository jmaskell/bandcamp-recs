# Bandcamp Collaborative Recommendations — Design

**Date:** 2026-06-27
**Status:** Approved design, ready for implementation planning

## Summary

A small Python CLI tool that reads a user's **public** Bandcamp collection, runs
user-based collaborative filtering over Bandcamp's fan graph ("fans also
bought"), and produces a ranked **HTML page** of albums the user doesn't own yet
but is highly likely to enjoy. Every recommendation is a real Bandcamp release,
so it's directly buyable.

The tool only reads public pages and never logs in. It caches aggressively so
re-runs are fast, incremental, and resumable.

## Goals

- Surface genuinely personalized recommendations grounded in real taste overlap,
  not generic genre popularity.
- Keep everything inside Bandcamp so every result is buyable there.
- Be polite and low-risk toward Bandcamp's servers; be fully recoverable if
  throttled.
- Be small, readable, and testable — one module per pipeline stage.

## Non-Goals

- No login / no access to private purchases or hidden items (public collection
  only).
- No external recommendation services (Last.fm, Spotify, LLM ranking) in v1.
- No continuous/scheduled running in v1 — it's a manual CLI run.
- No purchasing or cart automation — output is a list of links.

## User & Configuration

- Bandcamp username: **`jmaskell`** (the public collection at
  `bandcamp.com/jmaskell`).
- Config lives in `config.toml` (with sensible defaults in code):
  - `username` — Bandcamp handle (default `jmaskell`).
  - `supporters_per_album` — fans to sample per owned album (default `30`).
  - `max_fans` — overall cap on distinct fans whose collections we fetch
    (default `500`).
  - `top_n` — number of recommendations rendered (default `50`).
  - `request_delay` — base delay between requests in seconds (default `0.7`),
    with randomized jitter applied.
  - `cache_path` — SQLite cache file (default `cache.db`).

## Architecture

A linear pipeline, one module per stage. Each stage reads from the cache and
writes results back so stages are independently runnable and testable.

```
username
  │
  ▼
collection.py   →  the albums you own (id, title, artist, url, art, tags)
  │
  ▼
supporters.py   →  for each owned album, the fans who "supported" (bought) it
  │
  ▼
fans.py         →  for a sampled set of those fans, their public collections
  │
  ▼
score.py        →  tally + score candidate albums (exclude what you own)
  │
  ▼
render.py       →  ranked recommendations.html
```

### Modules

1. **`collection.py` — what you own.**
   Fetches the collection for a given username. Bandcamp serves the collection
   as JSON behind the profile page (the `collection_items` endpoint, seeded by
   the `fan_id` and pagination token embedded in the profile page's data blob).
   Returns a normalized list of owned items: `item_id`, `title`, `artist`,
   `item_url`, `art_url`, `tags`. Used both for the user and (reused) for each
   sampled fan.

2. **`supporters.py` — who else owns your albums.**
   For each owned album, fetches the album page and parses the *"supported by"*
   fan list (the collectors shown on the release). Yields fan handles/ids.
   Honors `supporters_per_album`.

3. **`fans.py` — what those fans own.**
   For the sampled, de-duplicated set of fans (capped at `max_fans`), fetches
   each fan's public collection via the same mechanism as `collection.py`.
   Produces a mapping `fan → set(owned album ids)`.

4. **`score.py` — rank the candidates.**
   Aggregates every album owned across the sampled fans, excludes albums the
   user already owns, and scores each candidate. (See Scoring.)

5. **`render.py` — the output.**
   Renders the top `top_n` candidates to a standalone `recommendations.html`:
   album art, artist/title, tags, a plain-English "why", and a buy link. Opens
   cleanly in a browser, no server needed.

### Supporting components

- **`cache.py` — SQLite cache.** Every fetched profile, album page, and fan
  collection is stored once. Lookups hit the cache first. This makes re-runs
  near-instant and incremental, and lets an interrupted run resume.
- **`fetch.py` — the polite HTTP layer.** Single-threaded, one request at a
  time. Real browser `User-Agent`. Base `request_delay` plus randomized jitter.
  Retry with exponential backoff (with a ceiling) on 429/5xx. **Circuit
  breaker:** after a small number of consecutive 429s, it stops the run and
  saves progress rather than hammering.
- **`main.py` — CLI orchestrator.** Wires the pipeline, loads config, exposes
  flags including `--limit` (dry run) and `--top-n`.

## Scoring

The core idea: an album is a good recommendation to the degree that it is owned
by fans whose taste closely overlaps yours.

For each candidate album `c` (one you don't already own):

```
score(c) = Σ  affinity(f)        for each sampled fan f who owns c
           f

affinity(f) = | f.collection ∩ your.collection |     # shared albums
```

So an album owned by several fans who each share ~12–15 albums with you scores
far above one owned by fans who share only 1.

**Popularity dampening.** To stop globally huge releases from dominating purely
because everyone owns them, divide by a sublinear function of the candidate's
observed frequency, e.g.:

```
final(c) = score(c) / sqrt(global_count(c))
```

where `global_count(c)` is how many sampled fans own `c`. This keeps strong,
taste-aligned matches on top while damping generic blockbusters. (Exact dampening
constant is a tuning knob, validated during implementation against real output.)

**The "why" string** is generated from the same data, e.g.:
> *"Owned by 9 fans who each share ~12 albums with your collection."*

## Data Flow & Runtime

- First run does the real scraping; with the default caps it's a bounded, modest
  number of requests and may take a few minutes.
- The fan-out is `owned_albums × supporters_per_album`, de-duplicated and capped
  at `max_fans`, then one collection fetch per fan — all bounded by config.
- Subsequent runs are fast because the cache serves most fetches; the tool also
  effectively gets "smarter" as the cache accumulates fan data.

## Error Handling & Politeness

- **One request at a time** — no concurrency, never a flood.
- **Delay + jitter** between every request.
- **Exponential backoff with a ceiling** on 429/5xx.
- **Circuit breaker** halts the run on repeated consecutive 429s and saves
  progress; re-running later resumes from cache.
- Private collections, deleted albums, and malformed responses are caught and
  skipped, not fatal.
- No login, no private data, no writes to Bandcamp — read-only on public pages.

### Risk note

Bandcamp's JSON endpoints are unofficial and may change; if the site changes,
the parsers (`collection.py`, `supporters.py`) may need a tweak. Since nothing
logs in, there is no account risk; the only realistic failure mode is temporary
IP rate-limiting, which the circuit breaker + cache make fully recoverable.

## Testing

- **Parser unit tests** against saved fixture HTML/JSON (no network) for
  `collection.py` and `supporters.py`.
- **Scoring unit tests** with synthetic fans/collections that produce a known
  ranking, including the popularity-dampening behavior.
- **Cache tests** — store/retrieve round-trips, cache-hit avoids fetch.
- **`--limit` dry-run mode** for a quick end-to-end smoke test against a tiny
  sample.

## Project Layout

```
bandcamp/
  recommend.py            # entry point (thin wrapper over main.py) 
  config.toml
  bandcamp_reco/
    __init__.py
    main.py
    fetch.py
    cache.py
    collection.py
    supporters.py
    fans.py
    score.py
    render.py
  tests/
    fixtures/
    test_collection.py
    test_supporters.py
    test_score.py
    test_cache.py
  recommendations.html    # generated output (gitignored)
  cache.db                # generated cache (gitignored)
  docs/superpowers/specs/2026-06-27-bandcamp-recommendations-design.md
```

## Open Tuning Knobs (resolved during implementation)

- Exact popularity-dampening function/constant.
- Default cap values (validated against real runtime on the actual collection).
- Whether a light tag-overlap boost is worth adding (deferred unless results need it).
