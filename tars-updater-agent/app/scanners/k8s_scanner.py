import logging
from kubernetes import client, config as k8s_config
from app.config import config as app_config

logger = logging.getLogger(__name__)

def get_running_containers():
    if not app_config.get("scanners", {}).get("enable_docker", True):
        return []
        
    try:
        # Load in-cluster config when running inside the Kubernetes pod
        k8s_config.load_incluster_config()
        v1 = client.CoreV1Api()
        
        # Get all pods across all namespaces
        pods = v1.list_pod_for_all_namespaces(watch=False)
        
        ignored = app_config.get("ignore", {}).get("containers", [])
        
        results = []
        for pod in pods.items:
            # We only care about running pods
            if pod.status.phase != "Running":
                continue
                
            for container in pod.spec.containers:
                # Name it clearly for the email report (e.g., apps/tars-updater-agent/agent)
                name = f"{pod.metadata.namespace}/{pod.metadata.name}/{container.name}"
                
                if container.name in ignored or name in ignored:
                    continue
                
                results.append({
                    "name": name,
                    "image": container.image,
                    "id": f"{pod.metadata.namespace}-{pod.metadata.name}"
                })
        return results
    except Exception as e:
        logger.error(f"Failed to get running pods via Kubernetes API: {e}")
        return []

def check_image_updates(containers):
    # Validating digests with Docker Hub V2 API without heavy downloads
    updates = []
    # Placeholder for registry digest checks
    return updates
