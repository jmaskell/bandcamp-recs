from dataclasses import dataclass

from bs4 import BeautifulSoup

from .collection import parse_pagedata_blob
from .models import Album


@dataclass
class AlbumPageInfo:
    tralbum_id: str | None
    tags: tuple[str, ...]
    supporter_usernames: list[str]


def parse_album_page(html: str) -> AlbumPageInfo:
    blob = parse_pagedata_blob(html)
    tralbum_id = blob.get("tralbum_id") or blob.get("id")
    if tralbum_id is not None:
        tralbum_id = str(tralbum_id)

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
            supporter_usernames=list(cached["supporter_usernames"]),
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
    return info.supporter_usernames[:limit]
