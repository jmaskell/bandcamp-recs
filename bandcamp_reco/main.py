import argparse
import dataclasses
import sys

from .apple_music import AppleMusicClient, lookup_pool
from .cache import Cache
from .collection import get_collection
from .config import load_config
from .fans import get_fan_collections
from .fetch import Fetcher, CircuitBreakerTripped
from .models import album_key, album_source, album_key_from_url
from .render import render_html, write_html
from .score import score_candidates, candidate_pool
from .supporters import get_supporters, get_album_page, cached_tags


def _apply_apple_music(config, pool, cache) -> bool:
    if config.apple_music is None:
        return False
    try:
        client = AppleMusicClient(delay=config.apple_music.request_delay)
        results = lookup_pool(pool, client, cache, config.apple_music.country)
    except Exception as exc:
        print(f"Apple Music: disabled ({exc})", file=sys.stderr)
        return False
    for item in pool:
        match = results.get(album_key_from_url(item["url"]))
        if match is None:
            item["apple"] = "unknown"
        elif match.status == "available":
            item["apple"] = "available"
            item["appleUrl"] = match.url or ""
            item["appleName"] = match.name or ""
            item["appleArtist"] = match.artist or ""
        else:
            item["apple"] = "unavailable"
    return True


def run(config, fetcher, cache, limit=None):
    try:
        owned = get_collection(config.username, fetcher, cache)
    except CircuitBreakerTripped:
        owned = []
    owned_keys = {album_key(a) for a in owned}

    # --limit bounds only the (expensive) supporter crawl, NOT the exclusion
    # set above. Truncating owned_keys would let albums you own leak back in
    # as recommendations.
    crawl_albums = owned if limit is None else owned[:limit]

    # collect candidate supporters across the crawled owned albums
    supporter_usernames = []
    for album in crawl_albums:
        try:
            supporter_usernames.extend(
                get_supporters(album, fetcher, cache,
                               limit=config.supporters_per_album)
            )
        except CircuitBreakerTripped:
            break
        except Exception:
            continue

    # You are a supporter of your own albums; never sample yourself as a fan
    # (your collection is all owned, and would otherwise dominate the results).
    supporter_usernames = [u for u in supporter_usernames if u != config.username]

    fan_albums = get_fan_collections(
        supporter_usernames, fetcher, cache,
        max_fans=config.max_fans,
        max_albums_per_fan=config.max_albums_per_fan,
    )

    recs = score_candidates(
        owned_keys, fan_albums, top_n=config.top_n,
        affinity_cap=config.affinity_cap,
        max_per_source=config.max_per_source,
    )
    # Fetch+cache tags for the default top picks so the initial view is tag-rich.
    recs = _enrich_tags(recs, fetcher, cache)

    # The page re-ranks this candidate pool client-side from its controls.
    pool = candidate_pool(
        owned_keys, fan_albums,
        get_tags=lambda u: cached_tags(u, cache),
        min_fans=2, pool_size=400,
    )
    defaults = {
        "affinity_cap": config.affinity_cap,
        "max_per_source": config.max_per_source,
        "top_n": config.top_n,
        "min_fans": 2,
        "hide_owned_sources": config.hide_owned_sources,
    }
    # Labels/artists (Bandcamp sources) you already own music from, so the page
    # can offer to filter them out for pure discovery.
    owned_sources = sorted({album_source(a.url) for a in owned})
    apple_enabled = _apply_apple_music(config, pool, cache)
    html = render_html(pool, username=config.username, defaults=defaults,
                       owned_sources=owned_sources, apple_enabled=apple_enabled)
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
                        help="faster sample: crawl supporters for only the first "
                             "N owned albums (your full collection is still "
                             "excluded from results)")
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
    print(f"Wrote recommendations to {config.output_path} "
          f"(open it and adjust the controls to re-rank)")
    return 0
