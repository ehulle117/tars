# adsb-tools

Six small features built on top of `dump1090`'s live aircraft feed, all
sharing one poller and one SQLite database. Runs in the k3s cluster,
pinned to `k3s-worker-pi` (see `../adsb-tools.yaml`) since it needs to
reach the RTL-SDR JSON bridge on that node's `localhost:28080`.

- **Flight logger** (`logger.py`) — every aircraft seen, with session start/end and min/max altitude/speed, in `sightings`.
- **Live map** (`map_server.py` + `static/map.html`) — Leaflet map of current aircraft positions.
- **Overhead alert bot** (`alert_bot.py`) — Discord post on emergency squawks, military aircraft, helicopters, and low+close traffic.
- **Coverage map** (`coverage_server.py` + `static/coverage.html`) — every position ever logged, colored by range and broken out as a directional polar plot, to visualize actual antenna reception range.
- **Route lookup** (`route_lookup.py`) — aircraft type/registration/manufacturer via a local copy of the OpenSky Network aircraft database (`aircraftDatabase.csv`, baked into the image — hexdb.io was tried first but had ~0% coverage for US aircraft).
- **Closest-approach leaderboard** (`closest_approach.py` + `leaderboard.py`) — nearest any aircraft has ever come to the receiver, clickable from the live map.

## What stays outside this repo

`dump1090-mutability` (owns the RTL-SDR USB device) and its JSON bridge
(`python3 -m http.server 28080 --directory /run/dump1090-mutability`) run
as unmanaged host-level services directly on the Pi — not containerized,
not part of this deploy. The poller pod reaches them via `hostNetwork: true`
+ `http://localhost:28080/aircraft.json`.

## Deployment

See `../adsb-tools.yaml` — 3 Deployments (poller, live map on :8766,
coverage map on :8767) sharing one PVC for `adsb_tools.db`/`state.json`/
`photo_cache.json`. Push to `main`, CI builds+pushes the image, ArgoCD
auto-syncs.

Secrets (created manually, never committed — see the migration plan for
exact commands):
- `adsb-tools-discord` — Discord bot token, mounted at
  `~/.config/adsb-tools/discord_bot_token`.
- `adsb-tools-location` — the receiver's real lat/lon as a JSON file,
  mounted at `~/.config/adsb-tools/receiver_location.json`. Falls back to
  Ithaca, NY city center (a public, non-precise default) if absent.

Updating the aircraft database: replace `aircraftDatabase.csv` in this
directory, commit — CI rebuilds the image with the new data baked in.

## Local development

```bash
python3 -m venv venv
source venv/bin/activate
# no third-party deps - everything here is stdlib + curl (Discord uploads) + CDN JS (Leaflet)
```

Run any script with `--self-check` (or just run it directly for the ones
without a CLI, e.g. `python3 logger.py`) to sanity-check its core logic
against synthetic data without needing a live feed.
