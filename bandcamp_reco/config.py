import os
import tomllib
from dataclasses import dataclass


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


DEFAULTS = {
    "username": "jmaskell",
    "supporters_per_album": 30,
    "max_fans": 500,
    "max_albums_per_fan": 200,
    "top_n": 50,
    "request_delay": 0.7,
    "cache_path": "cache.db",
    "output_path": "recommendations.html",
}


def load_config(path: str | None = None) -> Config:
    values = dict(DEFAULTS)
    path = path or "config.toml"
    if os.path.exists(path):
        with open(path, "rb") as f:
            values.update(tomllib.load(f))
    return Config(**{k: values[k] for k in DEFAULTS})
