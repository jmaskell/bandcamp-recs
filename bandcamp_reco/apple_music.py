import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

TITLE_THRESHOLD = 0.85
ARTIST_THRESHOLD = 0.85
_COMPILATION_ARTISTS = {"various artists", "various", "va", ""}

_BRACKETS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_SUFFIX = re.compile(r"\s*[-–—]\s*(ep|single|lp)\s*$")
_NONALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class AppleMatch:
    status: str            # "available" | "unavailable"
    url: str | None
    name: str | None
    artist: str | None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Decompose ligatures that NFKD doesn't fully handle
    text = text.replace('æ', 'ae')  # LATIN SMALL LETTER AE
    text = text.replace('œ', 'oe')  # LATIN SMALL LIGATURE OE
    text = text.lower()
    text = _BRACKETS.sub("", text)
    text = _SUFFIX.sub("", text)
    text = _NONALNUM.sub(" ", text)
    return text.strip()


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def match_album(artist: str, title: str, results: list[dict]) -> AppleMatch:
    want_artist = normalize(artist)
    want_title = normalize(title)
    is_comp = want_artist in _COMPILATION_ARTISTS

    best = None
    best_score = 0.0
    best_collection_len = float('inf')  # Tie-breaker: prefer shorter collection names (exact matches)

    for r in results:
        title_score = _ratio(want_title, normalize(r.get("collectionName", "")))
        if title_score < TITLE_THRESHOLD:
            continue
        if is_comp:
            artist_score = 0.0
        else:
            artist_score = _ratio(want_artist, normalize(r.get("artistName", "")))
            if artist_score < ARTIST_THRESHOLD:
                continue
        combined = title_score + artist_score
        collection_name = r.get("collectionName", "")
        collection_len = len(collection_name)

        # Pick if score is better, or if score is same but collection name is shorter (exact match)
        if combined > best_score or (combined == best_score and collection_len < best_collection_len):
            best_score = combined
            best = r
            best_collection_len = collection_len

    if best is None:
        return AppleMatch(status="unavailable", url=None, name=None, artist=None)
    return AppleMatch(
        status="available",
        url=best.get("collectionViewUrl"),
        name=best.get("collectionName"),
        artist=best.get("artistName"),
    )
