from dataclasses import dataclass


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
