# Mead Log over Tailscale

Mead Log (`apps/mead.yaml`) runs a Tailscale sidecar that joins the tailnet as its own
device, `homebrew`. Sharing that one device gives someone off the LAN (Gabe) the app and
nothing else: not tars, not case, not the rest of the tailnet.

The app has no login, so anyone it's shared with can add, edit and delete everything.

## Setup (once, in this order: the pod won't start until step 3 is done)

### 1. Policy: allow the port

The sidecar uses `tag:game`, which already has a `tagOwners` entry, so that needs no
change. In the admin console under **Access controls**, add one grant:

```jsonc
"grants": [
  {
    "src": ["autogroup:shared"],   // people a device is shared with
    "dst": ["tag:game"],
    "ip":  ["tcp:80"],
  },
],
```

Sharing is still per device: Gabe reaches only what's shared with him. Port 80 on
`homebrew` forwards to the app (see the `mead-tailscale-serve` ConfigMap), so the address
has no port number.

### 2. Auth key

**Settings → Keys → Generate auth key**: not reusable, **pre-approved**. A plain
untagged key works: the sidecar asks for `tag:game` itself. Tagged
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
he opens `http://homebrew.tail94a391.ts.net`, or `http://<tailnet IP from step 4>` if that
name doesn't resolve for him.

To revoke access: **Machines → `homebrew` → ⋯ → Share…** and remove him.
