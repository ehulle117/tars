# Ashlands Ascendant — Valheim 1.0 Server on Tars

A second Valheim dedicated server running on the Tars k3s cluster, for the new
1.0 world, named **Ashlands Ascendant** after 1.0's headline addition. Deployed alongside the original server (`apps/valheim.yaml`,
[docs/valheim/README.md](../valheim/README.md)) so the old world stays up
until we're done with it — this is not a migration, it's a second, independent
deployment.

- **Manifests:** [`apps/valheim2.yaml`](../../apps/valheim2.yaml)
- **Player-facing guide:** [`CONNECT.md`](./CONNECT.md) — send this to friends
- **Image:** [`ghcr.io/lloesche/valheim-server`](https://github.com/lloesche/valheim-server-docker)

Everything about how this works — the Tailscale sidecar networking, backup
behavior, update behavior, resource sizing, and troubleshooting — is identical
to the original server. See
[docs/valheim/README.md](../valheim/README.md#how-the-networking-works) for
the full explanation; only the differences are called out below.

## What's different from the original `valheim` deployment

| | Original (`valheim`) | New (`valheim2`) |
| --- | --- | --- |
| Deployment / pod | `valheim` | `valheim2` |
| Game / query ports | UDP 2456 / 2457 | UDP 2458 / 2459 |
| Tailscale hostname | `valheim` | `valheim2` |
| Config/server PVCs | `valheim-config-pvc` / `valheim-server-pvc` | `valheim2-config-pvc` / `valheim2-server-pvc` |
| Backup directory | `/backups/valheim` | `/backups/valheim2` |
| Secrets | `valheim-server`, `valheim-tailscale-auth`, `valheim-tailscale-state` | `valheim2-server`, `valheim2-tailscale-auth`, `valheim2-tailscale-state` |
| `valheim-server-docker` image tag | `latest` (should track the 1.0 release once it's tagged) | `latest` |

The port shift (2458/2459 instead of 2456/2457) is what lets both pods
coexist on the same LoadBalancer without a host-port clash, the same way the
status port (8080) is deliberately *not* exposed via LoadBalancer on either
deployment — see the comment in `apps/valheim.yaml` about the `arm-svc`
conflict.

## One-time setup

Same procedure as the original server, substituting the `valheim2` names
throughout. Summarized:

### 1. Create the secrets

```sh
kubectl create secret generic valheim2-tailscale-auth \
  --namespace apps \
  --from-literal=TS_AUTHKEY='tskey-auth-xxxxxxxxxxxx'

kubectl create secret generic valheim2-server \
  --namespace apps \
  --from-literal=SERVER_NAME='Ashlands Ascendant' \
  --from-literal=WORLD_NAME='Ashlands' \
  --from-literal=SERVER_PASS='changeme' \
  --from-literal=ADMINLIST_IDS='76561198000000000'
```

Same notes apply as the original: paste each value in one motion, `SERVER_PASS`
needs 5+ characters and must not appear in `SERVER_NAME`, `WORLD_NAME` is the
world *filename* (pick the real 1.0 world name before first boot — changing it
later creates a new world rather than renaming), and `ADMINLIST_IDS` is
space-separated SteamID64s from [steamid.io](https://steamid.io).

### 2. Approve the device and find its tailnet IP

```sh
kubectl -n apps logs -f deploy/valheim2 -c valheim
kubectl -n apps exec deploy/valheim2 -c tailscale -- tailscale ip -4
```

Approve the `valheim2` device in the Tailscale admin console (**Machines**) if
device approval is enabled.

### 3. Add the access rule

Same as the original, but scoped to the new ports and IP:

```jsonc
"grants": [
  {
    "src": ["autogroup:shared"],
    "dst": ["100.x.y.z"],   // valheim2's tailnet IP
    "ip":  ["udp:2458-2459"],
  },
],
```

### 4. Share the node with each friend

**Admin console → Machines → `valheim2` → ⋯ → Share…**

### 5. Disable key expiry on the node

**Admin console → Machines → `valheim2` → ⋯ → Disable key expiry**

### 6. Send the connect guide

Send [`CONNECT.md`](./CONNECT.md) to each friend with their share invite link
and the tailnet IP + port `2458` filled in.

## Operations

Identical to the original — see
[docs/valheim/README.md#operations](../valheim/README.md#operations), swapping
`valheim` for `valheim2` and `/backups/valheim` for `/backups/valheim2`.

## Running both servers side by side

- Both pods run independently; stopping/restoring one has no effect on the
  other.
- Resource requests are the same as the original (4Gi request / 8Gi limit per
  pod) — running both concurrently roughly doubles Valheim's footprint on the
  cluster. Watch node memory once both are up, and consider a `nodeSelector`
  to pin them to different nodes if Tars gets tight.
- When the old world is finally retired, decommission with:
  ```sh
  kubectl -n apps delete -f apps/valheim.yaml
  kubectl -n apps delete secret valheim-server valheim-tailscale-auth valheim-tailscale-state
  ```
  and remove `apps/valheim.yaml` / `docs/valheim/` from the repo. Until then,
  leave both in place.

## Deliberately not done

Same as the original — no crossplay, no mods, no public exposure. See
[docs/valheim/README.md#deliberately-not-done](../valheim/README.md#deliberately-not-done).
