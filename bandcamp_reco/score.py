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


def score_candidates(
    owned_keys: set[str],
    fan_albums: dict[str, list[Album]],
    top_n: int,
    affinity_cap: int = 4,
    max_per_source: int = 2,
) -> list[Recommendation]:
    # per-fan deduplicated key -> first Album seen with that key
    fan_key_album = {}
    affinity = {}
    for fan, albums in fan_albums.items():
        key_to_album = {}
        for a in albums:
            key_to_album.setdefault(album_key(a), a)
        fan_key_album[fan] = key_to_album
        # affinity per fan = how many of YOUR albums they also own
        affinity[fan] = len(set(key_to_album) & owned_keys)

    # Aggregate candidates (albums you don't own); each fan counts once per key.
    # A fan's contribution is capped at affinity_cap so a few very-overlapping
    # "friends" can't dominate; summing capped weights across distinct fans
    # rewards broad consensus over a single enthusiastic endorsement.
    agg: dict[str, dict] = {}
    for fan, key_to_album in fan_key_album.items():
        weight = min(affinity[fan], affinity_cap)
        for k, album in key_to_album.items():
            if k in owned_keys:
                continue
            entry = agg.setdefault(
                k, {"album": album, "score": 0.0, "count": 0, "shared": []}
            )
            entry["score"] += weight
            entry["count"] += 1
            entry["shared"].append(affinity[fan])

    recs = []
    for entry in agg.values():
        count = entry["count"]
        typical = round(sum(entry["shared"]) / count) if count else 0
        recs.append(Recommendation(
            album=entry["album"], score=float(entry["score"]), fan_count=count,
            typical_shared=typical, why=_why(count, typical),
        ))

    # Highest score first; break ties toward broader consensus.
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
