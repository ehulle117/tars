import time
import schedule
import logging
from app.config import config
from app.scanners.k8s_scanner import get_running_containers, check_image_updates
from app.scanners.trivy_scanner import scan_image
from app.scanners.os_scanner import get_os_updates
from app.storage.db import (
    has_cve_been_reported, mark_cve_reported,
    record_vulnerability_finding, record_update_finding,
)
from app.notifiers.email import send_email

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
                
    # 2. Dispatch alert if necessary
    if new_criticals:
        logger.warning(f"Found {len(new_criticals)} new critical vulnerabilities. Dispatching alert.")
        send_email(
            subject="🚨 CRITICAL SECURITY ALERT - Tars Updater",
            template_name="critical_alert.html",
            context={"vulnerabilities": new_criticals}
        )
    else:
        logger.info("Daily scan complete. No new critical vulnerabilities.")

def weekly_job():
    logger.info("Starting weekly digest job...")
    
    # 1. Get OS Updates
    os_updates = get_os_updates()
    
    # 2. Get Container Updates
    containers = get_running_containers()
    container_updates = check_image_updates(containers)

    # 3. Persist findings so they survive beyond the email inbox
    for item in os_updates + container_updates:
        record_update_finding(item)

    # 4. Dispatch Digest Email
    send_email(
        subject="📅 Tars Weekly Update Digest",
        template_name="weekly_digest.html",
        context={
            "os_updates": os_updates,
            "container_updates": container_updates
        }
    )
    logger.info("Weekly digest dispatched.")

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
