from fastapi import APIRouter, HTTPException
import docker
from typing import Optional

router = APIRouter()

@router.get("/{container_name}")
async def get_container_logs(container_name: str, tail: int = 100):
    """
    Fetch logs from a specific container.
    """
    try:
        client = docker.from_env()
        # Filter by name to find the correct container
        # We use a loose match because docker compose prepends project name
        containers = client.containers.list(all=True, filters={"name": container_name})
        
        if not containers:
            # Try exact match if loose match fails or returns multiple (though list returns list)
            try:
                container = client.containers.get(container_name)
                containers = [container]
            except docker.errors.NotFound:
                raise HTTPException(status_code=404, detail=f"Container '{container_name}' not found")

        # Pick the first match (usually the most relevant one if unique enough)
        container = containers[0]
        
        # Get logs
        logs = container.logs(tail=tail).decode('utf-8')
        return {"logs": logs, "container_id": container.id, "name": container.name}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
