import os
from pathlib import Path

# Determine if running in Docker or Local
if os.path.exists("/app/project"):
    PROJECT_ROOT = "/app/project"
else:
    # Fallback to local development path (3 levels up from this file: backend/api/settings.py -> backend/api -> backend -> admin_ui -> root)
    # Wait, settings.py is in admin_ui/backend/settings.py
    # So it's: settings.py -> backend -> admin_ui -> root (3 levels up)
    PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config/ai-agent.yaml")
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
USERS_PATH = os.path.join(PROJECT_ROOT, "config/users.json")
