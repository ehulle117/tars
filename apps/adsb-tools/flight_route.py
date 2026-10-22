#!/usr/bin/env python3
"""Origin/destination for a flight callsign, via adsbdb.com (free, no API key).

ADS-B itself carries no route. This is the airline's usual route for that flight
number, so it can be wrong for diversions or reused numbers, and private,
military and most GA callsigns have none.

Lookups happen on one background thread and are cached on disk, so callers
(the map's /aircraft.json, polled every 2s) never wait on the network: the first
call for a callsign returns None and the answer shows up a moment later.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request

from adsb_tools import DATA_DIR

CACHE_PATH = DATA_DIR / "flightroute_cache.json"
API_URL = "https://api.adsbdb.com/v0/callsign/{}"
USER_AGENT = "adsb-tools/1.0 (hobby ADS-B tracker; https://github.com/ehulle117)"
HIT_TTL_S = 7 * 86400      # airline schedules change; refresh weekly
MISS_TTL_S = 86400         # unknown callsigns: retry daily
ERROR_TTL_S = 600          # network trouble: retry in 10 minutes
# Airline-style callsign: 3-letter ICAO airline code + flight number. Skips tail
# numbers (N757F) and other GA idents, which adsbdb never has routes for.
CALLSIGN_RE = re.compile(r"^[A-Z]{3}[0-9][0-9A-Z]{0,4}$")

_cache: dict | None = None
_lock = threading.Lock()
_queue: queue.Queue = queue.Queue()
_pending: set[str] = set()
_worker: threading.Thread | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def _save() -> None:
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_cache))
    os.replace(tmp, CACHE_PATH)


def _airport(a: dict | None) -> dict | None:
    if not a:
        return None
    return {"iata": a.get("iata_code"), "icao": a.get("icao_code"), "name": a.get("name"),
            "city": a.get("municipality"), "country": a.get("country_name")}


def parse(data: dict) -> dict | None:
    """adsbdb response -> {"origin", "destination", "airline"} or None."""
    resp = data.get("response") if isinstance(data, dict) else None
    fr = resp.get("flightroute") if isinstance(resp, dict) else None
    if not fr:
        return None
    return {"origin": _airport(fr.get("origin")), "destination": _airport(fr.get("destination")),
            "airline": (fr.get("airline") or {}).get("name")}


def _fetch(callsign: str) -> dict | None:
    req = urllib.request.Request(API_URL.format(callsign), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return parse(json.loads(resp.read()))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # unknown callsign
        raise


def _work() -> None:
    while True:
        cs = _queue.get()
        try:
            route, ttl = _fetch(cs), None
            ttl = HIT_TTL_S if route else MISS_TTL_S
        except Exception:
            route, ttl = None, ERROR_TTL_S
        with _lock:
            old = _load().get(cs)
            # Keep a stale good answer through a network blip rather than blanking it.
            if route is None and ttl == ERROR_TTL_S and old and old.get("route"):
                route = old["route"]
            _cache[cs] = {"t": time.time(), "ttl": ttl, "route": route}
            _pending.discard(cs)
            try:
                _save()
            except OSError:
                pass
        time.sleep(1)  # be polite to a free API


def lookup(callsign: str | None) -> dict | None:
    """Cached route for a callsign (possibly stale), queueing a refresh if needed."""
    global _worker
    cs = (callsign or "").strip().upper()
    if not CALLSIGN_RE.match(cs):
        return None
    with _lock:
        entry = _load().get(cs)
        fresh = entry and time.time() - entry["t"] < entry.get("ttl", HIT_TTL_S)
        if not fresh and cs not in _pending:
            _pending.add(cs)
            _queue.put(cs)
            if _worker is None:
                _worker = threading.Thread(target=_work, daemon=True)
                _worker.start()
        return entry["route"] if entry else None


def _self_check() -> None:
    import tempfile
    from pathlib import Path
    global _fetch, CACHE_PATH, _cache
    sample = {"response": {"flightroute": {
        "airline": {"name": "Delta Air Lines"},
        "origin": {"iata_code": "ATL", "icao_code": "KATL", "name": "Hartsfield Jackson", "municipality": "Atlanta", "country_name": "United States"},
        "destination": {"iata_code": "EWR", "icao_code": "KEWR", "name": "Newark Liberty", "municipality": "New York", "country_name": "United States"}}}}
    r = parse(sample)
    assert r["origin"]["iata"] == "ATL" and r["destination"]["city"] == "New York" and r["airline"] == "Delta Air Lines", r
    assert parse({"response": "unknown callsign"}) is None
    assert CALLSIGN_RE.match("DAL2226") and CALLSIGN_RE.match("EDV5007") and not CALLSIGN_RE.match("N757F")
    assert lookup("N757F") is None and lookup("") is None and lookup("../x") is None

    calls = []
    orig_fetch, orig_path = _fetch, CACHE_PATH
    _fetch = lambda cs: (calls.append(cs), parse(sample) if cs == "DAL2226" else None)[1]
    tmpdir = tempfile.mkdtemp()
    CACHE_PATH, _cache = Path(tmpdir) / "c.json", None
    try:
        assert lookup("dal2226 ") is None, "first call must not block on the network"
        for _ in range(50):
            if "DAL2226" not in _pending:
                break
            time.sleep(0.05)
        assert lookup("DAL2226")["destination"]["iata"] == "EWR"
        assert calls == ["DAL2226"], f"cached hit must not refetch: {calls}"
        lookup("ZZZ9999")
        time.sleep(1.3)
        assert lookup("ZZZ9999") is None and calls.count("ZZZ9999") == 1, "misses are cached too"
        assert json.loads(CACHE_PATH.read_text())["DAL2226"]["route"]["origin"]["iata"] == "ATL"
        print("self-check OK: parse, callsign filter, non-blocking lookup, hit/miss caching, disk persistence")
    finally:
        _fetch, CACHE_PATH = orig_fetch, orig_path
        _cache = None


if __name__ == "__main__":
    _self_check()
