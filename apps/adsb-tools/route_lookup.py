#!/usr/bin/env python3
"""Feature 5: look up aircraft type/registration info for a hex.

Uses a local copy of the OpenSky Network aircraft database CSV
(https://opensky-network.org/datasets/metadata/aircraftDatabase.csv) as an
offline lookup table - hexdb.io's live API was tried first but had ~0%
coverage for US-registered aircraft, so this is a local table instead of a
network call.
"""
from __future__ import annotations

import csv
from pathlib import Path

CSV_PATH = Path(__file__).parent / "aircraftDatabase.csv"

_db: dict | None = None


def _load_db() -> dict:
    global _db
    if _db is not None:
        return _db
    _db = {}
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                hex_ = row.get("icao24", "").strip().lower()
                if not hex_:
                    continue
                _db[hex_] = {
                    "registration": row.get("registration", "").strip() or None,
                    "type": row.get("typecode", "").strip() or row.get("model", "").strip() or None,
                    "manufacturer": row.get("manufacturername", "").strip() or None,
                }
    except FileNotFoundError:
        pass  # fail soft - no database yet, every lookup returns None
    return _db


def lookup_route(hex_code: str) -> dict | None:
    """Returns {"registration":..., "type":..., "manufacturer":...} or None."""
    return _load_db().get(hex_code.lower())


def _self_check() -> None:
    import tempfile, os
    global _db, CSV_PATH
    orig_path, orig_db = CSV_PATH, _db
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    Path(path).write_text(
        'icao24,registration,manufacturericao,manufacturername,model,typecode\n'
        'abc123,N12345,BOEING,Boeing,737-800,B738\n'
    )
    CSV_PATH = Path(path)
    _db = None
    try:
        result = lookup_route("ABC123")  # case-insensitive
        assert result == {"registration": "N12345", "type": "B738", "manufacturer": "Boeing"}, result
        assert lookup_route("ffffff") is None
        print("self-check OK: CSV lookup works, case-insensitive, unknown hex -> None")
    finally:
        CSV_PATH, _db = orig_path, orig_db
        os.unlink(path)


if __name__ == "__main__":
    _self_check()
