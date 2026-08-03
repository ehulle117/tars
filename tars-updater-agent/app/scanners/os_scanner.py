import subprocess
import logging
from app.config import config

logger = logging.getLogger(__name__)

def get_os_updates():
    if not config.get("scanners", {}).get("enable_os", False):
        return []
        
    ignored = config.get("ignore", {}).get("packages", [])
        
    try:
        # Assumes Debian/Ubuntu host for now.
        # This requires the container to have access to the host's apt package lists, 
        # or executed via nsenter to run on the host network/filesystem.
        cmd = ["apt-get", "-s", "upgrade"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        updates = []
        for line in result.stdout.split('\n'):
            if line.startswith('Inst '):
                parts = line.split()
                if len(parts) >= 3:
                    pkg_name = parts[1]
                    if pkg_name in ignored:
                        continue
                        
                    version = parts[2].strip('[]')
                    updates.append({
                        "name": pkg_name,
                        "version": version,
                        "type": "os-package"
                    })
        return updates
    except FileNotFoundError:
        logger.warning("apt-get not found. OS scanning skipped or unsupported.")
        return []
    except Exception as e:
        logger.error(f"Failed to scan OS updates: {e}")
        return []
