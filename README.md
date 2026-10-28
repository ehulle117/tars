# Tars

GitOps config for **Tars**, a k3s cluster running the homelab's media,
automation, and monitoring services. Storage lives on **Case**, an Unraid
server that exports media over NFS.

Argo CD (`tars-apps`, in the `argocd` namespace) watches [`apps/`](apps/) on
`main` with auto-sync enabled. Pushing a manifest change here is the
deployment mechanism — nothing is applied by hand except secrets, which are
deliberately kept out of git.

See [`docs/architecture.md`](docs/architecture.md) for how the pieces fit
together.

## Services

All workloads run in the `apps` namespace unless noted.

| Service | Manifest | Image | Purpose |
|---|---|---|---|
| [Homarr](https://github.com/homarr-labs/homarr) | [`apps/homarr.yaml`](apps/homarr.yaml) | `ghcr.io/homarr-labs/homarr` | Dashboard / landing page for everything below |
| [Sonarr](https://sonarr.tv/) | [`apps/sonarr.yaml`](apps/sonarr.yaml) | `lscr.io/linuxserver/sonarr` | TV show acquisition |
| [Radarr](https://radarr.video/) | [`apps/radarr.yaml`](apps/radarr.yaml) | `lscr.io/linuxserver/radarr` | Movie acquisition |
| [Lidarr](https://lidarr.audio/) | [`apps/lidarr.yaml`](apps/lidarr.yaml) | `lscr.io/linuxserver/lidarr` | Music acquisition |
| [Bookshelf](https://github.com/pennydreadful/bookshelf) (Readarr fork) | [`apps/readarr.yaml`](apps/readarr.yaml) | `ghcr.io/pennydreadful/bookshelf` (`softcover`) | Book acquisition. Replaces archived Readarr in place - still named `readarr` in k8s |
| [Bazarr](https://www.bazarr.media/) | [`apps/bazarr.yaml`](apps/bazarr.yaml) | `lscr.io/linuxserver/bazarr` | Subtitle downloads for Sonarr/Radarr libraries |
| [Recyclarr](https://recyclarr.dev/) | [`apps/recyclarr.yaml`](apps/recyclarr.yaml) | `ghcr.io/recyclarr/recyclarr` | CronJob, daily 5:20 AM, syncs a minimal TRaSH custom-format set (BR-DISK/LQ/x265-HD blocks, repack scoring) onto existing Radarr/Sonarr profiles. Reuses the `arr-api-keys` Secret |
| [Prowlarr](https://prowlarr.com/) | [`apps/prowlarr.yaml`](apps/prowlarr.yaml) | `lscr.io/linuxserver/prowlarr` | Indexer manager, feeds the *arr apps |
| [Overseerr](https://overseerr.dev/) | [`apps/overseerr.yaml`](apps/overseerr.yaml) | `lscr.io/linuxserver/overseerr` | Request front-end for Sonarr/Radarr |
| [Deluge](https://deluge-torrent.org/) | [`apps/deluge.yaml`](apps/deluge.yaml) | `binhex/arch-delugevpn` | Torrent client (VPN-wrapped) |
| [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) | [`apps/flaresolverr.yaml`](apps/flaresolverr.yaml) | `ghcr.io/flaresolverr/flaresolverr` | Cloudflare bypass proxy for Prowlarr indexers |
| [ARM](https://github.com/automatic-ripping-machine/automatic-ripping-machine) | [`apps/arm.yaml`](apps/arm.yaml) | `automaticrippingmachine/automatic-ripping-machine` | Automatic disc ripping (needs host `/dev/sr0`, privileged) |
| [Fetcharr](https://github.com/egg82/fetcharr) | [`apps/fetcharr.yaml`](apps/fetcharr.yaml) | `egg82/fetcharr` | Syncs quality profiles/tags across *arr apps |
| [Home Assistant](https://www.home-assistant.io/) | [`apps/homeassistant.yaml`](apps/homeassistant.yaml) | `ghcr.io/home-assistant/home-assistant` | Home automation; Sonoff SNZB-02 temp/humidity sensors via ZHA. The Sonoff Zigbee dongle is plugged into `tars` (pod is privileged and mounts `/dev/serial` for ZHA's `/dev/serial/by-id/...` path) - restart the pod after plugging/replugging it. Port 8123 |
| [Uptime Kuma](https://github.com/louislam/uptime-kuma) | [`apps/uptime-kuma.yaml`](apps/uptime-kuma.yaml) | `louislam/uptime-kuma` | Status/uptime monitoring for the cluster |
| [Mead Log](apps/mead/PLAN.md) | [`apps/mead.yaml`](apps/mead.yaml) | `ghcr.io/ehulle117/tars-mead` | Custom service: tracks mead batches (planned/active/archived), hydrometer readings, per-batch costs, an inventory with reorder levels and a shopping list (plan a batch against the shelf), a who-paid ledger, bottles left / tastings / printable labels with photos, batch comparison and CSV export, iSpindel readings ([setup](docs/mead-ispindel.md)), TOSNA nutrient schedule, stabilize/backsweeten math, and starter recipes from the r/mead wiki. FastAPI + SQLite (photos beside it) on the `mead-data-tars` local-path PVC on `tars`, covered by the 3 AM tars appdata backup. Shared with Gabe over Tailscale ([setup](docs/mead-tailscale.md)). http://homebrew.case.local (Nginx Proxy Manager route) / port 8770. `mead-bot` (same manifest) posts due tasks to Discord at 6 AM ET via the Tars bot; reply to a task with a reading (`1.040 68F`) or `done` to log it |
| [tars-updater-agent](tars-updater-agent/README.md) | [`apps/tars-updater-agent.yaml`](apps/tars-updater-agent.yaml) | `ghcr.io/ehulle117/tars-updater-agent` | Custom service: daily Trivy vuln scans (critical findings also queued for alerts — see "Alerting" below) + weekly OS/container update digest posted to Discord via the `Tars` bot (digest only, not triaged) |
| Appdata backup | [`apps/backup-cronjob.yaml`](apps/backup-cronjob.yaml), [`apps/pi-appdata-backup.yaml`](apps/pi-appdata-backup.yaml) | `alpine` | CronJobs, daily (3:00/3:30 AM), copy each node's local-path appdata to Case; queues for triage if a run fails — see "Alerting" below |
| *arr queue check | [`apps/arr-queue-check.yaml`](apps/arr-queue-check.yaml) | `python:3.12-alpine` | CronJob, daily 8 AM, checks Radarr/Sonarr/Lidarr/Readarr queues for stuck imports (24h+, or immediately for executable/fake releases) and Prowlarr for long-failing indexers; queues a report only when something's actually wrong |
| Bookshelf junk cleanup | [`apps/bookshelf-junk-cleanup.yaml`](apps/bookshelf-junk-cleanup.yaml) | `python:3.12-alpine` | CronJob, Sundays 6 AM, unmonitors obvious non-book junk (comic issues, box sets, samplers, study guides, coloring books, foreign editions) among Bookshelf books added in the last 8 days that have no file. Logs what it changed; `DRY_RUN=1` previews |
| Deluge stall check | [`apps/deluge-stall-check.yaml`](apps/deluge-stall-check.yaml) | `python:3.12-alpine` | CronJob, every 2h, flags torrents in Deluge's `Error` state or stuck `Downloading` at 0 B/s for 2h+ |
| Router check | [`apps/router-check.yaml`](apps/router-check.yaml) | `python:3.12-alpine` | CronJob, every 30 min, SSHes into the GL.iNet/OpenWrt router: WAN-down is an alert, upgradable `opkg` packages post straight to the digest channel. Needs a `router-ssh-key` Secret (public half authorized on the router) |
| Case health check | [`apps/case-health-check.yaml`](apps/case-health-check.yaml) | `python:3.12-alpine` | CronJob, every 30 min, SSHes into Case (Unraid) to check array state (`mdcmd status`) and `/mnt/user` disk usage. Needs a `case-ssh-key` Secret |
| Argo sync check | [`apps/argo-sync-check.yaml`](apps/argo-sync-check.yaml) | `python:3.12-alpine` | CronJob, every 15 min, reads `Application` status straight off the K8s API and flags anything not `Synced`/`Healthy` — replaces Argo CD's native webhook notifier so this also routes through the bot |
| Pod health check | [`apps/pod-health-check.yaml`](apps/pod-health-check.yaml) | `python:3.12-alpine` | CronJob, every 15 min, flags CrashLoopBackOff/ImagePullBackOff/OOMKilled/high-restart/stuck-Pending pods cluster-wide. Read-only via the `cluster-health-checker` ClusterRole. Detector only — queues, doesn't triage |
| Resource pressure check | [`apps/resource-pressure-check.yaml`](apps/resource-pressure-check.yaml) | `python:3.12-alpine` | CronJob, every 30 min, checks node CPU/memory (via metrics-server) and DiskPressure/MemoryPressure conditions, plus Case's NFS export disk usage above 90%. Detector only — queues, doesn't triage |
| Alerts | [`apps/tars-alerts.yaml`](apps/tars-alerts.yaml) | `python:3.12-alpine` | CronJob, every 15 min. Drains every detector's queued findings and posts each new one to Discord as a Forum thread, deduped (repeats re-posted at most daily). See \"Alerting\" below |
| Claude Code dev pod | [`apps/claude-code.yaml`](apps/claude-code.yaml) | `node:22-bookworm-slim` + `@anthropic-ai/claude-code` | Persistent pod you `kubectl exec` into for interactive Claude Code sessions against this repo/cluster. Not a service — just `sleep infinity` with PVCs for `/workspace` and `~/.claude` so login survives restarts. |

## Updates

Every third-party image is pinned to a version tag (or a digest, where the
upstream only publishes `latest`), and so are the pip/npm packages installed
at container start. [Renovate](renovate.json) opens one grouped PR a week
(Monday mornings, ET) to bump them, waits
3 days after a release before proposing it (most malicious package releases
are pulled within that window), and adds `@sha256` digests to every image.
Our own `ghcr.io/ehulle117/*` images are excluded since this repo builds them.

## Network policies

[`apps/network-policies.yaml`](apps/network-policies.yaml) isolates the pods
that handle untrusted input (deluge, flaresolverr, mead,
adsb-tools). No other pod accepts connections from them, and they can reach
only DNS and the public internet: not the LAN, and not other pods. Everything
else keeps today's behavior. When adding an app like that, add its `app`
label to both lists. To check the policies after a change, run
[`scripts/verify-network-policies.sh`](scripts/verify-network-policies.sh).

## Storage

Media is served from Case (Unraid, `192.168.8.152`) over NFS and mounted
`ReadWriteMany` into every media app — see
[`storage/nfs-media.yaml`](storage/nfs-media.yaml). Per-app config/state uses
`local-path` PVCs on the cluster itself, so app config and media data have
different backup/recovery stories: config PVCs are covered by the daily
appdata backup CronJob, media on Case is not managed by this repo.

## Adding a new service

1. Add a manifest under `apps/` (PVC + Deployment + Service, Ingress if it
   needs a hostname). Copy an existing single-container app (e.g.
   [`overseerr.yaml`](apps/overseerr.yaml)) as a starting point.
2. Keep secrets out of the manifest — use a `Secret` referenced by name (see
   `fetcharr-secrets` for the pattern) and create the
   actual `Secret` object out-of-band, not committed.
3. Add a row to the table above and commit to `main`. Argo CD picks it up
   automatically.

## Alerting

Everything alerting-related is bot-only — no Discord webhooks anywhere in
this repo — and follows one shape: a small set of **detectors** (one per
resource: pods, node/Case resource pressure, *arr queues, Deluge, the
router, Case's array, Argo CD sync status, the three appdata backups,
`tars-updater-agent`'s CVE scan) each just look for a problem and, if they
find one, drop a text file in a shared queue. One job, **`tars-alerts`**
([`apps/tars-alerts.yaml`](apps/tars-alerts.yaml)), is the only
thing that posts a problem report to Discord — no detector holds the bot
token for alerts or knows a channel
ID. Two channels total:

- **Alerts channel** (`ALERTS_CHANNEL_ID`, Forum) — every problem
  from every detector, one thread per distinct finding, thread title
  `<source>: <summary>`.
- **Digest channel** (`DIGEST_CHANNEL_ID`, `1546986016861192202`, plain
  channel) — routine "you should know this" info that isn't a problem:
  `tars-updater-agent`'s weekly OS/container update summary, and
  `router-check`'s list of upgradable `opkg` packages. Posted directly, no
  GitHub issue, no triage, no resolution tracking.

### Detectors

Every detector is symmetric: find a problem or don't, and if so, write
`<queue-mount>/.tars-triage-queue/<source>-<timestamp>.txt` on the shared
`nfs-media-pvc`. None of them know about Discord.

- `pod-health-check` (15 min): CrashLoopBackOff/ImagePullBackOff/OOMKilled/
  high-restart/stuck-Pending pods cluster-wide, via the read-only
  `cluster-health-checker` ClusterRole.
- `resource-pressure-check` (30 min): node CPU/memory (metrics-server),
  DiskPressure/MemoryPressure conditions, Case's NFS export usage, and
  Tars's local disk (alert at 70% - Deluge's downloads live there).
- `arr-queue-check` (daily 8 AM): stuck *arr imports, long-failing
  Prowlarr indexers.
- `deluge-stall-check` (2h): torrents in `Error` state or stalled at 0 B/s.
- `library-leftover-check` (daily 7:30 AM): scene/torrent-named entries at the
  root of the movies/tv/music/ebooks libraries on Case, and `.exe`/`.scr`-style
  files anywhere in them. Tripwire for Deluge's move-completed paths leaking
  into the libraries and for fake releases imported by the *arr apps.
- `router-check` (30 min): WAN down, via SSH + `ubus` on the GL.iNet router
  (`router-ssh-key` Secret).
- `case-health-check` (30 min): Unraid array state (`mdcmd status`) and
  `/mnt/user` disk usage, via SSH (`case-ssh-key` Secret).
- `argo-sync-check` (15 min): any Argo CD `Application` not `Synced`/
  `Healthy`, read straight off the K8s API — this is what replaces Argo
  CD's own native webhook notifier, so Argo status also flows through the
  bot instead of a separate integration.
- The three `*-appdata-backup` CronJobs: queue on backup failure.
- `tars-updater-agent`: queues on a `CRITICAL`-severity Trivy finding
  (its weekly update summary is a digest-channel post instead — see above).

Argo CD's and Uptime Kuma's *own* native notification configs (which only
know how to POST to a fixed webhook URL) are unused/removed in favor of the
detectors above — one shape, no separate webhook-based path to keep in sync.

### `tars-alerts`

Runs every 15 min. Each queued file becomes one Forum thread in
`ALERTS_CHANNEL_ID`, titled `<source>: <first line>`, and the file is
deleted after a successful post (a failed post leaves it for the next run).
Repeats are deduped in `.tars-alert-state.json` next to the queue: the same
finding (digits ignored) is posted once, then re-posted as a reply in its
original thread at most once a day while it keeps recurring.

No Claude and no GitHub. This replaced a Claude + `gh` triage job that held a
GitHub PAT and a Claude token while acting on text from pod logs.

Needs: `discord-alerts` Secret (`bot_token`), `ALERTS_CHANNEL_ID` env var,
`nfs-media-pvc` for the queue, optional `tars_alert_triage_url` key in
`uptime-kuma-push` for a heartbeat that only fires on clean runs.

**Note on testing changes here**: because `selfHeal: true` is set on the
`tars-apps`/`tars-storage` Argo CD Applications, a live `kubectl apply`
against anything Argo CD manages gets reverted to match `main` within
moments - validate with `--dry-run=client` and re-verify after merge.

### Secrets

- **`discord-alerts`** (`apps` namespace, out-of-band): `bot_token` only —
  the `Tars` Discord bot, invited to the server once with Send Messages/
  Create Posts in Forums/Add Reactions. No `webhook_url` key anymore.
- **`router-ssh-key`** / **`case-ssh-key`** (`apps` namespace, out-of-band):
  dedicated ed25519 keypairs, public half authorized on the router/Case
  respectively — not the same key used for interactive SSH access.
- **`uptime-kuma-push`** (`apps` namespace): one push-monitor URL per key
  (`pod_health_check_url`, `resource_pressure_check_url`,
  `tars_appdata_backup_url`,
  `pi_appdata_backup_url`). `pod-health-check`/`resource-pressure-check`
  ping unconditionally at the end of every run; the backup CronJobs ping
  only on success. This catches a job crashing before it ever reaches its
  own queue-write step — something the queue/triage alerting above can't
  see on its own. Configured in Uptime Kuma itself (not tracked in git).

