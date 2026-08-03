import subprocess
import json
import logging
from app.config import config

logger = logging.getLogger(__name__)

def scan_image(image_name):
    if not config.get("scanners", {}).get("enable_trivy", True):
        return []
        
    logger.info(f"Running Trivy scan on {image_name}")
    try:
        # Run trivy and output as JSON, only reporting CRITICAL severity
        cmd = [
            "trivy", "image", 
            "--format", "json", 
            "--severity", "CRITICAL",
            "--quiet",
            "--no-progress",
            image_name
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"Trivy scan failed for {image_name}: {result.stderr}")
            return []
            
        data = json.loads(result.stdout)
        
        vulnerabilities = []
        if "Results" in data:
            for res in data["Results"]:
                if "Vulnerabilities" in res:
                    for vuln in res["Vulnerabilities"]:
                        vulnerabilities.append({
                            "cve_id": vuln.get("VulnerabilityID"),
                            "pkg_name": vuln.get("PkgName"),
                            "installed_version": vuln.get("InstalledVersion"),
                            "fixed_version": vuln.get("FixedVersion"),
                            "title": vuln.get("Title"),
                            "target": image_name
                        })
        return vulnerabilities
    except json.JSONDecodeError:
        logger.error(f"Failed to parse Trivy output as JSON for {image_name}")
        return []
    except Exception as e:
        logger.error(f"Exception during Trivy scan for {image_name}: {e}")
        return []
