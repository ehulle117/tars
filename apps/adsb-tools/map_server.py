#!/usr/bin/env python3
"""Feature 2: live map of current aircraft positions.

Reads a JSON snapshot that run.py writes each poll cycle and serves it,
following the same stdlib-only ThreadingHTTPServer pattern as
sdr-waterfall/server.py (no Flask needed for two routes).

Usage: python3 map_server.py <state.json> [port]
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from route_lookup import lookup_route
from photo_lookup import get_photo
from closest_approach import leaderboard

STATIC_DIR = Path(__file__).parent / "static"


def build_response(state_path: str) -> dict:
    try:
        state = json.loads(Path(state_path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"receiver": None, "aircraft": []}
    for a in state.get("aircraft", []):
        route = lookup_route(a["hex"])  # cached on disk, fails soft to None
        a["route"] = route
        a["photo"] = get_photo(a["hex"], (route or {}).get("type"), (route or {}).get("manufacturer"))
    return state


def build_closest_response(top_n: int = 10) -> dict:
    rows = leaderboard(top_n=top_n)
    entries = []
    for hex_, flight, range_km, alt, lat, lon, seen_at in rows:
        route = lookup_route(hex_)
        entries.append({
            "hex": hex_, "flight": (flight or "").strip() or hex_,
            "range_km": range_km, "alt_baro": alt, "lat": lat, "lon": lon, "seen_at": seen_at,
            "route": route,
            "photo": get_photo(hex_, (route or {}).get("type"), (route or {}).get("manufacturer")),
        })
    return {"leaderboard": entries}


def make_handler(state_path: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/aircraft.json":
                payload = json.dumps(build_response(state_path)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/closest.json":
                payload = json.dumps(build_closest_response()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                index = (STATIC_DIR / "map.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(index)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(index)

    return Handler


def _self_check() -> None:
    import tempfile, os
    global lookup_route, get_photo, leaderboard
    orig_lookup, orig_photo, orig_leaderboard = lookup_route, get_photo, leaderboard
    lookup_route = lambda hex_: {"type": "TEST"}  # avoid real network calls
    get_photo = lambda hex_, t, m: {"url": "http://example.com/test.jpg"}
    leaderboard = lambda top_n=10: [("abc123", "TST1", 4.2, 5000, 42.0, -76.0, 1000.0)]

    closest = build_closest_response()
    assert closest == {"leaderboard": [{
        "hex": "abc123", "flight": "TST1", "range_km": 4.2, "alt_baro": 5000,
        "lat": 42.0, "lon": -76.0, "seen_at": 1000.0,
        "route": {"type": "TEST"}, "photo": {"url": "http://example.com/test.jpg"},
    }]}, closest

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        Path(path).write_text(json.dumps({"receiver": {"lat": 1, "lon": 2}, "aircraft": [{"hex": "abc"}]}))
        result = build_response(path)
        assert result["receiver"] == {"lat": 1, "lon": 2}, result
        assert len(result["aircraft"]) == 1, result
        assert result["aircraft"][0]["route"] == {"type": "TEST"}, result
        assert result["aircraft"][0]["photo"]["url"] == "http://example.com/test.jpg", result
        result_missing = build_response(path + ".missing")
        assert result_missing == {"receiver": None, "aircraft": []}, result_missing
        print("self-check OK: state file read, route + photo + closest-approach enrichment, and missing-file fallback all work")
    finally:
        lookup_route, get_photo, leaderboard = orig_lookup, orig_photo, orig_leaderboard
        os.unlink(path)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-check":
        _self_check()
        sys.exit(0)
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <state.json> [port]")
        print(f"   or: {sys.argv[0]} --self-check")
        sys.exit(1)
    state_arg = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8766
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(state_arg))
    print(f"Serving live map on http://0.0.0.0:{port}  (reading {state_arg})")
    httpd.serve_forever()
