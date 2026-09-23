#!/usr/bin/env python3
"""Feature 3: post to Discord for emergency squawks, military aircraft,
helicopters, and low+close traffic (the kind of thing you'd actually notice
overhead, like a medevac departing nearby)."""
from __future__ import annotations

import os
import tempfile
import time
import urllib.request

from adsb_tools import discord_post
from adsb_tools.geo import haversine
from route_lookup import lookup_route
from photo_lookup import get_photo

# Raw IP:port, not the .tars.local hostname - that only resolves via the
# home router's local DNS, which a phone on Private DNS / cellular won't use.
MAP_URL = "http://192.168.8.226:8766"

EMERGENCY_SQUAWKS = {"7500", "7600", "7700"}  # hijack, radio failure, general emergency
SQUAWK_MEANING = {"7500": "HIJACK", "7600": "RADIO FAILURE", "7700": "GENERAL EMERGENCY"}

# US military ICAO hex allocation block (ADF7C8-AFFFFF); good enough heuristic,
# not exhaustive of every country's military aircraft.
MILITARY_HEX_RANGE = (0xADF7C8, 0xAFFFFF)

HELICOPTER_CATEGORY = "A7"
LOW_ALT_FT = 2000
CLOSE_RANGE_KM = 20

DEDUPE_WINDOW_S = 15 * 60

ALERT_CHANNEL_ID = None  # set before deploying

_last_posted: dict[tuple[str, str], float] = {}  # (hex, reason) -> timestamp


def _is_military(hex_code: str) -> bool:
    try:
        val = int(hex_code, 16)
    except ValueError:
        return False
    return MILITARY_HEX_RANGE[0] <= val <= MILITARY_HEX_RANGE[1]


def _describe(a: dict) -> str:
    # Many military aircraft don't broadcast a callsign (OPSEC), and weak/
    # partial reception can mean no altitude either - say so plainly rather
    # than falling back to repeating the hex as if it were the callsign.
    flight = (a.get("flight") or "").strip()
    label = flight if flight else "no callsign broadcast"
    alt = a.get("alt_baro")
    alt_str = f"{alt} ft" if alt is not None else "altitude unknown"
    return f"{label} (hex {a['hex']}), {alt_str}"


