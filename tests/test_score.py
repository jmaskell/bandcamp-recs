from bandcamp_reco.models import Album, album_key, album_source
from bandcamp_reco.score import score_candidates, Recommendation


def _album(url):
    return Album(item_id=url, album_id=None, title=url.split("/")[-1],
                 artist="A", url=url, art_url=None)


OWNED = {f"https://own{i}.bandcamp.com/album/o" for i in range(20)}
OWNED_ALBUMS = [_album(u) for u in OWNED]
OWNED_LIST = sorted(OWNED)


def test_excludes_owned_albums():
    fan_albums = {"f1": OWNED_ALBUMS + [_album("https://cand.bandcamp.com/album/x")]}
    recs = score_candidates(OWNED, fan_albums, top_n=50)
    assert {album_key(r.album) for r in recs} == {"https://cand.bandcamp.com/album/x"}


def test_affinity_cap_stops_one_friend_dominating():
    """A single super-overlapping friend must not outrank a multi-fan consensus."""
    # one friend shares all 20 owned albums and owns candidate A
    superfan = OWNED_ALBUMS + [_album("https://lab.bandcamp.com/album/A")]
    # three moderately-aligned fans (share 5 each) all own candidate B
    mods = {
        f"m{i}": [_album(OWNED_LIST[j]) for j in range(5)]
                 + [_album("https://lab.bandcamp.com/album/B")]
        for i in range(3)
    }
    recs = score_candidates(OWNED, {"super": superfan, **mods},
                            top_n=10, affinity_cap=4, max_per_source=10)
    rank = [album_key(r.album) for r in recs]
    A = "https://lab.bandcamp.com/album/A"
    B = "https://lab.bandcamp.com/album/B"
    assert rank.index(B) < rank.index(A)


def test_consensus_album_ranks_above_single_fan_album():
    """Many aligned fans beats one slightly-more-aligned fan."""
    fansP = {
        f"p{i}": [_album(OWNED_LIST[j]) for j in range(3)]
                 + [_album("https://p.bandcamp.com/album/p")]
        for i in range(4)
    }
    fanQ = {"q": [_album(OWNED_LIST[j]) for j in range(4)]
                 + [_album("https://q.bandcamp.com/album/q")]}
    recs = score_candidates(OWNED, {**fansP, **fanQ},
                            top_n=10, affinity_cap=4, max_per_source=10)
    rank = [album_key(r.album) for r in recs]
    assert rank.index("https://p.bandcamp.com/album/p") < \
           rank.index("https://q.bandcamp.com/album/q")


def test_diversity_cap_limits_albums_per_source():
    """One label with many strong albums shouldn't flood the results.

    With enough other sources to fill top_n, the per-source cap holds (no
    backfill needed)."""
    label_albums = [_album(f"https://biglabel.bandcamp.com/album/{i}") for i in range(4)]
    others = [_album(f"https://indie{i}.bandcamp.com/album/z") for i in range(3)]
    fans = {
        f"f{i}": [_album(OWNED_LIST[j]) for j in range(4)] + label_albums + others
        for i in range(5)
    }
    recs = score_candidates(OWNED, fans, top_n=5, affinity_cap=4, max_per_source=2)
    sources = [album_source(r.album.url) for r in recs]
    assert sources.count("biglabel") == 2          # capped, not flooding all 5
    assert len([s for s in sources if s != "biglabel"]) == 3  # filled by others


def test_diversity_backfills_when_short_of_top_n():
    """If diversity leaves us short of top_n, backfill with the best leftovers."""
    label_albums = [_album(f"https://only.bandcamp.com/album/{i}") for i in range(5)]
    fans = {
        f"f{i}": [_album(OWNED_LIST[j]) for j in range(4)] + label_albums
        for i in range(3)
    }
    recs = score_candidates(OWNED, fans, top_n=5, affinity_cap=4, max_per_source=2)
    # only one source exists; we must still return all 5 (backfilled past the cap)
    assert len(recs) == 5


def test_dedup_same_candidate_twice_counts_once():
    # one fan owns all owned albums + the SAME candidate listed twice
    fan_albums = {"f1": OWNED_ALBUMS + [_album("https://c.bandcamp.com/album/x"),
                                        _album("https://c.bandcamp.com/album/x")]}
    recs = score_candidates(OWNED, fan_albums, top_n=10, affinity_cap=4)
    rec = next(r for r in recs if album_key(r.album) == "https://c.bandcamp.com/album/x")
    assert rec.fan_count == 1   # one fan, not double-counted
    assert rec.score == 4.0     # affinity 20, capped at 4, counted once


def test_recommendation_fields_use_capped_score():
    fan_albums = {
        "f1": [_album(OWNED_LIST[j]) for j in range(5)]
              + [_album("https://c.bandcamp.com/album/x")],
        "f2": [_album(OWNED_LIST[j]) for j in range(3)]
              + [_album("https://c.bandcamp.com/album/x")],
    }
    recs = score_candidates(OWNED, fan_albums, top_n=10, affinity_cap=4)
    rec = next(r for r in recs if r.album.url == "https://c.bandcamp.com/album/x")
    assert isinstance(rec, Recommendation)
    assert rec.fan_count == 2
    # affinities 5 and 3, each capped at 4 -> 4 + 3 = 7
    assert rec.score == 7.0
    assert rec.typical_shared == 4  # round(mean([5, 3]))
    assert "2 fans who each share ~4 albums" in rec.why


def test_why_grammar_singular():
    fan_albums = {"f1": [_album(OWNED_LIST[0]),
                         _album("https://c.bandcamp.com/album/x")]}
    recs = score_candidates(OWNED, fan_albums, top_n=5)
    assert recs[0].why == "Owned by 1 fan who shares ~1 album with your collection."
