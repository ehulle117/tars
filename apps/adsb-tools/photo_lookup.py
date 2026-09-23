#!/usr/bin/env python3
"""Look up an aircraft photo: the real one if planespotters.net has it for
this exact hex, else a representative stock photo of the aircraft type via
Wikimedia Commons search. Both results are cached on disk indefinitely -
a given aircraft/type combination has a stable answer, no point re-querying.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "photo_cache.json"
USER_AGENT = "adsb-tools/1.0 (hobby ADS-B tracker; https://github.com/ehulle117)"

_cache: dict | None = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    CACHE_PATH.write_text(json.dumps(_cache))


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _real_photo(hex_code: str) -> dict | None:
    try:
        data = _get_json(f"https://api.planespotters.net/pub/photos/hex/{hex_code}")
        photos = data.get("photos") or []
        if not photos:
            return None
        p = photos[0]
        return {
            "url": p["thumbnail_large"]["src"],
            "credit": p.get("photographer"),
            "link": p.get("link"),
            "source": "real",
        }
    except Exception:
        return None


def _stock_photo(aircraft_type: str, manufacturer: str) -> dict | None:
    query = f"{manufacturer or ''} {aircraft_type} aircraft".strip()
    try:
        params = urllib.parse.urlencode({
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrnamespace": 6, "gsrlimit": 1, "prop": "imageinfo",
            "iiprop": "url", "iiurlwidth": 400, "format": "json",
        })
        data = _get_json(f"https://commons.wikimedia.org/w/api.php?{params}")
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return None
        info = next(iter(pages.values()))["imageinfo"][0]
        return {"url": info["thumburl"], "credit": "Wikimedia Commons", "source": "stock"}
    except Exception:
        return None


def get_photo(hex_code: str, aircraft_type: str | None, manufacturer: str | None) -> dict | None:
    cache = _load_cache()
    key = hex_code.lower()
    if key in cache:
        return cache[key]

    photo = _real_photo(hex_code)
    if photo is None and aircraft_type:
        type_key = f"type:{aircraft_type}"
        if type_key in cache:
            photo = cache[type_key]
        else:
            photo = _stock_photo(aircraft_type, manufacturer)
            cache[type_key] = photo
    cache[key] = photo
    _save_cache()
    return photo


def _self_check() -> None:
    import tempfile, os
    global CACHE_PATH, _cache
    orig_path, orig_cache = CACHE_PATH, _cache
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    CACHE_PATH = Path(path)
    _cache = None
    try:
        result = get_photo("ffffff", None, None)  # no real photo, no type to fall back on
        assert result is None, result
        cache = _load_cache()
        assert "ffffff" in cache, cache  # miss still cached, avoids re-querying
        print("self-check OK: unknown hex with no type info returns None and caches the miss")
    finally:
        CACHE_PATH, _cache = orig_path, orig_cache
        if os.path.exists(path):
            os.unlink(path)


if __name__ == "__main__":
    _self_check()
