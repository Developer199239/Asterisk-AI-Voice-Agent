import os
import shutil
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
ENV_EXAMPLE_PATH = os.path.join(PROJECT_ROOT, ".env.example")
USERS_PATH = os.path.join(PROJECT_ROOT, "config/users.json")


def ensure_env_file():
    """Copy .env.example to .env if .env doesn't exist.
    
    This ensures ai-engine can start with default/placeholder values
    before the wizard updates them with real credentials.
    """
    if not os.path.exists(ENV_PATH) and os.path.exists(ENV_EXAMPLE_PATH):
        shutil.copy(ENV_EXAMPLE_PATH, ENV_PATH)
        return True
    return False
