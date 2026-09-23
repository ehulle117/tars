#!/usr/bin/env python3
"""Poll dump1090's aircraft.json on an interval and fan out to callbacks.

Normalizes field names since dump1090 forks differ (dump1090-fa uses
alt_baro/gs, dump1090-mutability/classic dump1090 uses altitude/speed).
"""
import json
import time
import urllib.request
from typing import Callable

# Aliases: normalized_key -> tuple of possible raw keys, first match wins.
FIELD_ALIASES = {
    "alt_baro": ("alt_baro", "altitude"),
    "gs": ("gs", "speed"),
}


def _normalize(entry: dict) -> dict:
    out = dict(entry)
    for norm_key, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in entry:
                out[norm_key] = entry[alias]
                break
    return out


def fetch_json(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_aircraft(url: str) -> list[dict]:
    """GET aircraft.json, return the normalized aircraft list (empty on error)."""
    try:
        data = fetch_json(url)
    except Exception:
        return []
    raw_list = data.get("aircraft", []) if isinstance(data, dict) else []
    return [_normalize(a) for a in raw_list if "hex" in a]


def fetch_receiver(url: str) -> dict:
    """GET receiver.json once at startup; returns {} on error."""
    try:
        return fetch_json(url)
    except Exception:
        return {}


class Poller:
    """Polls aircraft.json on an interval, calls each registered callback
    with the current normalized aircraft list. Single-threaded: callbacks
    run in sequence on the poll thread, so keep each one fast (<1s)."""

    def __init__(self, aircraft_url: str, interval_s: float = 2.0):
        self.aircraft_url = aircraft_url
        self.interval_s = interval_s
        self._callbacks: list[Callable[[list[dict]], None]] = []

    def register(self, callback: Callable[[list[dict]], None]) -> None:
        self._callbacks.append(callback)

    def run_forever(self) -> None:
        while True:
            aircraft = fetch_aircraft(self.aircraft_url)
            for cb in self._callbacks:
                try:
                    cb(aircraft)
                except Exception as e:
                    print(f"[poller] callback {cb.__name__} raised: {e}")
            time.sleep(self.interval_s)


def _self_check() -> None:
    fa_style = {"hex": "abc123", "flight": "UAL123", "alt_baro": 35000, "gs": 450}
    mutability_style = {"hex": "def456", "flight": "DAL456", "altitude": 12000, "speed": 300}
    n1, n2 = _normalize(fa_style), _normalize(mutability_style)
    assert n1["alt_baro"] == 35000 and n1["gs"] == 450, n1
    assert n2["alt_baro"] == 12000 and n2["gs"] == 300, n2
    print("self-check OK: field normalization handles both dump1090-fa and mutability schemas")


if __name__ == "__main__":
    _self_check()
