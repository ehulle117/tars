import os
import yaml
import logging

logger = logging.getLogger(__name__)

def load_config(path="agent-config.yaml"):
    if not os.path.exists(path):
        # Fallback to example if running locally for dev without config
        path = "agent-config.example.yaml"
        if not os.path.exists(path):
             logger.warning(f"No config file found at {path}")
             return {}
    
    with open(path, 'r') as f:
        config = yaml.safe_load(f)
        
    # Inject env vars
    if "smtp" in config:
        config["smtp"]["password"] = os.environ.get("SMTP_PASSWORD", "")
        
    return config

config = load_config()
