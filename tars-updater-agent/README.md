# Tars Updater Agent

A robust, self-hosted Python service built to run on Tars. It monitors Docker containers and the host OS for updates, and actively scans for critical vulnerabilities using Trivy.

## Features
- **Daily Vulnerability Scanning**: Connects to the local Docker socket and runs Trivy against running images. If a `CRITICAL` severity CVE is found, it sends an immediate alert.
- **Weekly Digest**: Summarizes pending baremetal OS updates and container updates into a clean HTML email.
- **State Tracking**: Uses a local SQLite database to track what has already been reported, ensuring you don't suffer from alert fatigue.
- **Persistent Findings History**: Every scanned vulnerability and pending update is also written to `vulnerability_findings` / `update_findings` tables in the same SQLite DB (with first/last seen timestamps), independent of email dedup — so findings remain queryable even after the alert email has been sent. View them with:
  ```bash
  python -m app.report
  ```

## Deployment

1. Rename `agent-config.example.yaml` to `agent-config.yaml` and configure your SMTP settings.
2. Ensure you have a GitHub Personal Access Token if publishing via GitHub Actions.
3. Use the provided `docker-compose.example.yml` to deploy the agent to Tars.

### Required Volumes
The agent must have access to the Docker socket to identify running containers:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```
