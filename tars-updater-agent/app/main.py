import os
import time
import schedule
import logging
from datetime import datetime
from app.config import config
from app.scanners.k8s_scanner import get_running_containers, check_image_updates
from app.scanners.trivy_scanner import scan_image
from app.scanners.os_scanner import get_os_updates
from app.storage.db import (
    has_cve_been_reported, mark_cve_reported,
    record_vulnerability_finding, record_update_finding,
)
from app.notifiers.discord import post_digest_thread, format_weekly_digest

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def queue_for_triage(source, text):
    # pod-health-check drains this alongside its own findings and runs it
    # through Claude/gh triage - this service can't co-locate with the
    # Claude config PVC, so it just drops a file here instead.
    queue_dir = "/queue/.tars-triage-queue"
    os.makedirs(queue_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    with open(f"{queue_dir}/{source}-{stamp}.txt", "w") as f:
        f.write(text)


def daily_job():
    logger.info("Starting daily scan job...")
    
    new_criticals = []
    
    # 1. Scan Docker Containers for CRITICAL CVEs
    containers = get_running_containers()
    for c in containers:
        vulns = scan_image(c["image"])
        for v in vulns:
            record_vulnerability_finding(v)
            if not has_cve_been_reported(v["cve_id"], v["target"]):
                new_criticals.append(v)
                mark_cve_reported(v["cve_id"], v["target"])
                
    # 2. Queue for Claude triage if necessary - pod-health-check drains this
    # and posts the triaged result to Discord (UPDATER_AGENT_CHANNEL_ID via
    # the Tars bot). No direct alert here; the queue IS the alert path.
    if new_criticals:
        logger.warning(f"Found {len(new_criticals)} new critical vulnerabilities. Queuing for triage.")
        lines = [f"New critical CVE: {v['cve_id']} in {v['target']}" for v in new_criticals]
        queue_for_triage("tars-updater-critical-cve", "\n".join(lines))
    else:
        logger.info("Daily scan complete. No new critical vulnerabilities.")

def weekly_job():
    logger.info("Starting weekly digest job...")
    
    # 1. Get OS Updates
    os_updates = get_os_updates()
    
    # 2. Get Container Updates
    containers = get_running_containers()
    container_updates = check_image_updates(containers)

    # 3. Persist findings so they survive beyond the digest post
    for item in os_updates + container_updates:
        record_update_finding(item)

    # 4. Post digest to Discord - routine informational summary, not a
    # problem report, so this posts directly to a plain channel rather than
    # going through the Claude-triage queue (see repo README's Alerting
    # section).
    digest = format_weekly_digest(os_updates, container_updates)
    post_digest_thread(os.environ.get("DIGEST_CHANNEL_ID"), digest)
    logger.info("Weekly digest posted to Discord.")

def main():
    daily_time = config.get("schedule", {}).get("daily_scan_time", "02:00")
    weekly_day = config.get("schedule", {}).get("weekly_digest_day", "sunday").lower()
    weekly_time = config.get("schedule", {}).get("weekly_digest_time", "08:00")

    logger.info(f"Scheduling daily scan at {daily_time}")
    schedule.every().day.at(daily_time).do(daily_job)

    logger.info(f"Scheduling weekly digest on {weekly_day} at {weekly_time}")
    
    try:
        getattr(schedule.every(), weekly_day).at(weekly_time).do(weekly_job)
    except AttributeError:
         logger.error(f"Invalid day of week: {weekly_day}")
         return
    
    logger.info("Tars Updater Agent started. Waiting for scheduled jobs...")
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
