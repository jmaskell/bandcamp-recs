# Per-record recommendations

## Goal

Let the user pick one record from their own collection and see albums similar to
it — "fans who bought this record also bought these" — instead of only the
existing recommendations drawn from the whole collection.

"Similar" stays **collaborative and album-level**, matching the rest of the app:
similarity comes from overlapping fan ownership, not audio analysis or genre.
The list is **pure discovery** — only albums the user does not already own.

This is purely additive. The existing whole-collection view is unchanged, and a
run produces it exactly as before; the per-record data and view are extra.

## Decisions

- **Basis of similarity:** collaborative, album-level. For a seed record, its
  "fans" are that record's Bandcamp supporters; candidates are other albums
  those fans own.
- **Interaction:** browse in the HTML page. The user picks any owned record from
  a clickable list and sees its similar albums, ranked instantly in the browser.
  No CLI flag, no per-record re-run.
- **Candidates:** only albums the user does **not** own (pure discovery),
  consistent with the global view.
- **No new crawling:** per-record data is built from the same cache a full run
  already populates. The only pipeline change is *keeping* the seed→supporters
  link that is currently discarded when fans are pooled.
- **Scoring is unchanged math:** each fan's weight is their *global* affinity
  (how many of the user's whole collection they own), capped by `affinity_cap`.
  A record's recommendations therefore favor albums bought by fans who both
  bought this record and broadly share the user's taste.
- **Reuse over rebuild:** per-record pools are produced by the existing
  `score.candidate_pool`, and the page ranks them with the existing client-side
  re-rank engine and controls.

## Architecture

```
bandcamp_reco/
  main.py        change: keep seed_supporters map; build per-record pools;
                 run Apple Music lookups over the deduped candidate set
  score.py       reuse candidate_pool on a per-seed filtered fan dict
                 (optional thin helper to build all per-record pools)
  render.py      embed OWNED / ALBUMS / BYRECORD; add the "By record" view and
                 a currentPool() accessor the existing engine reads from
  config.py      extend: per_record_pool_size, per_record_min_fans
```

### Pipeline change (`main.py`)

Today `run()` pools all supporters into a flat list and discards which seed
record each came from. Keep that link as the crawl proceeds:

```
seed_supporters: { ownedRecordKey -> [supporter usernames] }   # new
supporter_usernames = dedup(union of seed_supporters values)   # as today, for fetching
```

Fan collections are still fetched once per fan via `get_fan_collections`
(unchanged). Then, for each owned record, build a per-record pool by reusing
`candidate_pool` over only that record's fans:

```
sub_fans = { u: fan_albums[u] for u in seed_supporters[key] if u in fan_albums }
pool_for_record = candidate_pool(
    owned_keys, sub_fans, get_tags=…,
    min_fans=config.per_record_min_fans, pool_size=config.per_record_pool_size,
)
```

No new scoring logic: `candidate_pool` already excludes owned albums and weights
each fan by their affinity against the whole `owned_keys` set.

### Embed shape (normalized)

To keep the page from bloating, embedded data is normalized so each candidate
album appears once regardless of how many records it is similar to:

```
OWNED    = [ {key, title, artist, art, url}, … ]                 // pickable records
ALBUMS   = { albumKey: {title, artist, url, art, source, tags, apple…} }  // each candidate once
BYRECORD = { ownedKey: [ {a: albumKey, h: hist, f: fans}, … ] }  // refs into ALBUMS
```

`albumKey` is the existing album key (URL, sans query/trailing slash), which
dedups naturally and stays debuggable. Apple Music lookups run once per unique
album in `ALBUMS`, not once per seed.

The existing global `POOL` embed stays exactly as-is.

### Page UI (`render.py`)

One page, two views, a toggle at the top:

- **Whole collection** — the current view, unchanged, shown by default on open.
- **By record** — new:
  1. **Record picker** — `OWNED` as a compact clickable list (art thumb + title
     + artist) with a search box to filter a long collection by title/artist.
     Records with no usable pool are omitted; a quiet line reads "M of your N
     records have enough data."
  2. **Selected-record header** — a banner "Similar to: 〔art〕 Title — Artist"
     with a link out to Bandcamp and a "← back to my records" control.
  3. **Results + controls** — the same results list and the same control panel
     (affinity-cap, min-fans, diversity, tag filter, hide-owned-sources,
     Apple-Music availability, flag/export) operating on the selected record's
     pool.

The client's single reference to the constant `POOL` is refactored into a
`currentPool()` accessor:

- Whole collection → `currentPool = POOL` (today's behavior).
- By record → `currentPool = BYRECORD[seedKey].map(ref => ({ ...ALBUMS[ref.a],
  hist: ref.h, fans: ref.f }))`.

Everything downstream — scoring, diversity, filtering, rendering, the count
line, Apple flag export — is unchanged because it already consumes a pool array.

View state and the selected record live only in the page; no URL or storage
persistence. The page opens on the whole-collection view as today.

### "Why" text

The per-record "why" string gains seed context, e.g. "Owned by 5 fans of this
record who each share ~3 albums with you." The global view's wording is
unchanged.

## Edge cases

- **Thin/empty records** — a record is listed in `OWNED` only if its pool has
  ≥1 candidate; the rest are omitted. The picker shows "M of your N records have
  enough data."
- **`--limit N` runs** — only the first N records are crawled, so only those can
  appear. The view notes this so partial data is not mistaken for complete.
- **`max_fans` cap** — some records' supporters may not have had collections
  fetched under the global fan cap, yielding thinner pools. Same limitation as
  the global view; no special handling.
- **Empty after filtering** — reuses the existing "no results" empty state.
- **Apple Music disabled** — `ALBUMS` omits the apple fields; the page renders
  without them, exactly as today.

## Config additions (`config.toml`)

- `per_record_pool_size` (default **60**) — max candidates embedded per record;
  the main lever on page size.
- `per_record_min_fans` (default **2**) — min fans who must own a candidate for
  it to appear in a record's list.

## Size

With normalization the page is expected to grow from ~114KB to roughly
1–1.5MB — a local file that opens fine in a browser. If it grows too large,
lower `per_record_pool_size`.

## Testing

- **`score.py`** — restricting `candidate_pool` to one seed's fans yields the
  expected candidates and histograms, excludes owned albums, and respects
  `per_record_min_fans`.
- **`main.py`** — `seed_supporters` is built correctly; the union dedup for
  fetching is unchanged; the per-record structure is assembled; Apple Music
  lookups run once per unique album.
- **`render.py`** — `OWNED` / `ALBUMS` / `BYRECORD` serialize and `</`-escape
  safely; the by-record scaffolding and toggle are present; existing
  global-view tests stay green.
- **Smoke** — a record with no candidates is excluded from `OWNED`.

## Out of scope

- Audio/genre-based similarity ("sounds like"). Collaborative only.
- Track-level (individual song) recommendations. Album/release level only.
- Showing albums the user already owns within a record's list.
- A CLI flag to focus one record, or per-record persisted/separate pages.
