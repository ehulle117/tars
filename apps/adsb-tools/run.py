#!/usr/bin/env python3
"""Entrypoint: poll dump1090, fan out to logger/alert_bot/closest_approach/
coverage, and write a live state.json snapshot for map_server.py to serve.
"""
import json
import time
from pathlib import Path

from adsb_tools.poller import Poller
from adsb_tools.db import get_db
import logger
import alert_bot
import closest_approach
import coverage

# --- config -----------------------------------------------------------
# dump1090-mutability writes JSON to /run/dump1090-mutability/, served here
# by a plain stdlib http.server (lighttpd's own alias config wasn't
# cooperating and 8080 collides with another service on this k3s node).
AIRCRAFT_URL = "http://localhost:28080/aircraft.json"
ALERT_CHANNEL_ID = "1550242832512458752"  # shared SDR-alerts Discord channel (Tars bot)
STATE_PATH = Path(__file__).parent / "state.json"

# Receiver's exact coordinates are a real-world address - never committed.
# Set once via: python3 -c "import json,pathlib; \
#   p=pathlib.Path.home()/'.config/adsb-tools/receiver_location.json'; \
#   p.parent.mkdir(parents=True, exist_ok=True); \
#   p.write_text(json.dumps({'lat': 0.0, 'lon': 0.0}))"
RECEIVER_LOCATION_FILE = Path.home() / ".config" / "adsb-tools" / "receiver_location.json"
_DEFAULT_LOCATION = {"lat": 42.4430, "lon": -76.5019}  # Ithaca, NY city center (public fallback)


def _load_receiver_location() -> tuple[float, float]:
    try:
        loc = json.loads(RECEIVER_LOCATION_FILE.read_text())
        return loc["lat"], loc["lon"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print(f"[run] no receiver location at {RECEIVER_LOCATION_FILE}, "
              f"using public fallback (Ithaca city center)")
        return _DEFAULT_LOCATION["lat"], _DEFAULT_LOCATION["lon"]


RECEIVER_LAT, RECEIVER_LON = _load_receiver_location()
# ------------------------------------------------------------------------


def make_state_writer():
    def on_poll(aircraft: list[dict]) -> None:
        state = {
            "receiver": {"lat": RECEIVER_LAT, "lon": RECEIVER_LON},
            "aircraft": aircraft,
            "updated_at": time.time(),
        }
        STATE_PATH.write_text(json.dumps(state))

    return on_poll


def main() -> None:
    conn = get_db()
    poller = Poller(AIRCRAFT_URL, interval_s=2.0)
    poller.register(make_state_writer())
    poller.register(logger.make_callback(conn))
    poller.register(closest_approach.make_callback(RECEIVER_LAT, RECEIVER_LON, conn))
    poller.register(coverage.make_callback(RECEIVER_LAT, RECEIVER_LON, conn))
    if ALERT_CHANNEL_ID:
        poller.register(alert_bot.make_callback(ALERT_CHANNEL_ID, RECEIVER_LAT, RECEIVER_LON))
    print(f"Polling {AIRCRAFT_URL} every {poller.interval_s}s ...")
    poller.run_forever()


if __name__ == "__main__":
    main()
