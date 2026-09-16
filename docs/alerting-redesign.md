# Alerting redesign (proposal, not yet implemented)

The current alerting grew one CronJob at a time: 8 scripts each hand-roll
their own Discord HTTP calls, thread-reuse logic is copy-pasted across three
of them almost verbatim, one path still posts via a raw webhook instead of
the bot, routing to a channel is a hardcoded dict buried in
`pod-health-check.py`, and "direct" vs "queued" triage are two different
code paths for the same job. This proposes one cohesive shape, bot-only.

## Principles

1. **One transport.** Every Discord post goes through the `Tars` bot. Drop
   the `discord-alerts` `webhook_url` secret and the raw webhook call in the
   appdata-backup jobs entirely — they already also drop a queue file, so
   the webhook call is pure duplication today.
2. **One shared library, not copy-paste.** `discord_post`,
   `find_or_create_thread`, and the triage-and-post flow currently exist
   almost identically in `pod-health-check.py`, `resource-pressure-check.py`,
   and `tars-insight-digest.yaml`. Pull them into one `ConfigMap`
   (`alert-lib`) every detector script mounts and imports.
3. **One queue, one drain, symmetric detectors.** Today `pod-health-check`
   and `resource-pressure-check` triage inline ("direct") because they
   happen to be co-located with the Claude config PVC; everything else
   drops a file and waits ("queued"). Collapse this: every detector — pod
   health included — only ever *detects* and drops a queue file. A single
   `tars-alert-triage` CronJob does nothing but drain the queue, dedupe
   against open GitHub issues via `gh`, and post. No more special-cased
   "this job happens to triage its own findings" path.
4. **One declarative routing table**, not a dict hand-edited inside
   `pod-health-check.py`. A small `routing.json` ConfigMap maps a source
   prefix to a channel id: adding a new detector means adding one line, not
   editing shared triage code.
5. **Two lanes, not five channels.** Collapse the current
   `TRACKED_ISSUES_CHANNEL_ID` / `ARR_QUEUE_CHANNEL_ID` /
   `UPDATER_AGENT_CHANNEL_ID` / `RECOMMENDATIONS_CHANNEL_ID` sprawl into:
   - **`#tars-alerts`** (Forum) — every triaged problem, any source, one
     thread per issue, thread title prefixed `[source]`.
   - **`#tars-digest`** (plain channel) — routine "you should know this"
     info that isn't a problem (software updates). Never triaged, no
     GitHub issue, just posted.
6. **Retire `tars-insight-digest`.** Its every-6h "re-derive cluster health
   from scratch via Claude" is redundant with the dedicated pod/resource
   detectors below and was the one thing not gated on "found something" —
   consolidating removes the overlap instead of patching around it.

## Resources monitored, and how

| Resource | Detector | Cadence | Lane |
|---|---|---|---|
| Tars pods (crash/restart/OOM/pending) | `pod-health-check` (K8s API, read-only) | 15 min | alert |
| Tars node pressure (CPU/mem/disk conditions) | `resource-pressure-check` (K8s + metrics-server) | 30 min | alert |
| Case NFS export capacity | `resource-pressure-check` (`shutil.disk_usage`) | 30 min | alert |
| Case array/disk health (SMART, array state) | **new** — Unraid API poll | 30 min | alert |
| Pi liveness (reachable, disk, key services) | **new** — SSH poll, same pattern as router-check | 15 min | alert |
| Router WAN status | `router-check` (SSH + `ubus`) | 30 min | alert |
| Router OS package updates | `router-check` (SSH + `opkg list-upgradable`) | 30 min | **digest**, not alert |
| *arr stuck imports / dead indexers | `arr-queue-check` | daily | alert |
| Deluge stalled/errored torrents | `deluge-stall-check` | 2h | alert |
| Argo CD app OutOfSync/Degraded | **new** — poll Argo's API instead of its native webhook, so it also routes through the bot | 15 min | alert |
| Appdata backup job failures (Tars/Pi/Case-worker) | the 3 `*-appdata-backup` CronJobs | daily | alert |
| Critical CVEs (Trivy) | `tars-updater-agent` | daily | alert |
| OS/container update summary | `tars-updater-agent` | weekly | **digest** |

Argo CD and Uptime Kuma's own native integrations only know how to hit a
fixed webhook URL — no way to redirect a bot token through them — so folding
Argo in means replacing its notification config with a small poller here,
same shape as every other detector. Uptime Kuma stays as internal
liveness/heartbeat plumbing (CronJobs push to it); it isn't itself wired to
Discord and doesn't need to be, since everything it watches already has its
own detector above.

## What gets displayed

**`#tars-alerts`** (Forum, one thread per tracked issue):
- Thread title: `[source] short description`, e.g. `[deluge] 12 stalled torrents`
- Thread body: Claude's 2-3 line plain-text summary of the finding and what
  it did (opened `tars#N`, commented, or judged not worth tracking)
- On the GitHub issue closing: an automatic "✅ Resolved: tars#N closed —
  title" reply in that same thread, plus a ✅ reaction on the original
  message — unchanged from today's `issue-closed-notify.yml`, which is
  already source-agnostic and needs no changes for this redesign
- A recurring finding replies into the *same* thread instead of opening a
  new one (existing `discord_thread_id` marker mechanism, unchanged)

**`#tars-digest`** (plain channel):
- Weekly OS/container update summary
- Router `opkg` upgradable package list
- No GitHub issue, no thread, no resolution tracking — it's informational,
  not a problem report

## What this doesn't change

- The GitHub-issue-as-source-of-truth model (`gh issue list/create/comment`,
  dedup by open issue) stays exactly as-is — it's the right mechanism,
  just currently invoked from two different code shapes.
- `issue-closed-notify.yml` stays as-is.
- `deluge-stall-check` and `router-check` (just shipped) stay as detectors,
  just re-plumbed to always queue (no behavior change — they already always
  queue) and picked up by the renamed/generalized `tars-alert-triage` drain
  job instead of `pod-health-check` specifically.

## Migration shape (for when you want to build it)

1. Add `alert-lib` ConfigMap (shared `discord_post`/`find_or_create_thread`/
   `triage_and_post` functions) and `routing.json` ConfigMap.
2. Rename `pod-health-check` → `tars-alert-triage`; strip its own
   pod-scanning logic out into a standalone `pod-health-check` detector that
   only ever queues (no more inline triage).
3. Same for `resource-pressure-check`: detector-only, queues instead of
   triaging inline.
4. Point every existing detector's queue-file prefix at `routing.json`
   instead of the hardcoded `GROUPS` dict.
5. Drop the `discord-alerts` webhook secret/calls from the 3 backup
   CronJobs; queue-only.
6. Add the two new detectors (Case array health, Pi liveness) and the Argo
   CD poller.
7. Delete `tars-insight-digest.yaml` and its `RECOMMENDATIONS_CHANNEL_ID`.
8. Collapse Discord channel IDs down to two (`ALERTS_CHANNEL_ID`,
   `DIGEST_CHANNEL_ID`) across every manifest.
