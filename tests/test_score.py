import math
from bandcamp_reco.models import Album, album_key
from bandcamp_reco.score import score_candidates, Recommendation


def _album(url):
    return Album(item_id=url, album_id=None, title=url.split("/")[-1],
                 artist="A", url=url, art_url=None)


OWNED = {f"https://own/{i}" for i in range(10)}


def test_excludes_owned_albums():
    owned_albums = [_album(u) for u in OWNED]
    fan_albums = {"f1": owned_albums + [_album("https://cand/x")]}
    recs = score_candidates(OWNED, fan_albums, top_n=50)
    keys = {album_key(r.album) for r in recs}
    assert keys == {"https://cand/x"}


def test_high_affinity_niche_beats_popular_low_affinity():
    owned = [_album(u) for u in OWNED]
    # superfan shares all 10 owned albums, owns niche candidate N
    superfan = owned + [_album("https://cand/N")]
    # three dr-ive-by fans each share only 1 owned album, all own popular P
    drivebys = {
        f"d{i}": [_album("https://own/0"), _album("https://cand/P")]
        for i in range(3)
    }
    fan_albums = {"super": superfan, **drivebys}
    recs = score_candidates(OWNED, fan_albums, top_n=10)
    ranked = [album_key(r.album) for r in recs]
    assert ranked[0] == "https://cand/N"  # niche, high-affinity wins
    assert "https://cand/P" in ranked


def test_dedup_same_candidate_twice_counts_once():
    owned = [_album(u) for u in OWNED]
    # fan owns all 10 owned albums + the SAME candidate listed twice
    fan_albums = {
        "f1": owned + [_album("https://cand/x"), _album("https://cand/x")],
    }
    recs = score_candidates(OWNED, fan_albums, top_n=10)
    rec = next(r for r in recs if album_key(r.album) == "https://cand/x")
    assert rec.fan_count == 1  # one fan, not double-counted
    assert rec.score == 10 / math.sqrt(1)  # affinity 10, not 2x


def test_recommendation_fields_and_why():
    owned = [_album(u) for u in OWNED]
    fan_albums = {
        "f1": owned[:5] + [_album("https://cand/x")],
        "f2": owned[:3] + [_album("https://cand/x")],
    }
    recs = score_candidates(OWNED, fan_albums, top_n=10)
    rec = recs[0]
    assert isinstance(rec, Recommendation)
    assert rec.fan_count == 2
    # affinities 5 and 3 -> score 8, count 2 -> final 8/sqrt(2)
    assert math.isclose(rec.score, 8 / math.sqrt(2), rel_tol=1e-6)
    assert rec.typical_shared == 4  # round(mean([5,3]))
    assert "2 fans" in rec.why
