# Mead Log over Tailscale

Mead Log (`apps/mead.yaml`) runs a Tailscale sidecar that joins the tailnet as its own
device, `homebrew`. Sharing that one device gives someone off the LAN (Gabe) the app and
nothing else: not tars, not case, not the rest of the tailnet. Same pattern as
[valheim2](valheim2/README.md).

The app has no login, so anyone it's shared with can add, edit and delete everything.

## Setup (once, in this order: the pod won't start until step 3 is done)

### 1. Policy: allow the tag and the port

In the admin console under **Access controls**, add:

```jsonc
"tagOwners": {
  "tag:homebrew": ["autogroup:admin"],
},
"grants": [
  {
    "src": ["autogroup:shared"],   // people a device is shared with
    "dst": ["tag:homebrew"],
    "ip":  ["tcp:8770"],
  },
],
```

If your policy doesn't already let your own devices reach tagged devices, add your user
to `src` too.

### 2. Auth key

**Settings → Keys → Generate auth key**: not reusable, **pre-approved**, tagged
`tag:homebrew`. Tagged devices don't expire, so no key-expiry step is needed.

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
