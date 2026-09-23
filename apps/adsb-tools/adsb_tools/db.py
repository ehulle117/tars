#!/usr/bin/env python3
"""Shared SQLite handle for all adsb-tools features."""
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent.parent / "adsb_tools.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (
    hex TEXT NOT NULL,
    flight TEXT,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    min_alt_baro INTEGER,
    max_alt_baro INTEGER,
    max_gs REAL,
    PRIMARY KEY (hex, first_seen)
);

CREATE TABLE IF NOT EXISTS positions (
    hex TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    alt_baro INTEGER,
    range_km REAL NOT NULL,
    seen_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_hex ON positions(hex);

CREATE TABLE IF NOT EXISTS closest_approach (
    hex TEXT PRIMARY KEY,
    flight TEXT,
    min_range_km REAL NOT NULL,
    lat REAL, lon REAL, alt_baro INTEGER,
    seen_at REAL NOT NULL
);
"""


def get_db(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _self_check() -> None:
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = get_db(Path(path))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert {"sightings", "positions", "closest_approach"} <= tables, tables
        conn.close()
        print("self-check OK: all tables created")
    finally:
        os.unlink(path)


if __name__ == "__main__":
    _self_check()
