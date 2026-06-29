from bandcamp_reco.apple_music import normalize, match_album, AppleMatch


def _result(name, artist, url="https://music.apple.com/gb/album/x/1"):
    return {"collectionName": name, "artistName": artist, "collectionViewUrl": url}


def test_normalize_strips_brackets_diacritics_and_punctuation():
    assert normalize("Sǽ (Deluxe Edition)") == "sae"
    assert normalize("Album - EP") == "album"
    assert normalize("A/B & C!") == "a b c"


def test_match_album_exact_match_is_available():
    results = [_result("Album X", "Artist A")]
    m = match_album("Artist A", "Album X", results)
    assert m.status == "available"
    assert m.url == "https://music.apple.com/gb/album/x/1"
    assert m.name == "Album X"
    assert m.artist == "Artist A"


def test_match_album_deluxe_edition_still_matches():
    results = [_result("Album X (Deluxe Edition)", "Artist A")]
    assert match_album("Artist A", "Album X", results).status == "available"


def test_match_album_wrong_artist_is_unavailable():
    results = [_result("Album X", "Some Other Band")]
    m = match_album("Artist A", "Album X", results)
    assert m.status == "unavailable"
    assert m.url is None


def test_match_album_no_results_is_unavailable():
    assert match_album("Artist A", "Album X", []).status == "unavailable"


def test_match_album_compilation_matches_on_title_alone():
    results = [_result("Big Compilation", "Various Artists 2024 Reissue")]
    m = match_album("Various Artists", "Big Compilation", results)
    assert m.status == "available"


def test_match_album_picks_best_of_several():
    results = [
        _result("Album X (Live)", "Artist A", "https://music.apple.com/gb/album/live/2"),
        _result("Album X", "Artist A", "https://music.apple.com/gb/album/x/1"),
    ]
    assert match_album("Artist A", "Album X", results).url == "https://music.apple.com/gb/album/x/1"
