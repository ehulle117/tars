#!/usr/bin/env python3
"""Feature 4: log downsampled positions to build a reception-range map."""
import time

from adsb_tools.db import get_db
from adsb_tools.geo import haversine

MIN_INTERVAL_S = 60  # only record one position per hex per this many seconds

_last_recorded: dict[str, float] = {}  # hex -> timestamp, in-memory (resets on restart)


def make_callback(receiver_lat: float, receiver_lon: float, conn=None):
    conn = conn or get_db()

    def on_poll(aircraft: list[dict]) -> None:
        now = time.time()
        inserted = False
        for a in aircraft:
            lat, lon = a.get("lat"), a.get("lon")
            if lat is None or lon is None:
                continue
            hex_ = a["hex"]
            if now - _last_recorded.get(hex_, 0) < MIN_INTERVAL_S:
                continue
            _last_recorded[hex_] = now
            range_km = haversine(receiver_lat, receiver_lon, lat, lon)
            conn.execute(
                "INSERT INTO positions (hex, lat, lon, alt_baro, range_km, seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                (hex_, lat, lon, a.get("alt_baro"), range_km, now),
            )
            inserted = True
        if inserted:
            conn.commit()

    return on_poll


def _self_check() -> None:
    import tempfile, os
    from pathlib import Path
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = get_db(Path(path))
        cb = make_callback(42.4430, -76.5019, conn)
        cb([{"hex": "abc", "lat": 42.53, "lon": -76.5019, "alt_baro": 5000}])
        cb([{"hex": "abc", "lat": 42.53, "lon": -76.5019, "alt_baro": 5000}])  # too soon, should be skipped
        rows = conn.execute("SELECT * FROM positions").fetchall()
        assert len(rows) == 1, rows
        print("self-check OK: downsampling skips a repeat within MIN_INTERVAL_S")
    finally:
        conn.close()
        os.unlink(path)


if __name__ == "__main__":
    _self_check()
