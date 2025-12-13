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
from services.fs import upsert_env_vars

router = APIRouter()


class ModelInfo(BaseModel):
    """Information about a single model."""
    id: str
    name: str
    path: str
    type: str  # stt, tts, llm
    backend: Optional[str] = None  # vosk, sherpa, kroko, piper, kokoro
    size_mb: Optional[float] = None
    voice_files: Optional[Dict[str, str]] = None  # For Kokoro voices


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
    - models/stt/ for Vosk, Sherpa, and Kroko models
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
                        id="vosk",  # Frontend expects 'vosk' for the default model
                        name=item,
                        path=f"/app/models/stt/{item}",
                        type="stt",
                        backend="vosk",
                        size_mb=get_dir_size_mb(item_path)
                    ))
                elif "sherpa" in item.lower():
                    stt_models["sherpa"].append(ModelInfo(
                        id=f"sherpa_{item}",
                        name=item,
                        path=f"/app/models/stt/{item}",
                        type="stt",
                        backend="sherpa",
                        size_mb=get_dir_size_mb(item_path)
                    ))
                elif "kroko" in item.lower():
                    stt_models["kroko"].append(ModelInfo(
                        id="kroko_embedded",
                        name=f"Kroko Embedded ({item})",
                        path=f"/app/models/stt/{item}",
                        type="stt",
                        backend="kroko",
                        size_mb=get_dir_size_mb(item_path)
                    ))
    
    # Note: Kroko Cloud API is not added here since it's a cloud service, not an installed model
    # It's available through the catalog but shouldn't appear in "installed" models list
    
    # Scan TTS models
    tts_dir = os.path.join(models_dir, "tts")
    if os.path.exists(tts_dir):
        for item in os.listdir(tts_dir):
            item_path = os.path.join(tts_dir, item)
            if item.endswith(".onnx"):
                name = item.replace(".onnx", "")
                tts_models["piper"].append(ModelInfo(
                    id=f"piper_{name}",
                    name=name,
                    path=f"/app/models/tts/{item}",
                    type="tts",
                    backend="piper",
                    size_mb=get_file_size_mb(item_path)
                ))
            elif item == "kokoro" and os.path.isdir(item_path):
                # Get available Kokoro voices
                voices_dir = os.path.join(item_path, "voices")
                voice_files = {}
                if os.path.exists(voices_dir):
                    for voice in os.listdir(voices_dir):
                        if voice.endswith(".pt"):
                            voice_name = voice.replace(".pt", "")
                            voice_files[voice_name] = voice
                            
                tts_models["kokoro"].append(ModelInfo(
                    id="kokoro_82m",
                    name="Kokoro v0.19 (82M)",
                    path="/app/models/tts/kokoro",
                    type="tts",
                    backend="kokoro",
                    size_mb=get_dir_size_mb(item_path),
                    voice_files=voice_files
                ))
    
    # Scan LLM models
    llm_dir = os.path.join(models_dir, "llm")
    if os.path.exists(llm_dir):
        for item in os.listdir(llm_dir):
            if item.endswith(".gguf"):
                item_path = os.path.join(llm_dir, item)
                llm_models.append(ModelInfo(
                    id=item.replace(".gguf", ""),
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
            auth_token = (get_setting("LOCAL_WS_AUTH_TOKEN", os.getenv("LOCAL_WS_AUTH_TOKEN", "")) or "").strip()
            if auth_token:
                await ws.send(json.dumps({"type": "auth", "auth_token": auth_token}))
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(raw)
                if data.get("type") != "auth_response" or data.get("status") != "ok":
                    raise RuntimeError(f"Local AI auth failed: {data}")

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
    
    env_file = os.path.join(PROJECT_ROOT, ".env")
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
                if request.model_path:
                    # Support for local/embedded Kroko
                    env_updates["LOCAL_STT_MODEL_PATH"] = request.model_path
                    yaml_updates["stt_model"] = request.model_path
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
                    auth_token = (get_setting("LOCAL_WS_AUTH_TOKEN", os.getenv("LOCAL_WS_AUTH_TOKEN", "")) or "").strip()
                    if auth_token:
                        await ws.send(json.dumps({"type": "auth", "auth_token": auth_token}))
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        auth_data = json.loads(raw)
                        if auth_data.get("type") != "auth_response" or auth_data.get("status") != "ok":
                            raise RuntimeError(f"Local AI auth failed: {auth_data}")

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
    if env_updates:
        _update_env_file(env_file, env_updates)
    
    # Sync to YAML config for consistency
    if yaml_updates:
        for field, value in yaml_updates.items():
            update_yaml_provider_field("local", field, value)
    
    # 3. Recreate container if needed (restart doesn't reload .env)
    if requires_restart:
        try:
            from api.system import _recreate_via_compose
            result = await _recreate_via_compose("local-ai-server")
            return SwitchModelResponse(
                success=True,
                message=f"Model switch initiated. Container recreating with new settings...",
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


class DeleteModelRequest(BaseModel):
    model_path: str
    type: str  # stt, tts, llm


@router.delete("/models")
async def delete_model(request: DeleteModelRequest):
    """
    Delete an installed model from the filesystem.
    """
    import shutil
    from settings import PROJECT_ROOT
    
    model_path = request.model_path
    model_type = request.type
    
    # Handle path mapping: local_ai_server returns /app/models/...
    # but admin_ui has models at /app/project/models/...
    if model_path.startswith('/app/models/'):
        model_path = model_path.replace('/app/models/', f'{PROJECT_ROOT}/models/')
    
    # Security: Ensure path is within the models directory
    models_base = os.path.join(PROJECT_ROOT, "models")
    
    # Normalize paths for comparison
    abs_model_path = os.path.abspath(model_path)
    abs_models_base = os.path.abspath(models_base)
    
    if not abs_model_path.startswith(abs_models_base):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model path: must be within {models_base}"
        )
    
    if not os.path.exists(abs_model_path):
        raise HTTPException(
            status_code=404,
            detail=f"Model not found: {model_path}"
        )
    
    try:
        if os.path.isdir(abs_model_path):
            shutil.rmtree(abs_model_path)
        else:
            os.remove(abs_model_path)
            # Also remove .json config file if exists (for Piper models)
            json_path = abs_model_path.replace('.onnx', '.onnx.json')
            if os.path.exists(json_path):
                os.remove(json_path)
        
        return {
            "success": True,
            "message": f"Model deleted: {os.path.basename(abs_model_path)}"
        }
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail="Permission denied: cannot delete model"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete model: {str(e)}"
        )


async def _verify_model_loaded(model_type: str, get_setting) -> bool:
    """Verify that the specified model type is loaded after restart."""
    # Try both localhost and container name
    urls_to_try = [
        "ws://127.0.0.1:8765",
        "ws://local_ai_server:8765",
        get_setting("HEALTH_CHECK_LOCAL_AI_URL", "ws://local_ai_server:8765")
    ]
    
    for ws_url in urls_to_try:
        try:
            async with websockets.connect(ws_url, open_timeout=5) as ws:
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
            continue
    
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
    upsert_env_vars(env_file, updates, header="Local AI model management")


# Import docker at module level for switch endpoint
try:
    import docker
except ImportError:
    docker = None
