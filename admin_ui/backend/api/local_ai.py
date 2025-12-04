"""
Local AI Server Model Management API

Endpoints for:
- Enumerating available models (STT, TTS, LLM)
- Switching active model with hot-reload support
- Getting current model status
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import os
import json
import asyncio
import websockets

router = APIRouter()


class ModelInfo(BaseModel):
    """Information about a single model."""
    name: str
    path: str
    type: str  # stt, tts, llm
    backend: Optional[str] = None  # vosk, sherpa, kroko, piper, kokoro
    size_mb: Optional[float] = None
    

class AvailableModels(BaseModel):
    """All available models grouped by type."""
    stt: Dict[str, List[ModelInfo]]  # Grouped by backend
    tts: Dict[str, List[ModelInfo]]  # Grouped by backend
    llm: List[ModelInfo]


class SwitchModelRequest(BaseModel):
    """Request to switch model."""
    model_type: str  # stt, tts, llm
    backend: Optional[str] = None  # For STT/TTS: vosk, sherpa, kroko, piper, kokoro
    model_path: Optional[str] = None  # For models with paths
    voice: Optional[str] = None  # For Kokoro TTS
    language: Optional[str] = None  # For Kroko STT


class SwitchModelResponse(BaseModel):
    """Response from model switch."""
    success: bool
    message: str
    requires_restart: bool = False


def get_dir_size_mb(path: str) -> float:
    """Get directory size in MB."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
    except Exception:
        pass
    return round(total / (1024 * 1024), 2)


def get_file_size_mb(path: str) -> float:
    """Get file size in MB."""
    try:
        return round(os.path.getsize(path) / (1024 * 1024), 2)
    except Exception:
        return 0


@router.get("/models", response_model=AvailableModels)
async def list_available_models():
    """
    List all available models from the models directory.
    
    Scans:
    - models/stt/ for Vosk and Sherpa models
    - models/tts/ for Piper and Kokoro models
    - models/llm/ for GGUF models
    """
    from settings import PROJECT_ROOT
    
    models_dir = os.path.join(PROJECT_ROOT, "models")
    
    stt_models: Dict[str, List[ModelInfo]] = {
        "vosk": [],
        "sherpa": [],
        "kroko": []
    }
    tts_models: Dict[str, List[ModelInfo]] = {
        "piper": [],
        "kokoro": []
    }
    llm_models: List[ModelInfo] = []
    
    # Scan STT models
    stt_dir = os.path.join(models_dir, "stt")
    if os.path.exists(stt_dir):
        for item in os.listdir(stt_dir):
            item_path = os.path.join(stt_dir, item)
            if os.path.isdir(item_path):
                if item.startswith("vosk-model"):
                    stt_models["vosk"].append(ModelInfo(
                        name=item,
                        path=f"/app/models/stt/{item}",
                        type="stt",
                        backend="vosk",
                        size_mb=get_dir_size_mb(item_path)
                    ))
                elif "sherpa" in item.lower():
                    stt_models["sherpa"].append(ModelInfo(
                        name=item,
                        path=f"/app/models/stt/{item}",
                        type="stt",
                        backend="sherpa",
                        size_mb=get_dir_size_mb(item_path)
                    ))
    
    # Kroko is cloud-based, add placeholder
    stt_models["kroko"].append(ModelInfo(
        name="Kroko Cloud API",
        path="wss://app.kroko.ai/api/v1/transcripts/streaming",
        type="stt",
        backend="kroko",
        size_mb=0
    ))
    
    # Scan TTS models
    tts_dir = os.path.join(models_dir, "tts")
    if os.path.exists(tts_dir):
        for item in os.listdir(tts_dir):
            item_path = os.path.join(tts_dir, item)
            if item.endswith(".onnx"):
                tts_models["piper"].append(ModelInfo(
                    name=item.replace(".onnx", ""),
                    path=f"/app/models/tts/{item}",
                    type="tts",
                    backend="piper",
                    size_mb=get_file_size_mb(item_path)
                ))
            elif item == "kokoro" and os.path.isdir(item_path):
                # Get available Kokoro voices
                voices_dir = os.path.join(item_path, "voices")
                if os.path.exists(voices_dir):
                    for voice in os.listdir(voices_dir):
                        if voice.endswith(".pt"):
                            voice_name = voice.replace(".pt", "")
                            tts_models["kokoro"].append(ModelInfo(
                                name=f"Kokoro - {voice_name}",
                                path=f"/app/models/tts/kokoro",
                                type="tts",
                                backend="kokoro",
                                size_mb=get_file_size_mb(os.path.join(voices_dir, voice))
                            ))
    
    # Scan LLM models
    llm_dir = os.path.join(models_dir, "llm")
    if os.path.exists(llm_dir):
        for item in os.listdir(llm_dir):
            if item.endswith(".gguf"):
                item_path = os.path.join(llm_dir, item)
                llm_models.append(ModelInfo(
                    name=item.replace(".gguf", ""),
                    path=f"/app/models/llm/{item}",
                    type="llm",
                    size_mb=get_file_size_mb(item_path)
                ))
    
    return AvailableModels(
        stt=stt_models,
        tts=tts_models,
        llm=llm_models
    )