def _download_photo(url: str) -> str | None:
    """Downloads a photo to a temp file so it can be uploaded as a real
    Discord attachment - many photo CDNs block Discord's own link-preview
    bot (to save bandwidth) even though a plain fetch like this succeeds."""
    try:
        fd, path = tempfile.mkstemp(suffix=".jpg")
        req = urllib.request.Request(url, headers={"User-Agent": "adsb-tools/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp, os.fdopen(fd, "wb") as f:
            f.write(resp.read())
        return path
    except Exception:
        return None


def _post_alert(channel_id: str, content: str, a: dict) -> None:
    route = lookup_route(a["hex"])
    photo = get_photo(a["hex"], (route or {}).get("type"), (route or {}).get("manufacturer"))
    # Some aircraft (esp. military, weak reception) have no position at all
    # yet - a map link with nothing to center on is worse than no link, so
    # only include one when we actually have somewhere to point it.
    if a.get("lat") is not None and a.get("lon") is not None:
        content += f"\nTrack live: {MAP_URL}/?hex={a['hex']}&lat={a['lat']}&lon={a['lon']}"
    else:
        content += "\n(no position received yet - can't link to the map)"

    photo_path = _download_photo(photo["url"]) if photo and photo.get("url") else None
    try:
        discord_post.post(channel_id, content, image_path=photo_path)
    finally:
        if photo_path:
            os.unlink(photo_path)


def make_callback(channel_id: str = ALERT_CHANNEL_ID, receiver_lat: float | None = None,
                   receiver_lon: float | None = None):
    def _should_post(key: tuple, now: float) -> bool:
        if now - _last_posted.get(key, 0) < DEDUPE_WINDOW_S:
            return False
        _last_posted[key] = now
        return True

    def on_poll(aircraft: list[dict]) -> None:
        if not channel_id:
            return
        now = time.time()
        for a in aircraft:
            hex_ = a["hex"]
            squawk = a.get("squawk")

            if squawk in EMERGENCY_SQUAWKS and _should_post((hex_, "emergency"), now):
                _post_alert(channel_id, f":rotating_light: **{SQUAWK_MEANING[squawk]}** squawk {squawk} — {_describe(a)}", a)
                continue  # an emergency squawk is the important thing; don't also spam other reasons

            if _is_military(hex_) and _should_post((hex_, "military"), now):
                _post_alert(channel_id, f":military_helmet: Military aircraft — {_describe(a)}", a)

            if a.get("category") == HELICOPTER_CATEGORY and _should_post((hex_, "helicopter"), now):
                _post_alert(channel_id, f":helicopter: Helicopter overhead — {_describe(a)}", a)

            alt = a.get("alt_baro")
            if (receiver_lat is not None and a.get("lat") is not None and alt is not None
                    and alt < LOW_ALT_FT):
                range_km = haversine(receiver_lat, receiver_lon, a["lat"], a["lon"])
                if range_km < CLOSE_RANGE_KM and _should_post((hex_, "low_close"), now):
                    _post_alert(channel_id, f":small_airplane: Low & close — {_describe(a)}, {range_km:.1f} km away", a)

    return on_poll


def _self_check() -> None:
    posted = []
    import adsb_tools.discord_post as dp
    global lookup_route, get_photo
    orig_post, orig_lookup, orig_photo = dp.post, lookup_route, get_photo
    dp.post = lambda channel_id, content, image_path=None: posted.append((content, image_path))
    lookup_route = lambda hex_: None  # avoid real network calls
    get_photo = lambda hex_, t, m: None  # no photo -> image_path should be None, not a broken download
    try:
        cb = make_callback(channel_id="123", receiver_lat=42.44, receiver_lon=-76.50)

        # emergency squawk
        cb([{"hex": "abc", "flight": "TST1", "squawk": "7700", "alt_baro": 5000}])
        cb([{"hex": "abc", "flight": "TST1", "squawk": "7700", "alt_baro": 5000}])  # deduped
        assert len(posted) == 1 and "GENERAL EMERGENCY" in posted[0][0], posted
        assert "can't link to the map" in posted[0][0], posted  # no lat/lon -> no bogus link
        assert posted[0][1] is None, posted  # no photo available -> no attachment

        # military hex (in the ADF7C8-AFFFFF block), no callsign broadcast
        cb([{"hex": "ae1234", "alt_baro": 30000}])
        assert len(posted) == 2 and "Military" in posted[1][0], posted
        assert "no callsign broadcast" in posted[1][0], posted

        # helicopter category
        cb([{"hex": "def", "flight": "N1COP", "category": "A7", "alt_baro": 1500}])
        assert len(posted) == 3 and "Helicopter" in posted[2][0], posted

        # low + close
        cb([{"hex": "ghi", "flight": "N2LOW", "alt_baro": 800, "lat": 42.45, "lon": -76.50}])
        assert len(posted) == 4 and "Low & close" in posted[3][0], posted

        # low but far away - should NOT post
        cb([{"hex": "jkl", "flight": "N3FAR", "alt_baro": 800, "lat": 43.50, "lon": -76.50}])
        assert len(posted) == 4, posted

        # alert-time position is included in the link when known (fast movers
        # may already be gone by the time someone clicks, so waiting for a
        # live match isn't enough)
        assert "&lat=42.45&lon=-76.5" in posted[3][0], posted

        print("self-check OK: emergency/military/helicopter/low-close all alert once each, dedupe and range-gating work, IP-based tracker link with alert-time position included, no-photo case sends no attachment")
    finally:
        dp.post = orig_post
        lookup_route, get_photo = orig_lookup, orig_photo


if __name__ == "__main__":
    _self_check()
