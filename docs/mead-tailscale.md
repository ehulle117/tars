# Mead Log over Tailscale

Mead Log (`apps/mead.yaml`) runs a Tailscale sidecar that joins the tailnet as its own
device, `homebrew`. Sharing that one device gives someone off the LAN (Gabe) the app and
nothing else: not tars, not case, not the rest of the tailnet. Same pattern as
[valheim2](valheim2/README.md).

The app has no login, so anyone it's shared with can add, edit and delete everything.

## Setup (once, in this order: the pod won't start until step 3 is done)

### 1. Policy: allow the port

The sidecar uses `tag:game`, which the valheim nodes already use, so `tagOwners` needs no
change. In the admin console under **Access controls**, add one grant:

```jsonc
"grants": [
  {
    "src": ["autogroup:shared"],   // people a device is shared with
    "dst": ["tag:game"],
    "ip":  ["tcp:8770"],
  },
],
```

Sharing is still per device: Gabe reaches only what's shared with him, so this doesn't
open anything on the valheim servers to him (and nothing listens on 8770 there).

### 2. Auth key

**Settings → Keys → Generate auth key**: not reusable, **pre-approved**. A plain
untagged key works, same as valheim: the sidecar asks for `tag:game` itself. Tagged
devices don't expire, so no key-expiry step is needed.

### 3. Secret

```sh
kubectl create secret generic mead-tailscale-auth --namespace apps \
  --from-literal=TS_AUTHKEY='tskey-auth-…'
```

### 4. Deploy

Push `apps/mead.yaml` and let Argo CD sync it. Then:

```sh
kubectl -n apps exec deploy/mead -c tailscale -- tailscale ip -4
```

### 5. Share with Gabe

**Machines → `homebrew` → ⋯ → Share…**, then send him the invite link. Once he accepts,
he opens `http://<tailnet IP from step 4>:8770`.

To revoke access: **Machines → `homebrew` → ⋯ → Share…** and remove him.
