import os
import tomllib
from dataclasses import dataclass


@dataclass
class AppleMusicConfig:
    enabled: bool
    country: str
    request_delay: float


@dataclass
class Config:
    username: str
    supporters_per_album: int
    max_fans: int
    max_albums_per_fan: int
    top_n: int
    request_delay: float
    cache_path: str
    output_path: str
    affinity_cap: int
    max_per_source: int
    hide_owned_sources: bool
    apple_music: AppleMusicConfig | None = None


DEFAULTS = {
    "username": "jmaskell",
    "supporters_per_album": 30,
    "max_fans": 500,
    "max_albums_per_fan": 200,
    "top_n": 50,
    "request_delay": 0.7,
    "cache_path": "cache.db",
    "output_path": "recommendations.html",
    "affinity_cap": 4,
    "max_per_source": 2,
    "hide_owned_sources": False,
}


def _parse_apple(section) -> AppleMusicConfig | None:
    # `section is None` means no [apple_music] table at all; an empty table
    # parses to {} (falsy) but should still yield a default-enabled config.
    if section is None or not section.get("enabled", True):
        return None
    return AppleMusicConfig(
        enabled=bool(section.get("enabled", True)),
        country=section.get("country", "gb"),
        request_delay=float(section.get("request_delay", 3.0)),
    )


def load_config(path: str | None = None) -> Config:
    values = dict(DEFAULTS)
    raw: dict = {}
    path = path or "config.toml"
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        values.update(raw)
    base = {k: values[k] for k in DEFAULTS}
    return Config(apple_music=_parse_apple(raw.get("apple_music")), **base)
