#!/usr/bin/env python3
"""Feature 6: track the closest range any aircraft has ever come to the receiver."""
import time

from adsb_tools.db import get_db
from adsb_tools.geo import haversine


def make_callback(receiver_lat: float, receiver_lon: float, conn=None):
    conn = conn or get_db()

    def on_poll(aircraft: list[dict]) -> None:
        now = time.time()
        updated = False
        for a in aircraft:
            lat, lon = a.get("lat"), a.get("lon")
            if lat is None or lon is None:
                continue
            range_km = haversine(receiver_lat, receiver_lon, lat, lon)
            row = conn.execute(
                "SELECT min_range_km FROM closest_approach WHERE hex = ?", (a["hex"],)
            ).fetchone()
            if row is None or range_km < row[0]:
                conn.execute(
                    """INSERT INTO closest_approach (hex, flight, min_range_km, lat, lon, alt_baro, seen_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(hex) DO UPDATE SET
                         flight=excluded.flight, min_range_km=excluded.min_range_km,
                         lat=excluded.lat, lon=excluded.lon, alt_baro=excluded.alt_baro,
                         seen_at=excluded.seen_at""",
                    (a["hex"], (a.get("flight") or "").strip() or None, range_km,
                     lat, lon, a.get("alt_baro"), now),
                )
                updated = True
        if updated:
            conn.commit()

    return on_poll


def leaderboard(conn=None, top_n: int = 10) -> list[tuple]:
    conn = conn or get_db()
    return conn.execute(
        """SELECT hex, flight, min_range_km, alt_baro, lat, lon, seen_at
           FROM closest_approach ORDER BY min_range_km ASC LIMIT ?""",
        (top_n,),
    ).fetchall()


def _self_check() -> None:
    import tempfile, os
    from pathlib import Path
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = get_db(Path(path))
        # receiver at Ithaca; aircraft 10km away, then closer at 2km
        cb = make_callback(42.4430, -76.5019, conn)
        cb([{"hex": "abc", "flight": "T1", "lat": 42.5330, "lon": -76.5019, "alt_baro": 5000}])  # ~10km north
        cb([{"hex": "abc", "flight": "T1", "lat": 42.4610, "lon": -76.5019, "alt_baro": 5000}])  # ~2km north, closer
        row = conn.execute("SELECT min_range_km FROM closest_approach WHERE hex='abc'").fetchone()
        assert row[0] < 5, row  # should have kept the closer (smaller) distance
        board = leaderboard(conn)
        assert len(board) == 1, board
        print(f"self-check OK: closest_approach kept min distance {row[0]:.2f} km")
    finally:
        conn.close()
        os.unlink(path)


if __name__ == "__main__":
    _self_check()
