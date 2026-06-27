import pytest
from bandcamp_reco.fetch import Fetcher, CircuitBreakerTripped


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self._responses.pop(0)

    def post(self, url, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("bandcamp_reco.fetch.time.sleep", lambda *_: None)
    monkeypatch.setattr("bandcamp_reco.fetch.random.uniform", lambda *_: 0.0)


def test_get_returns_response_on_200():
    session = FakeSession([FakeResponse(200, text="ok")])
    f = Fetcher(session=session)
    resp = f.get("http://x")
    assert resp.text == "ok"
    assert session.calls == 1


def test_retries_on_500_then_succeeds():
    session = FakeSession([FakeResponse(500), FakeResponse(200, text="ok")])
    f = Fetcher(session=session)
    assert f.get("http://x").text == "ok"
    assert session.calls == 2


def test_circuit_breaker_trips_after_two_consecutive_429():
    session = FakeSession([FakeResponse(429), FakeResponse(429)])
    f = Fetcher(session=session, breaker_threshold=2)
    with pytest.raises(CircuitBreakerTripped):
        f.get("http://x")


def test_429_counter_resets_on_success():
    session = FakeSession([FakeResponse(429), FakeResponse(200, text="ok"),
                           FakeResponse(429), FakeResponse(200, text="ok2")])
    f = Fetcher(session=session, breaker_threshold=2)
    assert f.get("http://x").text == "ok"
    assert f.get("http://y").text == "ok2"


def test_post_json_returns_parsed_body():
    session = FakeSession([FakeResponse(200, json_data={"items": []})])
    f = Fetcher(session=session)
    assert f.post_json("http://x", {"q": 1}) == {"items": []}
