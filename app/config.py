"""
Config loader — reads config.yaml and returns it as a dict.
Called at the top of every service function so changes to
config.yaml take effect immediately without restarting.
"""

import yaml
from pathlib import Path
from functools import lru_cache
import time

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
_cache: dict = {}
_cache_mtime: float = 0.0


def get_config() -> dict:
    """Return the current config, reloading from disk if the file changed."""
    global _cache, _cache_mtime
    mtime = CONFIG_PATH.stat().st_mtime
    if mtime != _cache_mtime:
        with open(CONFIG_PATH, "r") as f:
            _cache = yaml.safe_load(f)
        _cache_mtime = mtime
    return _cache


def get_need(need_key: str) -> dict:
    """Shortcut to fetch a single need's config block."""
    return get_config()["needs"][need_key]


def get_object(object_key: str) -> dict:
    """Shortcut to fetch a single object's config block."""
    return get_config()["objects"][object_key]


def get_vibe(vibe_key: str) -> dict:
    """Shortcut to fetch a single vibe's config block."""
    return get_config()["vibes"][vibe_key]


def get_skill(skill_key: str) -> dict:
    """Shortcut to fetch a single skill's config block."""
    return get_config()["skills"][skill_key]


def all_need_keys() -> list[str]:
    return list(get_config()["needs"].keys())


def all_skill_keys() -> list[str]:
    return list(get_config()["skills"].keys())
