import json

from bs4 import BeautifulSoup

from .models import Album, art_url_from_id

COLLECTION_API = "https://bandcamp.com/api/fancollection/1/collection_items"
PROFILE_URL = "https://bandcamp.com/{username}"


def parse_pagedata_blob(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(id="pagedata")
    if node is None or not node.get("data-blob"):
        return {}
    return json.loads(node["data-blob"])


def _is_album(raw: dict) -> bool:
    return (raw.get("item_type") or raw.get("tralbum_type")) in ("album", "a")


def raw_to_album(raw: dict) -> Album | None:
    if not _is_album(raw):
        return None
    art = raw.get("item_art_id") or raw.get("art_id")
    return Album(
        item_id=str(raw.get("item_id") or raw.get("tralbum_id") or raw.get("id") or ""),
        album_id=str(raw["album_id"]) if raw.get("album_id") else None,
        title=raw.get("item_title") or raw.get("title") or "",
        artist=raw.get("band_name") or "",
        url=raw.get("item_url") or raw.get("url") or "",
        art_url=art_url_from_id(art),
    )


def _albums_from_item_cache(blob: dict) -> list[Album]:
    cache = (blob.get("item_cache") or {}).get("collection") or {}
    out = []
    for raw in cache.values():
        album = raw_to_album(raw)
        if album:
            out.append(album)
    return out


def get_collection(username, fetcher, cache, max_items=None) -> list[Album]:
    blob = _load_profile_blob(username, fetcher, cache)
    if not blob:
        return []
    fan_id = (blob.get("fan_data") or {}).get("fan_id")
    albums = _albums_from_item_cache(blob)
    cdata = blob.get("collection_data") or {}
    token = cdata.get("last_token")
    item_count = cdata.get("item_count", len(albums))
    while (token and fan_id and len(albums) < item_count
           and (max_items is None or len(albums) < max_items)):
        page = fetcher.post_json(
            COLLECTION_API,
            {"fan_id": fan_id, "older_than_token": token, "count": 50},
        )
        new = [raw_to_album(r) for r in page.get("items", [])]
        albums.extend(a for a in new if a)
        token = page.get("last_token")
        if not page.get("more_available"):
            break
    if max_items is not None:
        albums = albums[:max_items]
    return albums


def _load_profile_blob(username, fetcher, cache) -> dict:
    cached = cache.get("profile_blob", username)
    if cached is not None:
        return cached
    html = fetcher.get(PROFILE_URL.format(username=username)).text
    blob = parse_pagedata_blob(html)
    cache.set("profile_blob", username, blob)
    return blob
