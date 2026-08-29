# Architecture

Two physical pieces: **Tars** (k3s cluster, compute) and **Case** (Unraid,
bulk storage). Everything deployed to Tars is defined in this repo's
[`apps/`](../apps/) and applied via GitOps, not by hand.

## System overview

```mermaid
flowchart TB
    subgraph internet["Internet"]
        friend["Friend's PC\n(Tailscale client)"]
    end

    subgraph tailnet["Tailscale network"]
        direction TB
    end

    subgraph tars["Tars — k3s cluster"]
        argocd["Argo CD\n(namespace: argocd)\nwatches apps/ on main, auto-sync"]

        subgraph appsns["namespace: apps"]
            homarr["Homarr\n(dashboard)"]
            arrstack["*arr stack\nSonarr / Radarr / Lidarr / Readarr\nProwlarr / Overseerr / Fetcharr"]
            deluge["Deluge\n(+ FlareSolverr)"]
            arm["ARM\n(disc ripper, needs /dev/sr0)"]
            hortusfox["HortusFox\n(app + mariadb)\n+ cron sidecars"]
            kuma["Uptime Kuma"]
            valheim["Valheim\n(+ tailscale sidecar)"]
            updater["tars-updater-agent\n(Trivy scans, update digest)"]
            backup["backup CronJob\n(daily 3 AM)"]
        end
    end

    subgraph case["Case — Unraid (192.168.8.152)"]
        nfs["NFS export\n/mnt/user/data"]
    end

    gitrepo[("this repo (git)\nmain branch")] -->|watches, auto-sync| argocd
    argocd -->|applies manifests| appsns

    arrstack -->|ReadWriteMany PVC\nnfs-media| nfs
    deluge -->|ReadWriteMany PVC\nnfs-media| nfs
    arm -->|ReadWriteMany PVC\nnfs-media| nfs

    valheim <-->|UDP over WireGuard,\nshared pod netns| tailnet
    friend <--> tailnet

    updater -->|daily email| smtp[("SMTP\nsmtp.gmail.com")]
    hortusfox -->|daily digest email| smtp
    kuma -.->|health checks| appsns
```

## Deployment flow (GitOps)

```mermaid
sequenceDiagram
    participant Dev as You
    participant Git as tars repo (main)
    participant Argo as Argo CD
    participant K3s as k3s API

    Dev->>Git: commit/push manifest change under apps/
    loop poll interval
        Argo->>Git: check for diff
    end
    Argo->>K3s: apply changed manifests
    K3s-->>Argo: rollout status
    Note over Dev,K3s: Secrets are the one exception —<br/>created out-of-band, never committed
```

## Storage model

- **Config/state** (app settings, databases like the HortusFox mariadb
  volume): `local-path` PVCs, backed by disk local to the k3s node. Covered
  by the daily `tars-appdata-backup` CronJob ([`apps/backup-cronjob.yaml`](../apps/backup-cronjob.yaml)).
- **Media** (`nfs-media-pvc`, `ReadWriteMany`): NFS export from Case at
  `192.168.8.152:/mnt/user/data`, mounted into every media-handling app
  (Sonarr/Radarr/Lidarr/Readarr/Deluge/ARM). Backup of this data is Case's
  responsibility, not this repo's.

## Notable design choices

- **Valheim over Tailscale, not port-forwarding**: the pod runs a Tailscale
  sidecar in the same network namespace as the game server, so the pod's
  tailnet IP *is* the game server address. No UDP ports opened to the
  internet, no NAT traversal. Full writeup: [`docs/valheim/README.md`](valheim/README.md).
- **Prowlarr + FlareSolverr**: Prowlarr centralizes indexer config for the
  *arr stack; FlareSolverr sits in front of indexers that use Cloudflare
  challenges.
- **tars-updater-agent**: a custom-built (not off-the-shelf) service —
  scans running container images with Trivy daily, and emails a weekly
  digest of pending OS/container updates. Findings persist in SQLite
  independent of email de-dup, queryable via `python -m app.report`. Source
  and deployment notes: [`tars-updater-agent/README.md`](../tars-updater-agent/README.md).
