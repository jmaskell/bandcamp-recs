from .collection import get_collection
from .fetch import CircuitBreakerTripped
from .progress import NULL_REPORTER


def get_fan_collections(usernames, fetcher, cache, max_fans, max_albums_per_fan,
                        reporter=NULL_REPORTER):
    result = {}
    seen = set()
    with reporter.bar(max_fans, "Reading fan collections") as bar:
        for username in usernames:
            if len(result) >= max_fans:
                break
            if username in seen:
                continue
            seen.add(username)
            try:
                albums = get_collection(
                    username, fetcher, cache, max_items=max_albums_per_fan
                )
            except CircuitBreakerTripped:
                break
            except Exception:
                continue
            result[username] = albums
            bar.update()  # counts fans actually fetched (not every username considered)
    return result
