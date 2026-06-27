import random
import time

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


class CircuitBreakerTripped(Exception):
    pass


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, delay=0.7, jitter=0.3, max_retries=4,
                 breaker_threshold=2, backoff_ceiling=30.0, session=None):
        self.delay = delay
        self.jitter = jitter
        self.max_retries = max_retries
        self.breaker_threshold = breaker_threshold
        self.backoff_ceiling = backoff_ceiling
        self._session = session or requests.Session()
        self._consecutive_429 = 0

    def get(self, url: str, **kwargs):
        return self._request("get", url, **kwargs)

    def post_json(self, url: str, json_body: dict) -> dict:
        resp = self._request("post", url, json=json_body)
        return resp.json()

    def _throttle(self):
        time.sleep(self.delay + random.uniform(0.0, self.jitter))

    def _backoff(self, attempt):
        time.sleep(min(self.delay * (2 ** attempt), self.backoff_ceiling))

    def _request(self, method_name, url, **kwargs):
        method = getattr(self._session, method_name)
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        for attempt in range(self.max_retries + 1):
            self._throttle()
            resp = method(url, headers=headers, **kwargs)
            if resp.status_code == 429:
                self._consecutive_429 += 1
                if self._consecutive_429 >= self.breaker_threshold:
                    raise CircuitBreakerTripped(
                        f"{self._consecutive_429} consecutive 429s; stopping"
                    )
                self._backoff(attempt)
                continue
            if 500 <= resp.status_code < 600:
                self._consecutive_429 = 0
                self._backoff(attempt)
                continue
            self._consecutive_429 = 0
            resp.raise_for_status()
            return resp
        raise FetchError(f"exhausted retries for {url}")
