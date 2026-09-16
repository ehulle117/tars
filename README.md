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
| [Uptime Kuma](https://github.com/louislam/uptime-kuma) | [`apps/uptime-kuma.yaml`](apps/uptime-kuma.yaml) | `louislam/uptime-kuma` | Status/uptime monitoring for the cluster |
| [Valheim](docs/valheim/README.md) | [`apps/valheim.yaml`](apps/valheim.yaml) | `ghcr.io/lloesche/valheim-server` | Dedicated game server, reachable over Tailscale (see linked doc for network diagram) |
| [tars-updater-agent](tars-updater-agent/README.md) | [`apps/tars-updater-agent.yaml`](apps/tars-updater-agent.yaml) | `ghcr.io/ehulle117/tars-updater-agent` | Custom service: daily Trivy vuln scans (critical findings also queued for Claude triage — see "Claude-triaged alerts" below) + weekly OS/container update digest posted to Discord via the `Tars` bot (digest only, not triaged) |
| Appdata backup | [`apps/backup-cronjob.yaml`](apps/backup-cronjob.yaml), [`apps/case-worker-appdata-backup.yaml`](apps/case-worker-appdata-backup.yaml), [`apps/pi-appdata-backup.yaml`](apps/pi-appdata-backup.yaml) | `alpine` | CronJobs, daily (3:00/3:15/3:30 AM), copy each node's local-path appdata to Case; queues for triage if a run fails — see "Alerting" below |
| *arr queue check | [`apps/arr-queue-check.yaml`](apps/arr-queue-check.yaml) | `python:3.12-alpine` | CronJob, daily 8 AM, checks Radarr/Sonarr/Lidarr/Readarr queues for stuck imports (24h+) and Prowlarr for long-failing indexers; queues a report only when something's actually wrong |
| Deluge stall check | [`apps/deluge-stall-check.yaml`](apps/deluge-stall-check.yaml) | `python:3.12-alpine` | CronJob, every 2h, flags torrents in Deluge's `Error` state or stuck `Downloading` at 0 B/s for 2h+ |
| Router check | [`apps/router-check.yaml`](apps/router-check.yaml) | `python:3.12-alpine` | CronJob, every 30 min, SSHes into the GL.iNet/OpenWrt router: WAN-down is an alert, upgradable `opkg` packages post straight to the digest channel. Needs a `router-ssh-key` Secret (public half authorized on the router) |
| Case health check | [`apps/case-health-check.yaml`](apps/case-health-check.yaml) | `python:3.12-alpine` | CronJob, every 30 min, SSHes into Case (Unraid) to check array state (`mdcmd status`) and `/mnt/user` disk usage. Needs a `case-ssh-key` Secret |
| Argo sync check | [`apps/argo-sync-check.yaml`](apps/argo-sync-check.yaml) | `python:3.12-alpine` | CronJob, every 15 min, reads `Application` status straight off the K8s API and flags anything not `Synced`/`Healthy` — replaces Argo CD's native webhook notifier so this also routes through the bot |
| Pod health check | [`apps/pod-health-check.yaml`](apps/pod-health-check.yaml) | `python:3.12-alpine` | CronJob, every 15 min, flags CrashLoopBackOff/ImagePullBackOff/OOMKilled/high-restart/stuck-Pending pods cluster-wide. Read-only via the `cluster-health-checker` ClusterRole. Detector only — queues, doesn't triage |
| Resource pressure check | [`apps/resource-pressure-check.yaml`](apps/resource-pressure-check.yaml) | `python:3.12-alpine` | CronJob, every 30 min, checks node CPU/memory (via metrics-server) and DiskPressure/MemoryPressure conditions, plus Case's NFS export disk usage above 90%. Detector only — queues, doesn't triage |
| Alert triage | [`apps/tars-alert-triage.yaml`](apps/tars-alert-triage.yaml) | `python:3.12-alpine` | CronJob, every 15 min — the only place Claude/`gh`/Discord triage happens. Drains every detector's queued findings, dedupes against open GitHub issues, opens/comments/skips, posts to Discord. See "Alerting" below |
| Claude Code dev pod | [`apps/claude-code.yaml`](apps/claude-code.yaml) | `node:22-bookworm-slim` + `@anthropic-ai/claude-code` | Persistent pod you `kubectl exec` into for interactive Claude Code sessions against this repo/cluster. Not a service — just `sleep infinity` with PVCs for `/workspace` and `~/.claude` so login survives restarts. |

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
find one, drop a text file in a shared queue. One job, **`tars-alert-triage`**
([`apps/tars-alert-triage.yaml`](apps/tars-alert-triage.yaml)), is the only
thing that ever touches Claude, `gh`, or Discord for a problem report — no
detector triages its own findings, holds a GitHub token, or knows a channel
ID. Two channels total:

- **Alerts channel** (`ALERTS_CHANNEL_ID`, Forum) — every triaged problem
  from every detector, one thread per tracked issue, thread title
  `<source>: <summary>`.
- **Digest channel** (`DIGEST_CHANNEL_ID`, `1547598576111194205`, plain
  channel) — routine "you should know this" info that isn't a problem:
  `tars-updater-agent`'s weekly OS/container update summary, and
  `router-check`'s list of upgradable `opkg` packages. Posted directly, no
  GitHub issue, no triage, no resolution tracking.

### Detectors

Every detector is symmetric: find a problem or don't, and if so, write
`<queue-mount>/.tars-triage-queue/<source>-<timestamp>.txt` on the shared
`nfs-media-pvc`. None of them know about Discord, GitHub, or Claude.

- `pod-health-check` (15 min): CrashLoopBackOff/ImagePullBackOff/OOMKilled/
  high-restart/stuck-Pending pods cluster-wide, via the read-only
  `cluster-health-checker` ClusterRole.
- `resource-pressure-check` (30 min): node CPU/memory (metrics-server),
  DiskPressure/MemoryPressure conditions, and Case's NFS export usage.
- `arr-queue-check` (daily 8 AM): stuck *arr imports, long-failing
  Prowlarr indexers.
- `deluge-stall-check` (2h): torrents in `Error` state or stalled at 0 B/s.
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

### `tars-alert-triage`

Runs every 15 min, node-pinned to `tars` (needs `claude-code-config-pvc`
mounted read-write — the same PVC the `claude-code` dev pod uses, so its
login is what authenticates Claude here, no separate Anthropic API key).
Each run:

1. Bootstraps Claude Code + `gh` only if the queue isn't empty.
2. For each queued file: runs a Claude triage prompt (shared as
   `triage_prompt`/`run_triage` in [`apps/alert-lib.yaml`](apps/alert-lib.yaml)) —
   checks `gh issue list --repo ehulle117/tars --state open` for an existing
   issue, then opens one, comments on the existing one, or does nothing on
   GitHub if it's not actually worth tracking.
3. Posts the result to `ALERTS_CHANNEL_ID` via the `Tars` bot
   (`post_and_track` in `alert-lib.yaml`) as a new Forum thread — or, for a
   recurring finding, a reply into the *same* thread as before (looked up
   via a `discord_thread_id` marker stashed in the issue body).
4. Deletes the queue file only after a successful post — a failed run
   leaves it for the next attempt.

`alert-lib.yaml`'s `discord_post`/`post_and_track`/`triage_prompt`/
`run_triage` are the one place this logic is written — every script that
touches Discord mounts this ConfigMap instead of carrying its own copy.

Needs: `claude-code-config-pvc`, `github-pat` Secret (`GH_TOKEN`),
`GITHUB_REPO` env var, `discord-alerts` Secret (`bot_token`),
`ALERTS_CHANNEL_ID` env var, and `nfs-media-pvc` mounted for the queue.

**Note on testing changes here**: because `selfHeal: true` is set on the
`tars-apps`/`tars-storage` Argo CD Applications, a live `kubectl apply`
against anything Argo CD manages gets silently reverted back to match
`main` within moments (not instantly — a live test can appear to pass by
winning a race against that reconcile cycle, then fail once merged if the
actual committed content is broken) — validate with `--dry-run=client`, but
treat a live-tested-before-merge result as provisional and re-verify after
the real merge lands.

### Secrets

- **`discord-alerts`** (`apps` namespace, out-of-band): `bot_token` only —
  the `Tars` Discord bot, invited to the server once with Send Messages/
  Create Posts in Forums/Add Reactions. No `webhook_url` key anymore.
- **`router-ssh-key`** / **`case-ssh-key`** (`apps` namespace, out-of-band):
  dedicated ed25519 keypairs, public half authorized on the router/Case
  respectively — not the same key used for interactive SSH access.
- **`github-pat`** (`apps` namespace, key `token`): the same classic PAT
  wired into Argo CD's repo credentials, reused for `gh issue` read/write.
- **`uptime-kuma-push`** (`apps` namespace): one push-monitor URL per key
  (`pod_health_check_url`, `resource_pressure_check_url`,
  `tars_appdata_backup_url`, `case_worker_appdata_backup_url`,
  `pi_appdata_backup_url`). `pod-health-check`/`resource-pressure-check`
  ping unconditionally at the end of every run; the backup CronJobs ping
  only on success. This catches a job crashing before it ever reaches its
  own queue-write step — something the queue/triage alerting above can't
  see on its own. Configured in Uptime Kuma itself (not tracked in git).

### Resolved-issue notice back to Discord

When Claude opens a new tracked issue, the bot's `POST /channels/{id}/threads`
response includes both the created Forum thread's id *and* the original
message's id, which get stashed in the issue body as invisible HTML
comments (`<!-- discord_thread_id: ... discord_message_id: ... -->`) via
one `gh issue edit` call. [`.github/workflows/issue-closed-notify.yml`](.github/workflows/issue-closed-notify.yml)
triggers whenever any issue in this repo closes, looks for those markers,
and — only if present — posts a "✅ Resolved" follow-up into that exact
thread and adds a ✅ reaction directly on the original message (a no-op for
any issue without the markers, e.g. one filed by hand, or opened before
this existed).

Both steps use the bot (`DISCORD_BOT_TOKEN` repo secret — a real Discord
bot created via the Discord Developer Portal, invited to the server with
Send Messages/Create Posts in Forums/Add Reactions), not a webhook — a
webhook can only post into threads under its own parent channel, and
findings now route to one of three different channels, so the bot's
"post to any channel I have access to" is what makes this work without a
separate webhook per channel. Separate from anything in-cluster since
Actions runs on GitHub's infrastructure, not Tars.

A recurring problem — Claude decides to comment on an existing issue
rather than open a new one — looks up that issue's stashed
`discord_thread_id` first and, if found, posts the follow-up as a reply in
that same original thread (`?thread_id=...`) instead of spawning a new
Forum post. Falls back to creating a new post only if the existing issue
predates this feature and has no marker to find.

