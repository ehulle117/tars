import os
from pathlib import Path

# Where mutable files (SQLite DB, state.json, photo cache) live. In the cluster
# this is the shared PVC mount, so all pods see the same SQLite WAL files.
DATA_DIR = Path(os.environ.get("ADSB_DATA_DIR", Path(__file__).parent.parent))
