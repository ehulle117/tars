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

Trade-off worth knowing: every external player must install Tailscale and accept
a share invite. That's the price for not opening UDP 2456 to the internet.

## One-time setup

### 1. Tailscale: tag, ACL, and auth key

In the [Tailscale admin console](https://login.tailscale.com/admin):

**a. Define the `tag:game` tag** (Access Controls → edit policy file):

```jsonc
"tagOwners": {
  "tag:game": ["autogroup:admin"],
},
```

**b. Let shared users reach the game ports.** `autogroup:shared` covers everyone
you invite without having to list their emails:

```jsonc
"acls": [
  // Existing rules stay as they are.
  {
    "action": "accept",
    "src":    ["autogroup:shared"],
    "dst":    ["tag:game:2456-2457"],
  },
],
```

This is deliberately narrow — shared users get the two Valheim UDP ports on the
game node and nothing else on the tailnet.

**c. Generate an auth key** (Settings → Keys → Generate auth key):

- Reusable: **yes**
- Ephemeral: **no** (the node must keep its identity across pod restarts)
- Pre-approved: **yes** (if device approval is on)
- Tags: **`tag:game`**

Also confirm **MagicDNS** is enabled (Admin console → DNS) so the server gets
a vanity hostname like `valheim.<tailnet>.ts.net` instead of a raw IP.

### 2. Create the secrets

Neither secret is in git. Create both in the `apps` namespace:

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

Notes:

- `SERVER_PASS` must be at least 5 characters and cannot appear in `SERVER_NAME`.
- `WORLD_NAME` is the world *filename*. Changing it later generates a brand new
  world rather than renaming the existing one.
- `ADMINLIST_IDS` is space-separated SteamID64 values. Find yours at
  [steamid.io](https://steamid.io). Admins get `devcommands`, kick, and ban.

### 3. Deploy

```sh
kubectl apply -f apps/valheim.yaml
kubectl -n apps rollout status deploy/valheim
```

First boot downloads ~2 GB of server files and takes several minutes. Watch it:

```sh
kubectl -n apps logs -f deploy/valheim -c valheim
```

The server is up once the log reads `Game server connected`.

### 4. Find the server address

With [MagicDNS](https://tailscale.com/kb/1081/magicdns) enabled on the tailnet
(Admin console → DNS → MagicDNS), the pod's `TS_HOSTNAME=valheim` gives it a
stable vanity name instead of a raw IP:

```
valheim.<your-tailnet>.ts.net
```

Find the exact name in the admin console under **Machines**, or from inside
the cluster:

```sh
kubectl -n apps exec deploy/valheim -c tailscale -- tailscale status --self --json | grep DNSName
```

That name plus port `2456` is what players enter. It's stable across restarts
because the node state is persisted in the `valheim-tailscale-state` secret,
and it beats handing out a raw `100.x.y.z` address. If MagicDNS is ever off,
`tailscale ip -4` still gives the underlying IP as a fallback.

### 5. Share the node with friends

Admin console → **Machines** → `valheim` → **⋯** → **Share…**. Send each friend
an invite link (or use a reusable link for the group). Then send them
[`CONNECT.md`](./CONNECT.md).

## Operations

**Status page** (LAN, via the LoadBalancer IP on port 8080) reports player count
and uptime as JSON:

```sh
kubectl -n apps port-forward deploy/valheim 8080:8080
curl -s localhost:8080/status.json
```

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
| Friend can't reach the server at all | They haven't accepted the share invite, or Tailscale isn't running on their machine |
| Tailscale connected but the join times out | ACL doesn't allow `autogroup:shared` → `tag:game:2456-2457` |
| Sidecar `CrashLoopBackOff` | Auth key expired or was ephemeral; regenerate and update the secret |
| Node shows offline after a restart | `valheim-tailscale-state` secret was deleted, or the ServiceAccount lost secret write permission |
| "Incorrect password" with the right password | Client cached an old world; have them clear the entry and re-add it |
| Server not in the friend's server list | Expected — `SERVER_PUBLIC=false`. Join by IP |

## Deliberately not done

- **No crossplay.** `CROSSPLAY=true` routes through Microsoft PlayFab relays,
  which adds latency and gives up the point of running this on the LAN.
- **No mods.** The layout is mod-ready — BepInEx installs into `/config` — but
  nothing is loaded today. Adding mods means every player installs matching
  versions.
- **No public exposure.** UDP 2456 is not reachable from the internet by design.
