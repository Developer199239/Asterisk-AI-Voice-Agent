"""
LLM Service - Main Entry Point
"""

import sys
from pathlib import Path

print("LLM Service - v2.0")
print(f"Python version: {sys.version}")
print(f"Python path: {sys.path}")

# Check if shared directory exists
shared_path = Path(__file__).parent.parent.parent / "shared"
print(f"Shared path: {shared_path}")
print(f"Shared path exists: {shared_path.exists()}")

if shared_path.exists():
    print(f"Shared directory contents: {list(shared_path.iterdir())}")
else:
    print("Shared directory does not exist!")

# Try to import
try:
    sys.path.append(str(shared_path))
    print("Added shared path to sys.path")
    
    from config import CallControllerConfig
    print("Successfully imported CallControllerConfig")
    
    from redis_client import RedisClient
    print("Successfully imported RedisClient")
    
except ImportError as e:
    print(f"Import error: {e}")
    print(f"Current sys.path: {sys.path}")
except Exception as e:
    print(f"Other error: {e}")

print("LLM Service - End")