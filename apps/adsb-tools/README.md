# adsb-tools

Six small features built on top of `dump1090`'s live aircraft feed, all
sharing one poller and one SQLite database. Runs in the k3s cluster,
pinned to `k3s-worker-pi` (see `../adsb-tools.yaml`) since it reads the
`aircraft.json` that `dump1090-mutability` writes on that node.

- **Flight logger** (`logger.py`) — every aircraft seen, with session start/end and min/max altitude/speed, in `sightings`.
- **Live map** (`map_server.py` + `static/map.html`) — Leaflet map of current aircraft positions. A warning strip appears if the feed, the poller, or Discord posting stops working. The **Playback** button replays logged tracks (`/history.json`, ~1 position per aircraft per minute, interpolated).
- **Hub** (`/hub` on the map server) — the live map and coverage map as two resizable, pan/zoom-synced windows.
- **Overhead alert bot** (`alert_bot.py`) — Discord post on emergency squawks, military aircraft, helicopters, and low+close traffic.
- **Coverage map** (`coverage_server.py` + `static/coverage.html`) — every position ever logged, colored by range and broken out as a directional polar plot, to visualize actual antenna reception range.
- **Route lookup** (`route_lookup.py`) — aircraft type/registration/manufacturer via a local copy of the OpenSky Network aircraft database (`aircraftDatabase.csv`, baked into the image — hexdb.io was tried first but had ~0% coverage for US aircraft).
- **Closest-approach leaderboard** (`closest_approach.py` + `leaderboard.py`) — nearest any aircraft has ever come to the receiver, clickable from the live map.

## What stays outside this repo

`dump1090-mutability` (owns the RTL-SDR USB device) runs as a systemd
service directly on the Pi — not containerized, not part of this deploy.
The poller pod mounts its `/run/dump1090-mutability` directory read-only
(hostPath) and reads `aircraft.json` from it directly
(`AIRCRAFT_URL=file:///dump1090/aircraft.json`). There is deliberately no
HTTP bridge: the old hand-started one died on every reboot and the poller
silently saw "no aircraft".

## Deployment

See `../adsb-tools.yaml` — 3 Deployments (poller, live map on :8766,
coverage map on :8767) sharing one PVC mounted as a **directory** at `/data`
(`ADSB_DATA_DIR`), holding `adsb_tools.db` (+ its WAL files), `state.json`,
and `photo_cache.json`. Mount the directory, not individual files: SQLite's
WAL files must be shared by every pod, or readers miss recent rows and the
writer loses unflushed ones on restart.

Push to `main`, CI builds+pushes the image, ArgoCD auto-syncs. The image tag
is `:main` with `imagePullPolicy: Always`, so after CI finishes run
`kubectl rollout restart deployment/<name> -n apps` to pick up new code.
Do not let the manifest change land before the image that understands it.

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
