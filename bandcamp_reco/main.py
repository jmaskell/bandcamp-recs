import argparse
import dataclasses

from .cache import Cache
from .collection import get_collection
from .config import load_config
from .fetch import Fetcher, CircuitBreakerTripped
from .models import album_key
from .render import render_html, write_html
from .score import score_candidates
from .supporters import get_supporters, get_album_page


def run(config, fetcher, cache, limit=None):
    owned = get_collection(config.username, fetcher, cache, max_items=limit)
    owned_keys = {album_key(a) for a in owned}

    # collect candidate supporters across owned albums
    supporter_usernames = []
    try:
        for album in owned:
            supporter_usernames.extend(
                get_supporters(album, fetcher, cache,
                               limit=config.supporters_per_album)
            )
    except CircuitBreakerTripped:
        pass  # proceed with whatever we gathered; cache holds progress

    # collect fan albums directly so get_collection remains monkeypatchable
    fan_albums = {}
    seen: set[str] = set()
    for username in supporter_usernames:
        if len(fan_albums) >= config.max_fans:
            break
        if username in seen:
            continue
        seen.add(username)
        try:
            albums = get_collection(
                username, fetcher, cache, max_items=config.max_albums_per_fan
            )
        except CircuitBreakerTripped:
            break
        except Exception:
            continue
        fan_albums[username] = albums

    recs = score_candidates(owned_keys, fan_albums, top_n=config.top_n)
    recs = _enrich_tags(recs, fetcher, cache)

    html = render_html(recs, username=config.username)
    write_html(html, config.output_path)
    return recs


def _enrich_tags(recs, fetcher, cache):
    enriched = []
    for rec in recs:
        try:
            info = get_album_page(rec.album, fetcher, cache)
            album = dataclasses.replace(rec.album, tags=tuple(info.tags))
            enriched.append(dataclasses.replace(rec, album=album))
        except Exception:
            enriched.append(rec)
    return enriched


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bandcamp recommendations")
    parser.add_argument("--config", default=None)
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None,
                        help="dry run: cap owned albums processed")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.top_n is not None:
        config = dataclasses.replace(config, top_n=args.top_n)

    cache = Cache(config.cache_path)
    fetcher = Fetcher(delay=config.request_delay)
    try:
        recs = run(config, fetcher, cache, limit=args.limit)
    finally:
        cache.close()
    print(f"Wrote {len(recs)} recommendations to {config.output_path}")
    return 0
