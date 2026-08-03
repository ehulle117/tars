import docker
import requests
import logging
from app.config import config

logger = logging.getLogger(__name__)

def get_running_containers():
    if not config.get("scanners", {}).get("enable_docker", True):
        return []
        
    try:
        client = docker.from_env()
        containers = client.containers.list()
        
        ignored = config.get("ignore", {}).get("containers", [])
        
        results = []
        for c in containers:
            if c.name in ignored:
                continue
            
            image_tags = c.image.tags
            image_name = image_tags[0] if image_tags else c.image.id
            
            results.append({
                "name": c.name,
                "image": image_name,
                "id": c.id
            })
        return results
    except Exception as e:
        logger.error(f"Failed to get running containers: {e}")
        return []

def check_image_updates(containers):
    # Validating digests with Docker Hub V2 API without heavy downloads
    updates = []
    # Placeholder for registry digest checks
    # A full implementation would query auth tokens from Docker Hub, 
    # fetch the remote manifest, and compare it against the local container digest.
    return updates
