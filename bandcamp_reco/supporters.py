from dataclasses import dataclass

from bs4 import BeautifulSoup

from .collection import parse_pagedata_blob
from .models import Album

THUMBS_API = "https://bandcamp.com/api/tralbumcollectors/2/thumbs"


@dataclass
class AlbumPageInfo:
    tralbum_id: str | None
    tags: tuple[str, ...]
    supporter_usernames: list[str]


def parse_album_page(html: str) -> AlbumPageInfo:
    blob = parse_pagedata_blob(html)
    # Live site uses 'album_id' at the top level as the numeric tralbum id.
    # Fall back to 'tralbum_id' / 'id' for backwards compatibility.
    tralbum_id = blob.get("album_id") or blob.get("tralbum_id") or blob.get("id")
    if tralbum_id is not None:
        tralbum_id = str(tralbum_id)

    # Supporters are no longer embedded in the page data-blob on the live site;
    # they are fetched via the tralbumcollectors thumbs API in get_supporters().
    # Keep this loop so fixture-based tests and any future page changes still work.
    supporters = []
    for s in blob.get("supporters") or []:
        name = s.get("username") or s.get("name")
        if name:
            supporters.append(name)

    soup = BeautifulSoup(html, "html.parser")
    tags = tuple(
        a.get_text(strip=True)
        for a in soup.select("a.tag")
        if a.get_text(strip=True)
    )
    return AlbumPageInfo(tralbum_id=tralbum_id, tags=tags,
                         supporter_usernames=supporters)


def get_album_page(album: Album, fetcher, cache) -> AlbumPageInfo:
    cached = cache.get("album_page", album.url)
    if cached is not None:
        return AlbumPageInfo(
            tralbum_id=cached["tralbum_id"],
            tags=tuple(cached["tags"]),
            supporter_usernames=list(cached.get("supporter_usernames", [])),
        )
    html = fetcher.get(album.url).text
    info = parse_album_page(html)
    cache.set("album_page", album.url, {
        "tralbum_id": info.tralbum_id,
        "tags": list(info.tags),
        "supporter_usernames": info.supporter_usernames,
    })
    return info


def get_supporters(album: Album, fetcher, cache, limit: int) -> list[str]:
    info = get_album_page(album, fetcher, cache)
    # If the page embed included supporters (legacy path), use them directly.
    if info.supporter_usernames:
        return info.supporter_usernames[:limit]
    # Otherwise fetch from the tralbumcollectors thumbs API.
    if not info.tralbum_id:
        return []
    cache_key = f"{album.url}#{limit}"
    cached = cache.get("supporters", cache_key)
    if cached is not None:
        return cached
    resp = fetcher.post_json(
        THUMBS_API,
        {"tralbum_type": "a", "tralbum_id": int(info.tralbum_id), "count": limit},
    )
    usernames = [
        r["username"] for r in ((resp or {}).get("results") or []) if r.get("username")
    ][:limit]
    cache.set("supporters", cache_key, usernames)
    return usernames
