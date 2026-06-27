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
