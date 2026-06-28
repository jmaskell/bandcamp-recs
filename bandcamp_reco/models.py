from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Album:
    item_id: str
    album_id: str | None
    title: str
    artist: str
    url: str
    art_url: str | None
    tags: tuple[str, ...] = ()


def album_key(album: "Album") -> str:
    return album.url.split("?")[0].rstrip("/")


def art_url_from_id(art_id) -> str | None:
    if not art_id:
        return None
    return f"https://f4.bcbits.com/img/a{art_id}_16.jpg"


def album_source(url: str) -> str:
    """The album's label/artist source on Bandcamp: the subdomain of a
    `<source>.bandcamp.com` URL (e.g. 'kompakt'), or the full host for a
    custom domain. Used to keep one label/artist from flooding results."""
    host = urlparse(url).netloc.lower()
    suffix = ".bandcamp.com"
    if host.endswith(suffix):
        return host[: -len(suffix)]
    return host
