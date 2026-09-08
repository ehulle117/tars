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
| [Readarr](https://readarr.com/) | [`apps/readarr.yaml`](apps/readarr.yaml) | `binhex/arch-readarr` | Book/audiobook acquisition |
| [Prowlarr](https://prowlarr.com/) | [`apps/prowlarr.yaml`](apps/prowlarr.yaml) | `lscr.io/linuxserver/prowlarr` | Indexer manager, feeds the *arr apps |
| [Overseerr](https://overseerr.dev/) | [`apps/overseerr.yaml`](apps/overseerr.yaml) | `lscr.io/linuxserver/overseerr` | Request front-end for Sonarr/Radarr |
| [Deluge](https://deluge-torrent.org/) | [`apps/deluge.yaml`](apps/deluge.yaml) | `binhex/arch-delugevpn` | Torrent client (VPN-wrapped) |
| [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) | [`apps/flaresolverr.yaml`](apps/flaresolverr.yaml) | `ghcr.io/flaresolverr/flaresolverr` | Cloudflare bypass proxy for Prowlarr indexers |
| [ARM](https://github.com/automatic-ripping-machine/automatic-ripping-machine) | [`apps/arm.yaml`](apps/arm.yaml) | `automaticrippingmachine/automatic-ripping-machine` | Automatic disc ripping (needs host `/dev/sr0`, privileged) |
| [Fetcharr](https://github.com/egg82/fetcharr) | [`apps/fetcharr.yaml`](apps/fetcharr.yaml) | `egg82/fetcharr` | Syncs quality profiles/tags across *arr apps |
| [HortusFox](https://hortusfox.com/) | [`apps/hortusfox.yaml`](apps/hortusfox.yaml) | mariadb + app | Plant-care tracker, with cron sidecars ([`hortusfox-cron.yaml`](apps/hortusfox-cron.yaml) every 15 min, [`hortusfox-digest.yaml`](apps/hortusfox-digest.yaml) daily 7 AM email) |
| [Uptime Kuma](https://github.com/louislam/uptime-kuma) | [`apps/uptime-kuma.yaml`](apps/uptime-kuma.yaml) | `louislam/uptime-kuma` | Status/uptime monitoring for the cluster |
| [Valheim](docs/valheim/README.md) | [`apps/valheim.yaml`](apps/valheim.yaml) | `ghcr.io/lloesche/valheim-server` | Dedicated game server, reachable over Tailscale (see linked doc for network diagram) |
| [tars-updater-agent](tars-updater-agent/README.md) | [`apps/tars-updater-agent.yaml`](apps/tars-updater-agent.yaml) | `ghcr.io/ehulle117/tars-updater-agent` | Custom service: daily Trivy vuln scans + weekly OS/container update digest emailed via SMTP |
| Appdata backup | [`apps/backup-cronjob.yaml`](apps/backup-cronjob.yaml), [`apps/case-worker-appdata-backup.yaml`](apps/case-worker-appdata-backup.yaml), [`apps/pi-appdata-backup.yaml`](apps/pi-appdata-backup.yaml) | `alpine` | CronJobs, daily (3:00/3:15/3:30 AM), copy each node's local-path appdata to Case; posts to Discord (`discord-alerts` secret) if a run fails |
| *arr queue check | [`apps/arr-queue-check.yaml`](apps/arr-queue-check.yaml) | `python:3.12-alpine` | CronJob, daily 8 AM, checks Radarr/Sonarr/Lidarr/Readarr queues for stuck imports (24h+) and Prowlarr for long-failing indexers; emails a report only when something's actually wrong |
| Pod health check | [`apps/pod-health-check.yaml`](apps/pod-health-check.yaml) | `python:3.12-alpine` | CronJob, every 15 min, flags CrashLoopBackOff/ImagePullBackOff/OOMKilled/high-restart/stuck-Pending pods cluster-wide; posts to Discord only when something's wrong. Read-only via the `cluster-health-checker` ClusterRole. |
| Resource pressure check | [`apps/resource-pressure-check.yaml`](apps/resource-pressure-check.yaml) | `python:3.12-alpine` | CronJob, every 30 min, checks node CPU/memory (via metrics-server) and DiskPressure/MemoryPressure conditions, plus Case's NFS export disk usage; posts to Discord above 90%. |

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
   `hortusfox-secrets` / `fetcharr-secrets` for the pattern) and create the
   actual `Secret` object out-of-band, not committed.
3. Add a row to the table above and commit to `main`. Argo CD picks it up
   automatically.

## Alerting

Cluster-health CronJobs (pod health, resource pressure, backup failures) and
Argo CD's own `OutOfSync`/`Degraded` notifications all post to a single
Discord channel via webhook.

- **`discord-alerts` Secret** (`apps` namespace, key `webhook_url`): created
  out-of-band like `smtp-auth`, not committed. Required by
  `pod-health-check`, `resource-pressure-check`, and the three
  `*-appdata-backup` CronJobs.
- **Argo CD notifications**: configured directly on the cluster in
  `argocd-notifications-cm` / `argocd-notifications-secret` (namespace
  `argocd`) — outside this repo's GitOps scope, since it configures Argo CD
  itself rather than an app it manages. The webhook service is registered
  under key `service.webhook.discord`; `selfHeal: true` is set on both the
  `tars-apps` and `tars-storage` Applications so manual drift (like a
  live-patched container that isn't in git) gets reverted automatically
  instead of silently persisting.
- **`uptime-kuma-push` Secret** (`apps` namespace): one push-monitor URL per
  key (`pod_health_check_url`, `resource_pressure_check_url`,
  `tars_appdata_backup_url`, `case_worker_appdata_backup_url`,
  `pi_appdata_backup_url`), created out-of-band. `pod-health-check` and
  `resource-pressure-check` ping their URL unconditionally at the end of
  every run (after any Discord post); the three backup CronJobs ping only
  on success. This catches a job crashing or silently failing to run at
  all — a case the Discord-only alerting above can't see, since a crashed
  script never reaches its own "post to Discord" step. The five Push
  monitors are configured in Uptime Kuma itself (not tracked in git), with
  the existing Discord notification attached.

**Note on testing changes here**: because `selfHeal: true` is on, a live
`kubectl apply` against anything Argo CD manages gets silently reverted
back to match `main` within moments — validate with `--dry-run=client`,
but expect a live functional test to require actually merging first.

