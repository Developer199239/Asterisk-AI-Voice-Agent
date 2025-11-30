from fastapi import APIRouter, HTTPException
import docker
from typing import List
from pydantic import BaseModel
import psutil
import os

router = APIRouter()

class ContainerInfo(BaseModel):
    id: str
    name: str
    status: str
    state: str

@router.get("/containers")
async def get_containers():
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            # Filter for project containers if needed, or return all
            # We can filter by label or name prefix if we want to be specific
            result.append({
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "state": c.attrs['State']['Status']
            })
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error listing containers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/containers/{container_id}/restart")
async def restart_container(container_id: str):
    try:
        client = docker.from_env()
        container = client.containers.get(container_id)
        container.restart()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/metrics")
async def get_system_metrics():
    try:
        # interval=None is non-blocking, returns usage since last call
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "cpu": {
                "percent": cpu_percent,
                "count": psutil.cpu_count()
            },
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "percent": memory.percent,
                "used": memory.used
            },
            "disk": {
                "total": disk.total,
                "free": disk.free,
                "percent": disk.percent
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def get_system_health():
    """
    Aggregate health status from Local AI Server and AI Engine.
    """
    async def check_local_ai():
        try:
            import websockets
            import json
            import asyncio
            
            # With host networking, use localhost instead of container name
            uri = os.getenv("HEALTH_CHECK_LOCAL_AI_URL", "ws://127.0.0.1:8765")
            print(f"DEBUG: Checking Local AI at {uri}")
            async with websockets.connect(uri, open_timeout=5) as websocket:
                print("DEBUG: Local AI connected, sending status...")
                await websocket.send(json.dumps({"type": "status"}))
                print("DEBUG: Local AI sent, waiting for response...")
                response = await asyncio.wait_for(websocket.recv(), timeout=5)
                print(f"DEBUG: Local AI response: {response[:100]}...")
                data = json.loads(response)
                if data.get("type") == "status_response":
                    return {
                        "status": "connected",
                        "details": data
                    }
                else:
                    return {
                        "status": "error",
                        "details": {"error": "Invalid response type"}
                    }
        except Exception as e:
            print(f"Local AI Check Error: {type(e).__name__}: {str(e)}")
            return {
                "status": "error",
                "details": {"error": f"{type(e).__name__}: {str(e)}"}
            }

    async def check_ai_engine():
        try:
            import httpx
            # With host networking, use localhost instead of container name
            url = os.getenv("HEALTH_CHECK_AI_ENGINE_URL", "http://127.0.0.1:15000/health")
            print(f"DEBUG: Checking AI Engine at {url}")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                print(f"DEBUG: AI Engine response: {resp.status_code}")
                if resp.status_code == 200:
                    return {
                        "status": "connected",
                        "details": resp.json()
                    }
                else:
                    return {
                        "status": "error",
                        "details": {"status_code": resp.status_code}
                    }
        except Exception as e:
            print(f"AI Engine Check Error: {type(e).__name__}: {str(e)}")
            return {
                "status": "error",
                "details": {"error": f"{type(e).__name__}: {str(e)}"}
            }

    import asyncio
    local_ai, ai_engine = await asyncio.gather(check_local_ai(), check_ai_engine())

    return {
        "local_ai_server": local_ai,
        "ai_engine": ai_engine
    }
