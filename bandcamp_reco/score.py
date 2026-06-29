from dataclasses import dataclass

from .models import Album, album_key, album_source


@dataclass
class Recommendation:
    album: Album
    score: float
    fan_count: int
    typical_shared: int
    why: str


def _why(count: int, typical: int) -> str:
    alb_word = "album" if typical == 1 else "albums"
    if count == 1:
        head = "1 fan who shares"
    else:
        head = f"{count} fans who each share"
    return f"Owned by {head} ~{typical} {alb_word} with your collection."


def _aggregate(owned_keys, fan_albums):
    """Map each candidate album (one you don't own) to the list of affinities of
    the fans who own it. affinity(fan) = how many of YOUR albums they also own.
    Each fan contributes to a candidate at most once (per-fan dedup)."""
    fan_key_album = {}
    affinity = {}
    for fan, albums in fan_albums.items():
        key_to_album = {}
        for a in albums:
            key_to_album.setdefault(album_key(a), a)
        fan_key_album[fan] = key_to_album
        affinity[fan] = len(set(key_to_album) & owned_keys)

    agg: dict[str, dict] = {}
    for fan, key_to_album in fan_key_album.items():
        for k, album in key_to_album.items():
            if k in owned_keys:
                continue
            entry = agg.setdefault(k, {"album": album, "shared": []})
            entry["shared"].append(affinity[fan])
    return agg


def _score(shared: list[int], affinity_cap: int) -> float:
    # Sum of per-fan weights, each capped so one very-overlapping fan can't
    # dominate; summing across fans rewards broad consensus.
    return float(sum(min(a, affinity_cap) for a in shared))


def score_candidates(
    owned_keys: set[str],
    fan_albums: dict[str, list[Album]],
    top_n: int,
    affinity_cap: int = 4,
    max_per_source: int = 2,
) -> list[Recommendation]:
    recs = []
    for entry in _aggregate(owned_keys, fan_albums).values():
        shared = entry["shared"]
        count = len(shared)
        typical = round(sum(shared) / count) if count else 0
        recs.append(Recommendation(
            album=entry["album"], score=_score(shared, affinity_cap),
            fan_count=count, typical_shared=typical, why=_why(count, typical),
        ))
    recs.sort(key=lambda r: (r.score, r.fan_count), reverse=True)
    return _diversify(recs, top_n, max_per_source)


def _diversify(recs, top_n, max_per_source):
    """Take the highest-scored recommendations, but at most max_per_source per
    Bandcamp source (label/artist), so one label can't flood the list. If the
    diversity pass leaves us short of top_n, backfill with the best leftovers."""
    if max_per_source <= 0:
        return recs[:top_n]
    selected, deferred = [], []
    per_source: dict[str, int] = {}
    for rec in recs:
        if len(selected) >= top_n:
            break
        src = album_source(rec.album.url)
        if per_source.get(src, 0) < max_per_source:
            selected.append(rec)
            per_source[src] = per_source.get(src, 0) + 1
        else:
            deferred.append(rec)
    for rec in deferred:
        if len(selected) >= top_n:
            break
        selected.append(rec)
    return selected


def candidate_pool(owned_keys, fan_albums, get_tags=None, min_fans=2, pool_size=400):
    """Build the data the interactive HTML page re-ranks client-side: for each
    candidate (owned by >= min_fans fans), the album metadata plus a histogram
    of owner affinities (affinity -> number of fans). The browser can then
    recompute scores for any affinity_cap without re-running the pipeline.

    get_tags(url) -> tuple[str, ...] | None is an optional callback for tags
    (e.g. read from cache); falls back to the album's own tags."""
    items = []
    for entry in _aggregate(owned_keys, fan_albums).values():
        shared = entry["shared"]
        if len(shared) < min_fans:
            continue
        album = entry["album"]
        hist: dict[int, int] = {}
        for a in shared:
            hist[a] = hist.get(a, 0) + 1
        tags = list(album.tags)
        if get_tags is not None:
            fetched = get_tags(album.url)
            if fetched:
                tags = list(fetched)
        items.append({
            "title": album.title,
            "artist": album.artist,
            "url": album.url,
            "art": album.art_url or "",
            "source": album_source(album.url),
            "tags": tags,
            "hist": {str(k): v for k, v in hist.items()},
            "fans": len(shared),
        })
    items.sort(key=lambda d: d["fans"], reverse=True)
    return items[:pool_size]


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
