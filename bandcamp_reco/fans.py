from .collection import get_collection
from .fetch import CircuitBreakerTripped


def get_fan_collections(usernames, fetcher, cache, max_fans, max_albums_per_fan):
    result = {}
    seen = set()
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
    return result
