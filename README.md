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
| Appdata backup | [`apps/backup-cronjob.yaml`](apps/backup-cronjob.yaml), [`apps/case-worker-appdata-backup.yaml`](apps/case-worker-appdata-backup.yaml), [`apps/pi-appdata-backup.yaml`](apps/pi-appdata-backup.yaml) | `alpine` | CronJobs, daily (3:00/3:15/3:30 AM), copy each node's local-path appdata to Case; posts to Discord (`discord-alerts` secret) and queues for Claude triage if a run fails |
| *arr queue check | [`apps/arr-queue-check.yaml`](apps/arr-queue-check.yaml) | `python:3.12-alpine` | CronJob, daily 8 AM, checks Radarr/Sonarr/Lidarr/Readarr queues for stuck imports (24h+) and Prowlarr for long-failing indexers; queues a report for Claude triage only when something's actually wrong |
| Pod health check | [`apps/pod-health-check.yaml`](apps/pod-health-check.yaml) | `python:3.12-alpine` | CronJob, every 15 min, flags CrashLoopBackOff/ImagePullBackOff/OOMKilled/high-restart/stuck-Pending pods cluster-wide. Read-only via the `cluster-health-checker` ClusterRole. When it finds something, Claude Code triages it (checks for an existing open GitHub issue via `gh`, opens/comments/skips accordingly) and posts the resulting one-line decision to a Discord Forum channel — see "Claude-triaged alerts" below. |
| Resource pressure check | [`apps/resource-pressure-check.yaml`](apps/resource-pressure-check.yaml) | `python:3.12-alpine` | CronJob, every 30 min, checks node CPU/memory (via metrics-server) and DiskPressure/MemoryPressure conditions, plus Case's NFS export disk usage above 90%. Same Claude-triage-on-finding behavior as Pod health check above. |
| Claude Code dev pod | [`apps/claude-code.yaml`](apps/claude-code.yaml) | `node:22-bookworm-slim` + `@anthropic-ai/claude-code` | Persistent pod you `kubectl exec` into for interactive Claude Code sessions against this repo/cluster. Not a service — just `sleep infinity` with PVCs for `/workspace` and `~/.claude` so login survives restarts. |
| Insight digest | [`apps/tars-insight-digest.yaml`](apps/tars-insight-digest.yaml) | same image as the dev pod above | CronJob, every 6h, has Claude Code itself (no separate Anthropic API billing — reuses the dev pod's login via the shared `claude-code-config-pvc`) read cluster state and judge real issues vs. noise, posting a curated digest to a dedicated Discord channel. Read-only via the `tars-insight-vm` ServiceAccount (created out-of-band, not in this repo) — Claude never sees the bot token or posts to Discord itself; a plain shell step outside its tool loop does that, since Claude Code's own Bash-tool safety check refuses to expand env vars that look like secrets. |

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

Cluster-health CronJobs (pod health, resource pressure, backup failures) and
Argo CD's own `OutOfSync`/`Degraded` notifications all post to a single
Discord channel via webhook.

- **`discord-alerts` Secret** (`apps` namespace): created out-of-band, not
  committed. Keys: `webhook_url` (the three
  `*-appdata-backup` CronJobs' direct failure alert) and `bot_token` (the
  `Tars` Discord bot — used for everything else below, including
  `tars-insight-digest`'s recommendations, which used to post via a
  separate `recommendations_webhook_url` webhook until that webhook was
  deleted server-side; see issue #63).
- **Bot-posted digest channels** (plain env vars, not Secrets — channel IDs
  aren't sensitive), each a dedicated Forum channel so the two feeds don't
  mix:
  - `DIGEST_CHANNEL_ID` (`1547598576111194205`, "k8s-updates"):
    `tars-updater-agent`'s weekly OS/container update digest.
  - `RECOMMENDATIONS_CHANNEL_ID` (`1547614601506463906`,
    "insight-recommendations"): `tars-insight-digest`'s scheduled AI digest.
- All alerting is now Discord-only — the `smtp-auth` Secret is no longer
  referenced anywhere in this repo and can be deleted from the cluster.
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
back to match `main` within moments (on ArgoCD's own reconcile cycle, not
instantly — a live test can appear to pass by winning a race against that
cycle, then fail once merged if the actual committed content is broken) —
validate with `--dry-run=client`, but treat a live-tested-before-merge
result as provisional and re-verify after the real merge lands.

### Claude-triaged alerts

`pod-health-check` is where all Claude/`gh` triage actually happens, since
it's the only alert source both unpinned from any specific node *and*
running frequently (every 15 min). Two ways a finding gets to it:

1. **Direct** (`pod-health-check`, `resource-pressure-check`): neither is
   node-pinned for hostPath reasons, so both are scheduled onto
   `k3s-worker-case` alongside the `claude-code-config-pvc` and triage their
   own findings in the same run they detect them in.
2. **Queued** (everything else that used to only send an email or a raw
   Discord ping): `arr-queue-check` and the three `*-appdata-backup`
   CronJobs, plus `tars-updater-agent`'s critical-CVE alert, drop a small
   text file in `.tars-triage-queue/` on the shared `nfs-media-pvc` (already
   mounted in most of them for other reasons) whenever they'd otherwise have
   emailed/alerted. `pod-health-check` drains that directory every run,
   folds each file's content in alongside its own findings, and deletes them
   only after a successful triage+post — a failed run leaves them for the
   next attempt. This exists because those jobs are hard node-pinned (the
   backups, to their own host's hostPath) or simply not built to run Claude
   themselves (`tars-updater-agent`'s own container image), so they can't
   co-locate with the Claude config PVC directly.
   - Not everything routes here: `tars-updater-agent`'s weekly OS/update
     digest is a routine informational summary, not a problem report —
     opening a GitHub issue over "a package has an update available"
     doesn't make sense, so it's posted as a plain message via the `Tars`
     bot to a dedicated digest channel (`DIGEST_CHANNEL_ID`) instead of
     going through triage.
   - Argo CD's and Uptime Kuma's native notifications are also excluded —
     both only know how to POST to a fixed webhook URL, with no hook for a
     custom script to redirect through.

Either way, once there's something to triage, Claude checks `gh issue list`
for an existing open issue covering the finding before deciding whether to
open a new one, comment on the existing one, or conclude it's not actually
worth tracking. Claude's final response is a single Discord-ready line,
posted via the **`Tars` Discord bot** (not a webhook) as a new Forum post
using `POST /channels/{id}/threads`. Which of three Forum channels depends
on the finding's source — `pod-health-check`'s/`resource-pressure-check`'s
own findings and the appdata-backup queue files share one general
tracked-issues channel; `arr-queue-check` and `tars-updater-agent`'s
critical-CVE queue files each get their own dedicated channel — kept
separate from the regular alerts channel so tracked issues don't mix with
raw noise, and from each other so they're independently readable.

A bot (rather than a webhook) is what makes routing to three different
channels straightforward: one bot token can post to any channel it has
permission in, whereas each destination would otherwise need its own
webhook. `bot_token` (`discord-alerts` Secret) is the same bot used for
the resolved-issue reaction below — invited to the server once, with Send
Messages/Create Posts in Forums/Add Reactions granted broadly (simplest
for a personal homelab; scoping per-channel is possible if desired).

Needs, on top of what `pod-health-check`/`resource-pressure-check` already
require:
- `claude-code-config-pvc` mounted read-write at `/root/.claude` (same PVC
  the `claude-code` dev pod uses — its login is what authenticates these,
  no separate Anthropic API key)
- `github-pat` Secret (`apps` namespace, key `token`): the same classic PAT
  wired into Argo CD's repo credentials, reused here for `gh issue`
  read/write access via `GH_TOKEN`
- `GITHUB_REPO` env var (`ehulle117/tars`)
- `TRACKED_ISSUES_CHANNEL_ID` / `ARR_QUEUE_CHANNEL_ID` /
  `UPDATER_AGENT_CHANNEL_ID` env vars (plain channel ID values, not secret)
- Queue writers need `nfs-media-pvc` mounted (most already have it) and
  write to `<mount>/.tars-triage-queue/<source>-<timestamp>.txt` — the
  filename prefix (`arr-queue-check-`, `tars-updater-critical-cve-`, or
  anything else) is what routes a queued finding to the right channel

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

