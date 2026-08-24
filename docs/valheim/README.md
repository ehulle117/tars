# Valheim Server on Tars

A vanilla Valheim dedicated server running on the Tars k3s cluster, reachable
from outside the LAN over Tailscale.

- **Manifests:** [`apps/valheim.yaml`](../../apps/valheim.yaml)
- **Player-facing guide:** [`CONNECT.md`](./CONNECT.md) — send this to friends
- **Image:** [`ghcr.io/lloesche/valheim-server`](https://github.com/lloesche/valheim-server-docker)

## How the networking works

The pod runs two containers that share a network namespace:

```
                    ┌─────────────────── pod: valheim ───────────────────┐
  friend's PC       │                                                    │
  (their tailnet)   │   ┌──────────────┐        ┌─────────────────────┐  │
        │           │   │  tailscale   │        │  valheim-server     │  │
        └── WireGuard ──▶  sidecar     │──lo──▶ │  UDP 2456 / 2457    │  │
            (UDP)   │   │  kernel mode │        │  HTTP 8080 (status) │  │
                    │   └──────────────┘        └─────────────────────┘  │
                    └────────────────────────────────────────────────────┘
                                    │
  LAN players ──────────────────────┘  valheim-svc (LoadBalancer, UDP)
```

Because the sidecar is in the same network namespace, the pod's **tailnet IP is
the Valheim server address**. No port forwarding, no public exposure, and no
NAT punch-through to hope for. LAN players can skip Tailscale and use the
LoadBalancer IP directly.

Trade-off worth knowing: every external player must install Tailscale and be
accept a share invite. That's the price for not opening UDP 2456 to
the internet.

**Deployment is automatic.** Argo CD (`tars-apps`, in the `argocd` namespace)
watches this repo's `apps/` directory on `main` with auto-sync enabled. Merging
a manifest change here is enough — nothing needs to be run by hand except the
two secrets below, which are deliberately kept out of git.

## One-time setup

### 1. Create the secrets

Neither secret is in git — create both in the `apps` namespace:

```sh
kubectl create secret generic valheim-tailscale-auth \
  --namespace apps \
  --from-literal=TS_AUTHKEY='tskey-auth-xxxxxxxxxxxx'

kubectl create secret generic valheim-server \
  --namespace apps \
  --from-literal=SERVER_NAME='Tars Valheim' \
  --from-literal=WORLD_NAME='Midgard' \
  --from-literal=SERVER_PASS='changeme' \
  --from-literal=ADMINLIST_IDS='76561198000000000'
```

Get the `TS_AUTHKEY` value from the Tailscale admin console: **Settings → Keys
→ Generate auth key**, with:

- Reusable: **yes**
- Ephemeral: **no** (the node must keep its identity across pod restarts)
- Pre-approved: **yes** (if device approval is on)

Notes:

- Paste each `--from-literal` value in one motion rather than typing it —
  a key or password that gets cut off mid-entry (e.g. hitting enter early in a
  terminal) creates a secret that *looks* fine but fails validation once the
  container tries to use it. If the `tailscale` container ends up crash-looping
  with `invalid key: unable to validate API key` in its logs, this is almost
  always why — delete the secret and recreate it carefully.
- `SERVER_PASS` must be at least 5 characters and cannot appear in `SERVER_NAME`.
- `WORLD_NAME` is the world *filename*. Changing it later generates a brand new
  world rather than renaming the existing one.
- `ADMINLIST_IDS` is space-separated SteamID64 values. Find yours at
  [steamid.io](https://steamid.io). Admins get `devcommands`, kick, and ban.

Once both secrets exist, the pod (already deployed by Argo CD) will pick them
up and restart on its own within a minute or so — no manual redeploy needed.

### 2. Approve the device and find its tailnet IP

First boot downloads ~2 GB of server files and takes several minutes. Watch it:

```sh
kubectl -n apps logs -f deploy/valheim -c valheim
```

The Valheim server itself is up once the log shows periodic `Connections N
ZDOS:...` lines.

The `tailscale` sidecar registers as a new device called `valheim` — if device
approval is enabled on your tailnet, approve it in the admin console under
**Machines** before it gets an IP. Once approved, find its address:

```sh
kubectl -n apps exec deploy/valheim -c tailscale -- tailscale ip -4
```

Note this IP down — it's used in the access rule below, and again in
[`CONNECT.md`](./CONNECT.md).

### 3. Add the access rule

This uses Tailscale's node-**sharing** feature rather than tailnet
membership — shared users don't count against your plan's member-seat limit,
which matters once you have more than a couple of friends. The rule grants
`autogroup:shared` (everyone the node is later shared with, in step 4) access
to just the two game ports:

If you're using the visual **Access Rules** builder, add a rule with:

| Field | Value |
| --- | --- |
| Source | `autogroup:shared` |
| Destination | the tailnet IP from step 2 (e.g. `100.x.y.z`) |
| Protocol | `UDP` |
| Port(s) | `2456-2457` |

The destination field in the visual builder only accepts IPs, tags, or
groups — not a device's plain name. If you'd rather edit the policy file
directly, the equivalent (Grants syntax) is:

```jsonc
"grants": [
  {
    "src": ["autogroup:shared"],
    "dst": ["100.x.y.z"],
    "ip":  ["udp:2456-2457"],
  },
],
```

This is deliberately narrow — shared users get the two Valheim UDP ports on
this one device and nothing else on the tailnet.

**Caveat:** because the rule targets a literal IP rather than a name, it needs
to be updated if the node ever re-registers with a new IP (see the
troubleshooting table below for when that happens). Enabling MagicDNS (Admin
console → DNS) is still worth doing separately — it doesn't change how this
rule works, but it gives players a stable name to type instead of the raw IP,
which is what [`CONNECT.md`](./CONNECT.md) uses.

### 4. Share the node with each friend

**Admin console → Machines → `valheim` → ⋯ → Share…**, then send each friend
the generated invite link (or use one reusable link for the whole group).
Accepting the link doesn't make them a tailnet member and doesn't use up a
seat — it only grants access to the one shared device, scoped further by the
access rule above to just the game ports.

### 5. Disable key expiry on the node

The auth key from step 1 is only used once, to bootstrap the node's first
join — after that the sidecar persists its identity in the
`valheim-tailscale-state` secret and never touches the auth key again. What
*does* matter long-term is the node's own session, which by default expires
(~180 days) and would otherwise kick the server off the tailnet until someone
re-authenticates it interactively.

Once the pod has registered and shows up in the admin console, disable that:

**Admin console → Machines → `valheim` → ⋯ → Disable key expiry**

This is a one-time step. After it's set, the node never needs re-auth again,
regardless of the original auth key's own expiry. (If the
`valheim-tailscale-state` secret is ever deleted, the node loses its identity
and this has to be redone after a fresh bootstrap.)

### 6. Send the connect guide

Send [`CONNECT.md`](./CONNECT.md) to each friend along with their share
invite link from step 4, filled in with the actual server address from
step 2.

## Operations

**Status page** (LAN, via the LoadBalancer IP on port 8080) reports player count
and uptime as JSON:

```sh
kubectl -n apps port-forward deploy/valheim 8080:8080
curl -s localhost:8080/status.json
```

This endpoint is occasionally flaky right after a restart (a
`TimeoutError('timed out')` in the response while the game process finishes
booting) — check the container logs for `Connections N ZDOS:...` lines as the
more reliable signal that the server is actually up.

**Backups.** The container snapshots the world every 6 hours to
`/backups/valheim` on the NFS share (`nfs-media-pvc` → `/mnt/user/data`),
keeping 14 days. The `local-path` config volume is *also* covered by the nightly
`tars-appdata-backup` CronJob, so there are two independent copies.

**Restore a world:**

```sh
kubectl -n apps scale deploy/valheim --replicas=0
# copy the .db and .fwl out of /backups/valheim into /config/worlds_local/
kubectl -n apps scale deploy/valheim --replicas=1
```

**Updates.** The container checks for Valheim server updates every 15 minutes and
restarts only when nobody is connected (`RESTART_IF_IDLE=true`). Clients must be
on the same game version, so a Valheim patch day means everyone updates.

**Resource use.** Valheim wants ~3 GB idle and grows with world size and player
count; the manifest requests 4 GB and caps at 8 GB. If Tars is tight on memory,
pin this to a specific node with a `nodeSelector` rather than letting the
scheduler pick.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Friend can't reach the server at all | They haven't accepted the share invite yet, or Tailscale isn't running on their machine |
| Tailscale connected but the join times out | The access rule's destination IP no longer matches the node's actual IP (see caveat in step 3), or the rule wasn't saved |
| `tailscale` container `CrashLoopBackOff` with `invalid key: unable to validate API key` in logs | The `TS_AUTHKEY` value in the secret got truncated when it was created — delete and recreate the secret with a freshly generated key, pasted in one motion |
| Node shows offline after a restart | `valheim-tailscale-state` secret was deleted, or the ServiceAccount lost secret write permission |
| Status page (`:8080/status.json`) returns a `TimeoutError` | Usually transient right after boot — check container logs for `Connections N ZDOS:...` instead |
| "Incorrect password" with the right password | Client cached an old world; have them clear the entry and re-add it |
| Server not in the friend's server list | Expected — `SERVER_PUBLIC=false`. Join by IP/name directly |

## Deliberately not done

- **No crossplay.** `CROSSPLAY=true` routes through Microsoft PlayFab relays,
  which adds latency and gives up the point of running this on the LAN.
- **No mods.** The layout is mod-ready — BepInEx installs into `/config` — but
  nothing is loaded today. Adding mods means every player installs matching
  versions.
- **No public exposure.** UDP 2456 is not reachable from the internet by design.
