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
        from datetime import datetime, timezone
        
        client = docker.from_env()
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            # Get image name
            image_name = c.image.tags[0] if c.image.tags else c.image.short_id
            
            # Calculate uptime from StartedAt
            uptime = None
            started_at = None
            if c.status == "running":
                try:
                    started_str = c.attrs['State'].get('StartedAt', '')
                    if started_str and started_str != '0001-01-01T00:00:00Z':
                        # Docker uses nanoseconds (9 digits), Python only handles microseconds (6)
                        # Truncate nanoseconds to microseconds and normalize timezone
                        import re
                        # Match: 2025-12-03T06:23:45.362413338+00:00 or 2025-12-03T06:23:45.362413338Z
                        match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d+)(Z|[+-]\d{2}:\d{2})?', started_str)
                        if match:
                            base = match.group(1)
                            frac = match.group(2)[:6].ljust(6, '0')  # Truncate to 6 digits
                            tz = match.group(3) or '+00:00'
                            if tz == 'Z':
                                tz = '+00:00'
                            normalized = f"{base}.{frac}{tz}"
                            started_dt = datetime.fromisoformat(normalized)
                        else:
                            # Fallback for simple format
                            started_dt = datetime.fromisoformat(started_str.replace('Z', '+00:00'))
                        
                        started_at = started_str
                        now = datetime.now(timezone.utc)
                        delta = now - started_dt
                        
                        # Format uptime nicely
                        days = delta.days
                        hours, remainder = divmod(delta.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        
                        if days > 0:
                            uptime = f"{days}d {hours}h {minutes}m"
                        elif hours > 0:
                            uptime = f"{hours}h {minutes}m"
                        else:
                            uptime = f"{minutes}m"
                except Exception as e:
                    print(f"Error calculating uptime for {c.name}: {e}")
            
            # Get exposed ports
            ports = []
            try:
                port_bindings = c.attrs.get('NetworkSettings', {}).get('Ports', {})
                for container_port, host_bindings in (port_bindings or {}).items():
                    if host_bindings:
                        for binding in host_bindings:
                            host_port = binding.get('HostPort', '')
                            if host_port:
                                ports.append(f"{host_port}:{container_port}")
            except Exception:
                pass
            
            result.append({
                "id": c.id,
                "name": c.name,
                "image": image_name,
                "status": c.status,
                "state": c.attrs['State']['Status'],
                "uptime": uptime,
                "started_at": started_at,
                "ports": ports
            })
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error listing containers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/containers/{container_id}/restart")
async def restart_container(container_id: str):
    """Restart a container using docker-compose with proper stop/remove/recreate."""
    import subprocess
    
    # Map container names to docker-compose service names
    service_map = {
        "ai_engine": "ai-engine",
        "admin_ui": "admin-ui",
        "local_ai_server": "local-ai-server"
    }
    
    service_name = service_map.get(container_id)
    
    # If not in map, it might be an ID or a raw name.
    # Try to resolve ID to name if possible.
    if not service_name:
        try:
            client = docker.from_env()
            container = client.containers.get(container_id)
            # Strip leading slash
            name = container.name.lstrip('/')
            # Try map again with name, or use name directly
            service_name = service_map.get(name, name)
        except:
            # Fallback to using the input as is
            service_name = container_id
    
    project_root = os.getenv("PROJECT_ROOT", "/app/project")
    
    print(f"DEBUG: Restarting {service_name} from {project_root}")
    
    # Map service names to container names
    container_name_map = {
        "ai-engine": "ai_engine",
        "admin-ui": "admin_ui", 
        "local-ai-server": "local_ai_server"
    }
    container_name = container_name_map.get(service_name, service_name.replace("-", "_"))
    
    try:
        # Step 1: Stop the container using docker directly (more reliable)
        stop_result = subprocess.run(
            ["/usr/bin/docker", "stop", container_name],
            capture_output=True,
            text=True,
            timeout=60
        )
        print(f"DEBUG: docker stop returncode={stop_result.returncode}")
        
        # Step 2: Force remove the container using docker directly
        rm_result = subprocess.run(
            ["/usr/bin/docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        print(f"DEBUG: docker rm returncode={rm_result.returncode}")
        
        # Step 3: Bring the service back up using docker-compose
        # -p: Use correct project name to match existing images
        up_result = subprocess.run(
            ["/usr/local/bin/docker-compose", "-p", "asterisk-ai-voice-agent",
             "up", "-d", "--no-build", service_name],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        print(f"DEBUG: up returncode={up_result.returncode}")
        print(f"DEBUG: up stdout={up_result.stdout}")
        print(f"DEBUG: up stderr={up_result.stderr}")
        
        if up_result.returncode == 0:
            return {"status": "success", "output": up_result.stdout or "Container restarted"}
        else:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to restart: {up_result.stderr or up_result.stdout}"
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Timeout waiting for container restart")
    except FileNotFoundError:
        # Fallback to Docker API if docker-compose not available
        try:
            client = docker.from_env()
            container = client.containers.get(container_id)
            container.restart()
            return {"status": "success", "method": "docker-api"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
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


@router.get("/directories")
async def get_directory_health():
    """
    Check health of directories required for audio playback.
    Returns status of media directory, symlink, and permissions.
    """
    project_root = os.getenv("PROJECT_ROOT", "/app/project")
    ast_media_dir = os.getenv("AST_MEDIA_DIR", "")
    
    # Expected paths
    host_media_dir = os.path.join(project_root, "asterisk_media", "ai-generated")
    asterisk_sounds_link = "/var/lib/asterisk/sounds/ai-generated"
    container_media_dir = "/mnt/asterisk_media/ai-generated"
    
    checks = {
        "media_dir_configured": {
            "status": "unknown",
            "configured_path": ast_media_dir,
            "expected_path": container_media_dir,
            "message": ""
        },
        "host_directory": {
            "status": "unknown",
            "path": host_media_dir,
            "exists": False,
            "writable": False,
            "message": ""
        },
        "asterisk_symlink": {
            "status": "unknown",
            "path": asterisk_sounds_link,
            "exists": False,
            "target": None,
            "valid": False,
            "message": ""
        }
    }
    
    # Check 1: AST_MEDIA_DIR configured
    if ast_media_dir:
        if "ai-generated" in ast_media_dir:
            checks["media_dir_configured"]["status"] = "ok"
            checks["media_dir_configured"]["message"] = "Correctly configured"
        else:
            checks["media_dir_configured"]["status"] = "warning"
            checks["media_dir_configured"]["message"] = "Missing 'ai-generated' subdirectory in path"
    else:
        checks["media_dir_configured"]["status"] = "error"
        checks["media_dir_configured"]["message"] = "AST_MEDIA_DIR not set in environment"
    
    # Check 2: Host directory exists and is writable
    try:
        if os.path.exists(host_media_dir):
            checks["host_directory"]["exists"] = True
            # Test write permission
            test_file = os.path.join(host_media_dir, ".write_test")
            try:
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
                checks["host_directory"]["writable"] = True
                checks["host_directory"]["status"] = "ok"
                checks["host_directory"]["message"] = "Directory exists and is writable"
            except PermissionError:
                checks["host_directory"]["status"] = "error"
                checks["host_directory"]["message"] = "Directory exists but not writable"
        else:
            checks["host_directory"]["status"] = "error"
            checks["host_directory"]["message"] = "Directory does not exist"
    except Exception as e:
        checks["host_directory"]["status"] = "error"
        checks["host_directory"]["message"] = f"Error checking directory: {str(e)}"
    
    # Check 3: Asterisk symlink
    # Note: When running in Docker, we can't verify the symlink because
    # /var/lib/asterisk/sounds is on the host and not mounted into the container.
    # If the other checks pass, assume symlink is OK (user can verify with test call).
    try:
        in_docker = os.path.exists("/.dockerenv") or os.getenv("DOCKER_CONTAINER", "")
        
        if os.path.islink(asterisk_sounds_link):
            checks["asterisk_symlink"]["exists"] = True
            target = os.readlink(asterisk_sounds_link)
            checks["asterisk_symlink"]["target"] = target
            
            # Check if target contains the project path or is correct
            if host_media_dir in target or target == host_media_dir:
                checks["asterisk_symlink"]["valid"] = True
                checks["asterisk_symlink"]["status"] = "ok"
                checks["asterisk_symlink"]["message"] = f"Symlink valid → {target}"
            else:
                checks["asterisk_symlink"]["status"] = "warning"
                checks["asterisk_symlink"]["message"] = f"Symlink points to {target}, expected {host_media_dir}"
        elif os.path.exists(asterisk_sounds_link):
            checks["asterisk_symlink"]["exists"] = True
            checks["asterisk_symlink"]["status"] = "warning"
            checks["asterisk_symlink"]["message"] = "Path exists but is not a symlink"
        elif in_docker:
            # Running in Docker - can't verify symlink but if other checks pass, assume OK
            checks["asterisk_symlink"]["status"] = "ok"
            checks["asterisk_symlink"]["message"] = "Cannot verify from Docker (symlink is on host)"
            checks["asterisk_symlink"]["docker_note"] = True
        else:
            checks["asterisk_symlink"]["status"] = "error"
            checks["asterisk_symlink"]["message"] = "Symlink does not exist"
    except Exception as e:
        checks["asterisk_symlink"]["status"] = "error"
        checks["asterisk_symlink"]["message"] = f"Error checking symlink: {str(e)}"
    
    # Calculate overall health
    statuses = [c["status"] for c in checks.values()]
    if all(s == "ok" for s in statuses):
        overall = "healthy"
    elif any(s == "error" for s in statuses):
        overall = "error"
    else:
        overall = "warning"
    
    return {
        "overall": overall,
        "checks": checks
    }


@router.post("/directories/fix")
async def fix_directory_issues():
    """
    Attempt to fix directory permission and symlink issues.
    """
    import subprocess
    
    project_root = os.getenv("PROJECT_ROOT", "/app/project")
    host_media_dir = os.path.join(project_root, "asterisk_media", "ai-generated")
    asterisk_sounds_link = "/var/lib/asterisk/sounds/ai-generated"
    
    fixes_applied = []
    errors = []
    
    # Fix 1: Create directory if missing
    try:
        os.makedirs(host_media_dir, mode=0o777, exist_ok=True)
        fixes_applied.append(f"Created directory: {host_media_dir}")
    except Exception as e:
        errors.append(f"Failed to create directory: {str(e)}")
    
    # Fix 2: Set permissions
    try:
        os.chmod(host_media_dir, 0o777)
        parent_dir = os.path.dirname(host_media_dir)
        os.chmod(parent_dir, 0o777)
        fixes_applied.append(f"Set permissions 777 on {host_media_dir}")
    except Exception as e:
        errors.append(f"Failed to set permissions: {str(e)}")
    
    # Fix 3: Create/fix symlink
    try:
        # Remove existing symlink or file
        if os.path.islink(asterisk_sounds_link):
            os.unlink(asterisk_sounds_link)
            fixes_applied.append(f"Removed old symlink: {asterisk_sounds_link}")
        elif os.path.exists(asterisk_sounds_link):
            errors.append(f"Cannot fix: {asterisk_sounds_link} exists and is not a symlink")
        
        # Create new symlink
        if not os.path.exists(asterisk_sounds_link):
            os.symlink(host_media_dir, asterisk_sounds_link)
            fixes_applied.append(f"Created symlink: {asterisk_sounds_link} → {host_media_dir}")
    except PermissionError:
        # Try with sudo
        try:
            result = subprocess.run(
                ["sudo", "ln", "-sf", host_media_dir, asterisk_sounds_link],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                fixes_applied.append(f"Created symlink with sudo: {asterisk_sounds_link} → {host_media_dir}")
            else:
                errors.append(f"Failed to create symlink with sudo: {result.stderr}")
        except Exception as e:
            errors.append(f"Failed to create symlink: {str(e)}")
    except Exception as e:
        errors.append(f"Failed to manage symlink: {str(e)}")
    
    # Fix 4: Update .env if needed
    env_file = os.path.join(project_root, ".env")
    try:
        env_content = ""
        if os.path.exists(env_file):
            with open(env_file, "r") as f:
                env_content = f.read()
        
        if "AST_MEDIA_DIR=" not in env_content:
            with open(env_file, "a") as f:
                f.write(f"\nAST_MEDIA_DIR=/mnt/asterisk_media/ai-generated\n")
            fixes_applied.append("Added AST_MEDIA_DIR to .env (requires container restart)")
        elif "AST_MEDIA_DIR=/mnt/asterisk_media/ai-generated" not in env_content:
            # Update existing value
            import re
            new_content = re.sub(
                r"AST_MEDIA_DIR=.*", 
                "AST_MEDIA_DIR=/mnt/asterisk_media/ai-generated", 
                env_content
            )
            with open(env_file, "w") as f:
                f.write(new_content)
            fixes_applied.append("Updated AST_MEDIA_DIR in .env (requires container restart)")
    except Exception as e:
        errors.append(f"Failed to update .env: {str(e)}")
    
    return {
        "success": len(errors) == 0,
        "fixes_applied": fixes_applied,
        "errors": errors,
        "restart_required": any("restart" in f.lower() for f in fixes_applied)
    }
