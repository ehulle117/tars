#!/usr/bin/env python3
"""Feature 2: live map of current aircraft positions.

Reads a JSON snapshot that run.py writes each poll cycle and serves it,
following the same stdlib-only ThreadingHTTPServer pattern as
sdr-waterfall/server.py (no Flask needed for two routes).

Usage: python3 map_server.py <state.json> [port]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from route_lookup import lookup_route
from photo_lookup import get_photo
from adsb_tools.db import get_db
from closest_approach import leaderboard
from fleet import HEX_RE, build_aircraft, build_fleet
import flight_route

STATIC_DIR = Path(__file__).parent / "static"
# In-cluster Service name; override for local dev.
COVERAGE_UPSTREAM = os.environ.get("COVERAGE_UPSTREAM", "http://adsb-tools-coverage-svc:8767")


def coverage_url(path: str) -> str:
    """/coverage/x -> <upstream>/x (path always starts with '/', so the host can't be changed)."""
    return COVERAGE_UPSTREAM + path[len("/coverage"):]


MAX_HISTORY_S = 48 * 3600   # cap one playback window
MAX_HISTORY_ROWS = 150_000


def build_history(start: float, end: float, db_path: Path | None = None, hex_: str | None = None) -> dict:
    """Logged positions in [start, end] grouped per aircraft, for playback.
    Positions are sampled ~1/min per aircraft, so the client interpolates."""
    end = min(end, start + MAX_HISTORY_S)
    conn = get_db(db_path) if db_path else get_db()
    one = " AND hex = ?" if hex_ else ""
    rows = conn.execute(
        "SELECT hex, seen_at, lat, lon, alt_baro FROM positions "
        f"WHERE seen_at BETWEEN ? AND ?{one} ORDER BY hex, seen_at LIMIT ?",
        (start, end, *([hex_] if hex_ else []), MAX_HISTORY_ROWS),
    ).fetchall()
    # Later sessions overwrite earlier ones, so a hex that changed callsign gets its latest.
    names = dict(conn.execute(
        "SELECT hex, flight FROM sightings WHERE flight IS NOT NULL "
        "AND last_seen >= ? AND first_seen <= ? ORDER BY first_seen", (start, end)).fetchall())
    lo, hi = conn.execute("SELECT MIN(seen_at), MAX(seen_at) FROM positions").fetchone()
    conn.close()
    tracks: dict[str, list] = {}
    for hex_, t, lat, lon, alt in rows:
        tracks.setdefault(hex_, []).append([round(t, 1), lat, lon, alt])
    return {
        "from": start, "to": end, "bounds": [lo, hi],
        "tracks": [{"hex": h, "flight": names.get(h), "pts": pts} for h, pts in tracks.items()],
    }


def build_activity(start: float, end: float, n: int, db_path: Path | None = None) -> dict:
    """Logged positions in [start, end) cut into n equal buckets, for the KPI
    sparklines and the timeline histogram. Bucket = [distinct aircraft, positions,
    max range km, min range km]; a bucket with 0 positions means nothing was logged."""
    n = max(1, min(int(n), 500))
    step = max((end - start) / n, 1.0)
    conn = get_db(db_path) if db_path else get_db()
    buckets = [[0, 0, None, None] for _ in range(n)]
    for b, ac, pos, hi, lo in conn.execute(
            "SELECT CAST((seen_at - ?) / ? AS INTEGER) AS b, COUNT(DISTINCT hex), COUNT(*), MAX(range_km), MIN(range_km) "
            "FROM positions WHERE seen_at >= ? AND seen_at < ? GROUP BY b", (start, step, start, end)):
        if 0 <= b < n:
            buckets[b] = [ac, pos, round(hi, 2), round(lo, 2)]
    extreme = {}
    for key, order in (("farthest", "DESC"), ("closest", "ASC")):
        row = conn.execute(
            f"SELECT p.hex, p.range_km, (SELECT flight FROM sightings s WHERE s.hex = p.hex AND s.flight IS NOT NULL "
            f"ORDER BY s.first_seen DESC LIMIT 1) FROM positions p WHERE p.seen_at >= ? AND p.seen_at < ? "
            f"ORDER BY p.range_km {order} LIMIT 1", (start, end)).fetchone()
        extreme[key] = {"hex": row[0], "km": round(row[1], 2), "flight": row[2]} if row else None
    seen = conn.execute("SELECT COUNT(DISTINCT hex) FROM sightings WHERE last_seen >= ? AND first_seen < ?",
                        (start, end)).fetchone()[0]
    conn.close()
    return {"from": start, "to": end, "step": step, "buckets": buckets, "seen": seen, **extreme}


def build_response(state_path: str) -> dict:
    try:
        state = json.loads(Path(state_path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"receiver": None, "aircraft": [], "server_now": time.time()}
    state["server_now"] = time.time()
    for a in state.get("aircraft", []):
        route = lookup_route(a["hex"])  # cached on disk, fails soft to None
        a["route"] = route
        a["photo"] = get_photo(a["hex"], (route or {}).get("type"), (route or {}).get("manufacturer"))
        a["flightroute"] = flight_route.lookup(a.get("flight"))  # origin/destination; None until looked up
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

        def _send(self, body: bytes, ctype: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path == "/fleet":  # may carry ?hex= / ?q=
                self._send((STATIC_DIR / "fleet.html").read_bytes(), "text/html")
            elif self.path == "/fleet.json":
                self._send(json.dumps(build_fleet()).encode(), "application/json")
            elif self.path.startswith("/fleet/") and self.path.endswith(".json"):
                detail = build_aircraft(self.path[len("/fleet/"):-len(".json")])
                if detail is None:
                    self._send(b'{"error": "not a 6-digit hex"}', "application/json", 404)
                else:
                    detail["photo"] = get_photo(detail["hex"], detail.get("type"), detail.get("manufacturer"))
                    latest = next((s["flight"] for s in detail["sessions"] if s["flight"]), None)
                    detail["flightroute"] = flight_route.lookup(latest)
                    self._send(json.dumps(detail).encode(), "application/json")
            elif self.path.startswith("/activity.json"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    end = float(q.get("to", [time.time()])[0])
                    start = float(q.get("from", [end - 86400])[0])
                    self._send(json.dumps(build_activity(start, end, int(q.get("n", ["96"])[0]))).encode(), "application/json")
                except ValueError:
                    self._send(b'{"error": "from/to/n must be numbers"}', "application/json", 400)
            elif self.path == "/aircraft.json":
                payload = json.dumps(build_response(state_path)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path.startswith("/history.json"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    now = time.time()
                    end = float(q.get("to", [now])[0])
                    start = float(q.get("from", [end - 3600])[0])
                    hex_ = q.get("hex", [None])[0]
                    if hex_ is not None and not HEX_RE.match(hex_.lower()):
                        raise ValueError
                    payload = json.dumps(build_history(start, end, hex_=hex_ and hex_.lower())).encode()
                    status = 200
                except ValueError:
                    payload, status = b'{"error": "from/to must be unix timestamps, hex a 6-digit hex"}', 400
                self.send_response(status)
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
            elif self.path.startswith("/coverage/"):
                try:
                    with urllib.request.urlopen(coverage_url(self.path), timeout=10) as up:
                        body, ctype = up.read(), up.headers.get("Content-Type", "text/html")
                    status = 200
                except Exception:
                    body, ctype, status = b"coverage service unreachable", "text/plain", 502
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/hub":
                index = (STATIC_DIR / "hub.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(index)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(index)
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
    assert coverage_url("/coverage/coverage.json") == COVERAGE_UPSTREAM + "/coverage.json"
    assert coverage_url("/coverage/") == COVERAGE_UPSTREAM + "/"
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
        assert result_missing["receiver"] is None and result_missing["aircraft"] == [], result_missing

        dbp = Path(path + ".db")
        conn = get_db(dbp)
        conn.executemany("INSERT INTO positions (hex, lat, lon, alt_baro, range_km, seen_at) VALUES (?,?,?,?,?,?)",
                         [("abc", 42.0, -76.0, 5000, 1.0, 100.0), ("abc", 42.1, -76.1, 5100, 1.0, 160.0),
                          ("def", 43.0, -75.0, 9000, 1.0, 120.0), ("abc", 42.9, -76.9, 1, 1.0, 9999.0)])
        conn.execute("INSERT INTO sightings (hex, flight, first_seen, last_seen) VALUES ('abc','TST1',90,170)")
        conn.commit(); conn.close()
        h = build_history(100.0, 200.0, dbp)
        by = {t["hex"]: t for t in h["tracks"]}
        assert [p[0] for p in by["abc"]["pts"]] == [100.0, 160.0] and by["abc"]["flight"] == "TST1", h
        assert by["def"]["flight"] is None and h["bounds"] == [100.0, 9999.0], h
        assert build_history(0.0, 10 * MAX_HISTORY_S, dbp)["to"] == MAX_HISTORY_S, "window must be capped"
        one = build_history(100.0, 200.0, dbp, hex_="def")
        assert [t["hex"] for t in one["tracks"]] == ["def"], one
        act = build_activity(100.0, 200.0, 2, dbp)  # buckets [100,150) and [150,200)
        assert act["buckets"] == [[2, 2, 1.0, 1.0], [1, 1, 1.0, 1.0]] and act["seen"] == 1, act
        assert act["farthest"]["hex"] in ("abc", "def") and act["closest"]["km"] == 1.0, act
        assert build_activity(500.0, 600.0, 4, dbp)["farthest"] is None, "empty window has no extremes"
        for ext in ("", "-wal", "-shm"):
            Path(str(dbp) + ext).unlink(missing_ok=True)
        print("self-check OK: state read, enrichment, missing-file fallback, history windowing/grouping/cap, activity buckets")
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
