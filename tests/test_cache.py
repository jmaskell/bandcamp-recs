from bandcamp_reco.cache import Cache


def test_get_missing_returns_none(tmp_path):
    c = Cache(str(tmp_path / "c.db"))
    assert c.get("profile", "jmaskell") is None
    c.close()


def test_set_then_get_roundtrips(tmp_path):
    c = Cache(str(tmp_path / "c.db"))
    c.set("profile", "jmaskell", {"fan_id": 42, "items": [1, 2, 3]})
    assert c.get("profile", "jmaskell") == {"fan_id": 42, "items": [1, 2, 3]}
    c.close()


def test_set_overwrites(tmp_path):
    c = Cache(str(tmp_path / "c.db"))
    c.set("ns", "k", {"v": 1})
    c.set("ns", "k", {"v": 2})
    assert c.get("ns", "k") == {"v": 2}
    c.close()


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "c.db")
    c1 = Cache(path)
    c1.set("ns", "k", {"v": 1})
    c1.close()
    c2 = Cache(path)
    assert c2.get("ns", "k") == {"v": 1}
    c2.close()