@router.get("/status")
async def get_local_ai_status():
    """
    Get current status from local-ai-server including active backends and models.
    """
    from settings import get_setting
    
    ws_url = get_setting("HEALTH_CHECK_LOCAL_AI_URL", "ws://local_ai_server:8765")
    
    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            await ws.send(json.dumps({"type": "status"}))
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(response)
            return {
                "connected": True,
                "status": data.get("status", "unknown"),
                "stt_backend": data.get("stt_backend"),
                "tts_backend": data.get("tts_backend"),
                "models": data.get("models", {})
            }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e)
        }


@router.post("/switch", response_model=SwitchModelResponse)
async def switch_model(request: SwitchModelRequest):
    """
    Switch the active model on local-ai-server with rollback support.
    
    For STT/TTS backend changes, updates environment variables AND YAML config,
    then triggers a container restart to reload the model. If the new model
    fails to load, automatically rolls back to the previous configuration.
    """
    from settings import PROJECT_ROOT, get_setting
    from api.config import update_yaml_provider_field
    
    print(f"DEBUG switch_model: model_type={request.model_type}, backend={request.backend}, model_path={request.model_path}")
    
    env_file = os.path.join(PROJECT_ROOT, ".env")
    print(f"DEBUG switch_model: env_file={env_file}")
    env_updates = {}
    yaml_updates = {}  # Track YAML updates for sync
    requires_restart = False
    
    # 1. Save current config for potential rollback
    previous_env = _read_env_values(env_file, [
        "LOCAL_STT_BACKEND", "LOCAL_STT_MODEL_PATH", "SHERPA_MODEL_PATH",
        "KROKO_LANGUAGE", "LOCAL_TTS_BACKEND", "LOCAL_TTS_MODEL_PATH",
        "KOKORO_VOICE", "KOKORO_MODEL_PATH", "LOCAL_LLM_MODEL_PATH"
    ])
    
    if request.model_type == "stt":
        if request.backend:
            env_updates["LOCAL_STT_BACKEND"] = request.backend
            yaml_updates["stt_backend"] = request.backend
            requires_restart = True
            
            if request.backend == "vosk" and request.model_path:
                env_updates["LOCAL_STT_MODEL_PATH"] = request.model_path
                yaml_updates["stt_model"] = request.model_path
            elif request.backend == "kroko":
                if request.language:
                    env_updates["KROKO_LANGUAGE"] = request.language
                    yaml_updates["kroko_language"] = request.language
            elif request.backend == "sherpa" and request.model_path:
                env_updates["SHERPA_MODEL_PATH"] = request.model_path
                yaml_updates["sherpa_model_path"] = request.model_path
                
    elif request.model_type == "tts":
        if request.backend:
            env_updates["LOCAL_TTS_BACKEND"] = request.backend
            yaml_updates["tts_backend"] = request.backend
            requires_restart = True
            
            if request.backend == "piper" and request.model_path:
                env_updates["LOCAL_TTS_MODEL_PATH"] = request.model_path
                yaml_updates["tts_voice"] = request.model_path
            elif request.backend == "kokoro":
                if request.voice:
                    env_updates["KOKORO_VOICE"] = request.voice
                    yaml_updates["kokoro_voice"] = request.voice
                if request.model_path:
                    env_updates["KOKORO_MODEL_PATH"] = request.model_path
                    yaml_updates["kokoro_model_path"] = request.model_path
                    
    elif request.model_type == "llm":
        if request.model_path:
            env_updates["LOCAL_LLM_MODEL_PATH"] = request.model_path
            # Try hot-reload for LLM if supported
            ws_url = get_setting("HEALTH_CHECK_LOCAL_AI_URL", "ws://local_ai_server:8765")
            try:
                async with websockets.connect(ws_url, open_timeout=5) as ws:
                    await ws.send(json.dumps({
                        "type": "reload_llm",
                        "model_path": request.model_path
                    }))
                    response = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(response)
                    if data.get("status") == "ok":
                        # Update env file for persistence but no restart needed
                        _update_env_file(env_file, env_updates)
                        return SwitchModelResponse(
                            success=True,
                            message=f"LLM model switched to {request.model_path} via hot-reload",
                            requires_restart=False
                        )
            except Exception as e:
                # Fall back to restart
                requires_restart = True
    
    # 2. Update .env file AND YAML config
    print(f"DEBUG switch_model: env_updates={env_updates}, requires_restart={requires_restart}")
    if env_updates:
        _update_env_file(env_file, env_updates)
        print(f"DEBUG switch_model: .env file updated")
    
    # Sync to YAML config for consistency
    if yaml_updates:
        for field, value in yaml_updates.items():
            update_yaml_provider_field("local", field, value)
        print(f"DEBUG switch_model: YAML config updated")
    
    # 3. Recreate container if needed (restart doesn't reload .env)
    if requires_restart:
        try:
            import subprocess
            import time
            
            # Use docker compose to recreate with new .env values
            # This is necessary because container.restart() doesn't reload env vars
            result = subprocess.run(
                ["docker", "compose", "up", "-d", "--force-recreate", "local_ai_server"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                raise Exception(f"docker compose failed: {result.stderr}")
            
            # 4. Wait for container to be healthy and verify model loaded
            time.sleep(8)  # Give container time to start and load models
            
            # Check health
            health_ok = await _verify_model_loaded(request.model_type, get_setting)
            
            if not health_ok:
                # 5. Rollback on failure
                _update_env_file(env_file, previous_env)
                subprocess.run(
                    ["docker", "compose", "up", "-d", "--force-recreate", "local_ai_server"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    timeout=60
                )
                return SwitchModelResponse(
                    success=False,
                    message=f"Model failed to load. Rolled back to previous configuration.",
                    requires_restart=True
                )
            
            return SwitchModelResponse(
                success=True,
                message=f"Model switched successfully.",
                requires_restart=True
            )
        except Exception as e:
            # Attempt rollback on any error
            try:
                _update_env_file(env_file, previous_env)
            except Exception:
                pass
            return SwitchModelResponse(
                success=False,
                message=f"Failed to recreate container: {str(e)}. Attempted rollback.",
                requires_restart=True
            )
    
    return SwitchModelResponse(
        success=True,
        message="Model configuration updated",
        requires_restart=False
    )


async def _verify_model_loaded(model_type: str, get_setting) -> bool:
    """Verify that the specified model type is loaded after restart."""
    ws_url = get_setting("HEALTH_CHECK_LOCAL_AI_URL", "ws://local_ai_server:8765")
    try:
        async with websockets.connect(ws_url, open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "status"}))
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(response)
            
            models = data.get("models", {})
            if model_type == "stt":
                return models.get("stt", {}).get("loaded", False)
            elif model_type == "tts":
                return models.get("tts", {}).get("loaded", False)
            elif model_type == "llm":
                return models.get("llm", {}).get("loaded", False)
            return True
    except Exception:
        return False


def _read_env_values(env_file: str, keys: list) -> Dict[str, str]:
    """Read specific environment variable values from .env file."""
    values = {}
    if not os.path.exists(env_file):
        return values
    
    with open(env_file, 'r') as f:
        for line in f:
            if '=' in line and not line.strip().startswith('#'):
                key = line.split('=')[0].strip()
                if key in keys:
                    value = line.split('=', 1)[1].strip()
                    values[key] = value
    return values


def _update_env_file(env_file: str, updates: Dict[str, str]):
    """Update environment variables in .env file."""
    print(f"DEBUG _update_env_file: env_file={env_file}, updates={updates}")
    lines = []
    updated_keys = set()
    
    # Read existing file
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            lines = f.readlines()
        print(f"DEBUG _update_env_file: read {len(lines)} lines from file")
    else:
        print(f"DEBUG _update_env_file: file does not exist!")
    
    # Update existing lines
    new_lines = []
    for line in lines:
        key = None
        if '=' in line and not line.strip().startswith('#'):
            key = line.split('=')[0].strip()
        
        if key and key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            updated_keys.add(key)
            print(f"DEBUG _update_env_file: updated {key}={updates[key]}")
        else:
            new_lines.append(line)
    
    # Add new keys that weren't in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")
            print(f"DEBUG _update_env_file: added new key {key}={value}")
    
    # Write back
    print(f"DEBUG _update_env_file: writing {len(new_lines)} lines to {env_file}")
    with open(env_file, 'w') as f:
        f.writelines(new_lines)
    print(f"DEBUG _update_env_file: write complete")


# Import docker at module level for switch endpoint
try:
    import docker
except ImportError:
    docker = None
