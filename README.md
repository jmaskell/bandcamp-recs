# Bandcamp Recommendations

Reads your **public** Bandcamp collection, finds fans whose taste overlaps
yours, and ranks albums they own that you don't — output as a browsable HTML page.

## Setup

    python -m pip install -r requirements.txt

## Usage

    python recommend.py                 # full run, uses config.toml
    python recommend.py --limit 5       # faster sample (crawl 5 albums' fans)
    python recommend.py --top-n 100     # render more recommendations

Open `recommendations.html` in your browser when it finishes.

**Note:** `--limit N` is a faster sample — it only crawls the supporters of your first `N` owned albums, so results are narrower (and less personalized) than a full run. It does **not** affect exclusion: your entire collection is always filtered out of the recommendations either way. Run with no `--limit` for the full, richest results.

## Config

Edit `config.toml` — your `username`, sampling caps, request delay, output path.

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

## How it works

1. Reads your collection from `bandcamp.com/<username>`.
2. For each album, finds other fans who bought it ("supported by").
3. Reads those fans' public collections.
4. Scores albums you don't own by how much taste their owners share with you,
   damping for raw popularity.
5. Renders the top results to `recommendations.html`.

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

## Notes

- Read-only and login-free — it only reads public pages.
- Everything is cached in `cache.db`, so re-runs are fast and resumable. If
  Bandcamp rate-limits you, the run stops cleanly; just run it again later.
- Bandcamp's data shapes are unofficial; if the site changes, the parsers in
  `collection.py` / `supporters.py` may need a small update.
