from fastapi import APIRouter, HTTPException
import os
import httpx

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _ai_engine_base_url() -> str:
    # HEALTH_CHECK_AI_ENGINE_URL is used elsewhere; default assumes same network namespace.
    health_url = os.getenv("HEALTH_CHECK_AI_ENGINE_URL", "http://127.0.0.1:15000/health")
    return health_url.replace("/health", "")


@router.get("/status")
async def get_mcp_status():
    """Proxy MCP status from ai-engine (runs MCP servers)."""
    base = _ai_engine_base_url()
    url = f"{base}/mcp/status"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="AI Engine is not reachable")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{server_id}/test")
async def test_mcp_server(server_id: str):
    """Proxy a safe MCP server test to ai-engine container context."""
    base = _ai_engine_base_url()
    url = f"{base}/mcp/test/{server_id}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url)
        if resp.status_code not in (200, 500):
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="AI Engine is not reachable")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

