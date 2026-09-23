#!/usr/bin/env python3
"""Feature 1: log every aircraft seen to SQLite (sightings table).

A "session" is a run of sightings for one hex with no gap longer than
SESSION_GAP_S; a new gap starts a new session row (new first_seen).
"""
import time

from adsb_tools.db import get_db

SESSION_GAP_S = 5 * 60

_open_sessions: dict[str, dict] = {}  # hex -> {"first_seen": ..., "last_seen": ...}


def make_callback(conn=None):
    conn = conn or get_db()

    def on_poll(aircraft: list[dict]) -> None:
        now = time.time()
        for a in aircraft:
            hex_ = a["hex"]
            session = _open_sessions.get(hex_)
            if session is None or now - session["last_seen"] > SESSION_GAP_S:
                session = {"first_seen": now, "last_seen": now,
                           "min_alt": a.get("alt_baro"), "max_alt": a.get("alt_baro"),
                           "max_gs": a.get("gs")}
                _open_sessions[hex_] = session
            else:
                session["last_seen"] = now
                alt = a.get("alt_baro")
                if isinstance(alt, (int, float)):
                    session["min_alt"] = alt if session["min_alt"] is None else min(session["min_alt"], alt)
                    session["max_alt"] = alt if session["max_alt"] is None else max(session["max_alt"], alt)
                gs = a.get("gs")
                if isinstance(gs, (int, float)):
                    session["max_gs"] = gs if session["max_gs"] is None else max(session["max_gs"], gs)

            conn.execute(
                """INSERT INTO sightings (hex, flight, first_seen, last_seen, min_alt_baro, max_alt_baro, max_gs)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(hex, first_seen) DO UPDATE SET
                     last_seen=excluded.last_seen,
                     flight=COALESCE(excluded.flight, flight),
                     min_alt_baro=excluded.min_alt_baro,
                     max_alt_baro=excluded.max_alt_baro,
                     max_gs=excluded.max_gs""",
                (hex_, a.get("flight", "").strip() or None, session["first_seen"], session["last_seen"],
                 session["min_alt"], session["max_alt"], session["max_gs"]),
            )
        conn.commit()

    return on_poll


def _self_check() -> None:
    import tempfile, os
    from pathlib import Path
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = get_db(Path(path))
        cb = make_callback(conn)
        cb([{"hex": "abc123", "flight": "TEST1", "alt_baro": 10000, "gs": 200}])
        cb([{"hex": "abc123", "flight": "TEST1", "alt_baro": 12000, "gs": 220}])
        rows = conn.execute("SELECT hex, max_alt_baro, max_gs FROM sightings").fetchall()
        assert len(rows) == 1, rows
        assert rows[0] == ("abc123", 12000, 220), rows
        print("self-check OK: session upsert tracks min/max across polls")
    finally:
        conn.close()
        os.unlink(path)


if __name__ == "__main__":
    _self_check()
