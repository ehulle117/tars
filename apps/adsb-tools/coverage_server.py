#!/usr/bin/env python3
"""Feature 4: reception coverage map from logged positions.

Usage: python3 coverage_server.py <adsb_tools.db> [port]
"""
import json
import math
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from adsb_tools.db import get_db

STATIC_DIR = Path(__file__).parent / "static"
MAX_POINTS = 20000  # ponytail: full-table read each request; fine at this size,
                     # switch to a downsampled query if positions.db grows past ~1M rows

# Receiver's exact coordinates are a real-world address - never committed,
# same secret-file pattern as run.py.
RECEIVER_LOCATION_FILE = Path.home() / ".config" / "adsb-tools" / "receiver_location.json"
_DEFAULT_LOCATION = {"lat": 42.4430, "lon": -76.5019}  # Ithaca, NY city center (public fallback)


def _load_receiver_location() -> dict:
    try:
        return json.loads(RECEIVER_LOCATION_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return _DEFAULT_LOCATION


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing in degrees from point 1 to point 2."""
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def build_response(db_path: str) -> dict:
    conn = get_db(Path(db_path))
    rows = conn.execute(
        "SELECT lat, lon, alt_baro, range_km FROM positions ORDER BY seen_at DESC LIMIT ?",
        (MAX_POINTS,),
    ).fetchall()
    conn.close()
    receiver = _load_receiver_location()
    points = []
    for lat, lon, alt_baro, range_km in rows:
        points.append({
            "lat": lat, "lon": lon, "alt_baro": alt_baro, "range_km": range_km,
            "bearing": bearing_deg(receiver["lat"], receiver["lon"], lat, lon),
        })
    return {"receiver": receiver, "points": points}


def make_handler(db_path: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/coverage.json":
                payload = json.dumps(build_response(db_path)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                index = (STATIC_DIR / "coverage.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(index)))
                self.end_headers()
                self.wfile.write(index)

    return Handler


def _self_check() -> None:
    import tempfile, os
    assert abs(bearing_deg(42.0, -76.0, 43.0, -76.0) - 0) < 1, "due north should be ~0 deg"
    assert abs(bearing_deg(42.0, -76.0, 42.0, -75.0) - 90) < 1, "due east should be ~90 deg"
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = get_db(Path(path))
        conn.execute("INSERT INTO positions (hex, lat, lon, alt_baro, range_km, seen_at) VALUES (?,?,?,?,?,?)",
                     ("abc", 42.5, -76.5, 5000, 12.3, 1.0))
        conn.commit()
        conn.close()
        result = build_response(path)
        assert len(result["points"]) == 1, result
        assert result["points"][0]["range_km"] == 12.3, result
        assert "bearing" in result["points"][0], result
        assert "receiver" in result, result
        print("self-check OK: coverage query returns logged points with bearing + receiver location")
    finally:
        os.unlink(path)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-check":
        _self_check()
        sys.exit(0)
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <adsb_tools.db> [port]")
        print(f"   or: {sys.argv[0]} --self-check")
        sys.exit(1)
    db_arg = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8767
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(db_arg))
    print(f"Serving coverage map on http://0.0.0.0:{port}  (reading {db_arg})")
    httpd.serve_forever()
