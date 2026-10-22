#!/usr/bin/env python3
"""Per-aircraft summary for the /fleet page: every hex ever seen, with its tail
number (registration), how many times it was observed, and so on.

One row per hex, aggregated from the sightings table ("sessions": runs of
sightings with no gap over SESSION_GAP_S, see logger.py).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from adsb_tools.db import get_db
from route_lookup import lookup_route

HEX_RE = re.compile(r"^[0-9a-f]{6}$")
MAX_SESSIONS = 500

# sightings.max_alt_baro can hold the text "ground", and SQLite sorts text above numbers.
_NUM = lambda col: f"CASE WHEN typeof({col}) IN ('integer','real') THEN {col} END"


def _registry(hex_: str) -> dict:
    info = lookup_route(hex_) or {}
    return {"tail": info.get("registration"), "type": info.get("type"), "manufacturer": info.get("manufacturer")}


def build_fleet(db_path: Path | None = None) -> dict:
    conn = get_db(db_path) if db_path else get_db()
    rows = conn.execute(f"""
        SELECT hex, COUNT(*), MIN(first_seen), MAX(last_seen), SUM(last_seen - first_seen),
               MAX({_NUM('max_alt_baro')}), MAX({_NUM('max_gs')}),
               COUNT(DISTINCT date(first_seen, 'unixepoch'))
        FROM sightings GROUP BY hex""").fetchall()
    calls: dict[str, list] = {}
    for hex_, flight, n in conn.execute(
            "SELECT hex, flight, COUNT(*) FROM sightings WHERE flight IS NOT NULL "
            "GROUP BY hex, flight ORDER BY hex, COUNT(*) DESC"):
        if len(calls.setdefault(hex_, [])) < 3:
            calls[hex_].append([flight, n])
    closest = dict(conn.execute("SELECT hex, min_range_km FROM closest_approach"))
    conn.close()
    aircraft = []
    for hex_, sessions, first, last, airtime, max_alt, max_gs, days in rows:
        aircraft.append({
            "hex": hex_, **_registry(hex_), "callsigns": calls.get(hex_, []),
            "sessions": sessions, "days": days, "airtime_s": round(airtime or 0),
            "first_seen": first, "last_seen": last, "max_alt": max_alt, "max_gs": max_gs,
            "closest_km": closest.get(hex_),
        })
    return {"generated": time.time(), "aircraft": aircraft}


def build_aircraft(hex_: str, db_path: Path | None = None) -> dict | None:
    """Session list (newest first) for one hex, or None if the hex is malformed."""
    hex_ = hex_.lower()
    if not HEX_RE.match(hex_):
        return None
    conn = get_db(db_path) if db_path else get_db()
    sessions = [
        {"first_seen": f, "last_seen": l, "flight": fl,
         "min_alt": a if isinstance(a, (int, float)) else None,
         "max_alt": b if isinstance(b, (int, float)) else None, "max_gs": g}
        for f, l, fl, a, b, g in conn.execute(
            "SELECT first_seen, last_seen, flight, min_alt_baro, max_alt_baro, max_gs FROM sightings "
            "WHERE hex = ? ORDER BY first_seen DESC LIMIT ?", (hex_, MAX_SESSIONS))
    ]
    conn.close()
    return {"hex": hex_, **_registry(hex_), "sessions": sessions}


def _self_check() -> None:
    import os
    import tempfile
    global lookup_route
    orig = lookup_route
    lookup_route = lambda h: {"registration": "N123AB", "type": "B738", "manufacturer": "Boeing"} if h == "aaa111" else None
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    dbp = Path(path)
    try:
        conn = get_db(dbp)
        conn.executemany(
            "INSERT INTO sightings (hex, flight, first_seen, last_seen, min_alt_baro, max_alt_baro, max_gs) VALUES (?,?,?,?,?,?,?)",
            [("aaa111", "UAL1", 0, 100, 1000, 30000, 400), ("aaa111", "UAL1", 86400, 86460, 500, "ground", 450),
             ("aaa111", None, 90000, 90010, None, None, None), ("bbb222", "X9", 10, 20, 100, 200, 100)])
        conn.execute("INSERT INTO closest_approach (hex, flight, min_range_km, seen_at) VALUES ('aaa111','UAL1',2.5,1)")
        conn.commit()
        conn.close()
        by = {a["hex"]: a for a in build_fleet(dbp)["aircraft"]}
        a = by["aaa111"]
        assert a["tail"] == "N123AB" and a["sessions"] == 3 and a["days"] == 2, a
        assert a["max_alt"] == 30000, f"text 'ground' must not win MAX: {a}"
        assert a["airtime_s"] == 100 + 60 + 10 and a["first_seen"] == 0 and a["last_seen"] == 90010, a
        assert a["callsigns"] == [["UAL1", 2]] and a["closest_km"] == 2.5, a
        assert by["bbb222"]["tail"] is None and by["bbb222"]["closest_km"] is None, by["bbb222"]
        d = build_aircraft("AAA111", dbp)
        assert [s["first_seen"] for s in d["sessions"]] == [90000, 86400, 0] and d["sessions"][1]["max_alt"] is None, d
        assert build_aircraft("../etc", dbp) is None and build_aircraft("zzzzzz", dbp) is None
        print("self-check OK: per-hex aggregation, text-altitude guard, callsign ranking, session list, hex validation")
    finally:
        lookup_route = orig
        for ext in ("", "-wal", "-shm"):
            Path(path + ext).unlink(missing_ok=True)


if __name__ == "__main__":
    _self_check()
