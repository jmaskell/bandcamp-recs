import math
from dataclasses import dataclass

from .models import Album, album_key


@dataclass
class Recommendation:
    album: Album
    score: float
    fan_count: int
    typical_shared: int
    why: str


def score_candidates(
    owned_keys: set[str],
    fan_albums: dict[str, list[Album]],
    top_n: int,
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

    # aggregate candidates (albums you don't own); each fan counts once per key
    agg: dict[str, dict] = {}
    for fan, key_to_album in fan_key_album.items():
        for k, album in key_to_album.items():
            if k in owned_keys:
                continue
            entry = agg.setdefault(
                k, {"album": album, "score": 0.0, "count": 0, "shared": []}
            )
            entry["score"] += affinity[fan]
            entry["count"] += 1
            entry["shared"].append(affinity[fan])

    recs = []
    for entry in agg.values():
        count = entry["count"]
        final = entry["score"] / math.sqrt(count) if count else 0.0
        typical = round(sum(entry["shared"]) / count) if count else 0
        why = (
            f"Owned by {count} fans who each share "
            f"~{typical} albums with your collection."
        )
        recs.append(Recommendation(
            album=entry["album"], score=final, fan_count=count,
            typical_shared=typical, why=why,
        ))

    recs.sort(key=lambda r: r.score, reverse=True)
    return recs[:top_n]
