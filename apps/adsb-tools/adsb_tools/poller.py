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


STALE_AFTER_S = 60  # dump1090 stamps each aircraft.json with "now"; older than this = receiver stalled


def parse_aircraft(data: dict) -> list[dict]:
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
        self.last_ok: float | None = None  # last time a fetch succeeded with fresh data
        self.last_error: str | None = None

    def poll_once(self) -> list[dict]:
        """Fetch once. A failed or stale fetch yields [] but is recorded in
        self.last_error, so "feed down" is distinguishable from "no aircraft"."""
        try:
            data = fetch_json(self.aircraft_url)
            age = time.time() - data["now"] if isinstance(data, dict) and "now" in data else 0
            if age > STALE_AFTER_S:
                raise RuntimeError(f"aircraft.json is {int(age)}s old (receiver stalled?)")
            self.last_ok, self.last_error = time.time(), None
            return parse_aircraft(data)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return []

    def health(self) -> dict:
        return {"ok": self.last_error is None and self.last_ok is not None,
                "last_ok": self.last_ok, "error": self.last_error}

    def register(self, callback: Callable[[list[dict]], None]) -> None:
        self._callbacks.append(callback)

    def run_forever(self) -> None:
        while True:
            aircraft = self.poll_once()
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
    import http.server, threading
    class H(http.server.BaseHTTPRequestHandler):
        body = b""
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(H.body)
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p = Poller(f"http://127.0.0.1:{srv.server_port}/")
    H.body = json.dumps({"now": time.time(), "aircraft": [{"hex": "abc", "altitude": 5}]}).encode()
    assert len(p.poll_once()) == 1 and p.health()["ok"], p.health()
    H.body = json.dumps({"now": time.time() - 600, "aircraft": [{"hex": "abc"}]}).encode()
    assert p.poll_once() == [] and not p.health()["ok"] and "old" in p.health()["error"], p.health()
    srv.shutdown(); srv.server_close()
    assert p.poll_once() == [] and "URLError" in p.health()["error"], p.health()
    print("self-check OK: field normalization, plus fresh/stale/unreachable feed health")


if __name__ == "__main__":
    _self_check()
