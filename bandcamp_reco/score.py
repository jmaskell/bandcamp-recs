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


def score_candidates(owned_keys, fan_albums, top_n) -> list[Recommendation]:
    # affinity per fan = how many of YOUR albums they also own
    affinity = {}
    fan_keys = {}
    for fan, albums in fan_albums.items():
        keys = {album_key(a) for a in albums}
        fan_keys[fan] = keys
        affinity[fan] = len(keys & owned_keys)

    # aggregate candidates (albums you don't own)
    agg: dict[str, dict] = {}
    for fan, albums in fan_albums.items():
        for album in albums:
            k = album_key(album)
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
