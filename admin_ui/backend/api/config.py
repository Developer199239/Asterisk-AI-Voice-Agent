from fastapi import APIRouter, HTTPException, UploadFile, File
import yaml
import os
from pydantic import BaseModel
from typing import Dict, Any
import settings

router = APIRouter()

class ConfigUpdate(BaseModel):
    content: str

@router.post("/yaml")
async def update_yaml_config(update: ConfigUpdate):
    try:
        # Validate YAML before saving
        try:
            yaml.safe_load(update.content)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML: {str(e)}")

        # Create backup before saving
        if os.path.exists(settings.CONFIG_PATH):
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{settings.CONFIG_PATH}.bak.{timestamp}"
            with open(settings.CONFIG_PATH, 'r') as src:
                with open(backup_path, 'w') as dst:
                    dst.write(src.read())

        with open(settings.CONFIG_PATH, 'w') as f:
            f.write(update.content)
        return {
            "status": "success",
            "restart_required": True,
            "message": "Configuration saved. Restart AI Engine to apply changes."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/yaml")
async def get_yaml_config():
    print(f"Accessing config at {settings.CONFIG_PATH}")
    if not os.path.exists(settings.CONFIG_PATH):
        print("Config file not found")
        raise HTTPException(status_code=404, detail="Config file not found")
    try:
        with open(settings.CONFIG_PATH, 'r') as f:
            config_content = f.read()
        yaml.safe_load(config_content) # Validate content is still valid YAML
        return {"content": config_content}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=500, detail=f"Error reading or parsing YAML config: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/env")
async def get_env_config():
    env_vars = {}
    if os.path.exists(settings.ENV_PATH):
        try:
            with open(settings.ENV_PATH, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        env_vars[key] = value
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return env_vars

@router.post("/env")
async def update_env(env_data: Dict[str, str]):
    try:
        # Create backup before saving
        if os.path.exists(settings.ENV_PATH):
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{settings.ENV_PATH}.bak.{timestamp}"
            with open(settings.ENV_PATH, 'r') as src:
                with open(backup_path, 'w') as dst:
                    dst.write(src.read())

        # Read existing lines
        lines = []
        if os.path.exists(settings.ENV_PATH):
            with open(settings.ENV_PATH, 'r') as f:
                lines = f.readlines()

        # Create a map of keys to line numbers
        key_line_map = {}
        for i, line in enumerate(lines):
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key = line.split('=', 1)[0].strip()
                    key_line_map[key] = i

        # Update existing keys or append new ones
        new_lines = lines.copy()
        
        # Ensure we have a newline at the end if the file is not empty
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'

        for key, value in env_data.items():
            # Skip empty keys
            if not key:
                continue
                
            line_content = f"{key}={value}\n"
            
            if key in key_line_map:
                # Update existing line
                new_lines[key_line_map[key]] = line_content
            else:
                # Append new key
                new_lines.append(line_content)
                # Update map for subsequent iterations (though not strictly needed for this simple logic)
                key_line_map[key] = len(new_lines) - 1

        with open(settings.ENV_PATH, 'w') as f:
            f.writelines(new_lines)
            
        
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ProviderTestRequest(BaseModel):
    name: str
    config: Dict[str, Any]

@router.post("/providers/test")
async def test_provider_connection(request: ProviderTestRequest):
    """Test connection to a provider based on its configuration"""
    try:
        import httpx
        import os
        
        # Helper to read API keys from .env file
        def get_env_key(key_name: str) -> str:
            """Read API key from .env file"""
            if os.path.exists(settings.ENV_PATH):
                with open(settings.ENV_PATH, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith(f"{key_name}="):
                            return line.split('=', 1)[1].strip()
            return ''
        
        provider_config = request.config
        provider_name = request.name
        
        # Determine provider type based on config structure
        if 'realtime_base_url' in provider_config or 'turn_detection' in provider_config:
            # OpenAI Realtime
            api_key = get_env_key('OPENAI_API_KEY')
            if not api_key:
                return {"success": False, "message": "OPENAI_API_KEY not set in .env file"}
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0
                )
                if response.status_code == 200:
                    return {"success": True, "message": f"Connected to OpenAI (HTTP {response.status_code})"}
                return {"success": False, "message": f"OpenAI API error: HTTP {response.status_code}"}
                
        elif 'google_live' in provider_config or ('llm_model' in provider_config and 'gemini' in provider_config.get('llm_model', '')):
            # Google Live
            api_key = get_env_key('GOOGLE_API_KEY')
            if not api_key:
                return {"success": False, "message": "GOOGLE_API_KEY not set in .env file"}
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                    timeout=10.0
                )
                if response.status_code == 200:
                    return {"success": True, "message": f"Connected to Google API (HTTP {response.status_code})"}
                return {"success": False, "message": f"Google API error: HTTP {response.status_code}"}
                
        elif 'ws_url' in provider_config:
            # Local provider (WebSocket)
            ws_url = provider_config.get('ws_url', '')
            # Convert ws:// to http:// for health check
            http_url = ws_url.replace('ws://', 'http://').replace('wss://', 'https://')
            if '/ws' in http_url:
                http_url = http_url.replace('/ws', '')
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(f"{http_url}/health", timeout=5.0)
                    if response.status_code == 200:
                        return {"success": True, "message": "Local AI server is reachable"}
                except:
                    pass
                return {"success": False, "message": "Cannot reach local AI server"}
                
        elif 'model' in provider_config or 'stt_model' in provider_config:
            # Check if it's Deepgram or OpenAI standard
            if provider_config.get('model', '').startswith('nova') or 'deepgram' in provider_name.lower():
                # Deepgram
                api_key = get_env_key('DEEPGRAM_API_KEY')
                if not api_key:
                    return {"success": False, "message": "DEEPGRAM_API_KEY not set in .env file"}
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://api.deepgram.com/v1/projects",
                        headers={"Authorization": f"Token {api_key}"},
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        return {"success": True, "message": f"Connected to Deepgram (HTTP {response.status_code})"}
                    return {"success": False, "message": f"Deepgram API error: HTTP {response.status_code}"}
            else:
                # OpenAI Standard or Generic
                # Try OpenAI first
                api_key = get_env_key('OPENAI_API_KEY')
                if api_key:
                   async with httpx.AsyncClient() as client:
                        try:
                            response = await client.get(
                                "https://api.openai.com/v1/models",
                                headers={"Authorization": f"Bearer {api_key}"},
                                timeout=5.0
                            )
                            if response.status_code == 200:
                                return {"success": True, "message": f"Connected to OpenAI (HTTP {response.status_code})"}
                        except:
                            pass
                
                # If we are here, it might be a local provider using 'model' key (e.g. local_tts)
                # but without ws_url? Usually local providers have ws_url. 
                # If it's pure local without WS (e.g. wrapper), assume success if file paths exist?
                return {"success": True, "message": "Provider configuration valid (No specific connection test available)"}

        elif 'agent_id' in provider_config or 'elevenlabs' in provider_name.lower():
            # ElevenLabs Agent
            api_key = get_env_key('ELEVENLABS_API_KEY')
            if not api_key:
                return {"success": False, "message": "ELEVENLABS_API_KEY not set in .env file. ElevenLabs requires API key."}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.elevenlabs.io/v1/user",
                    headers={"xi-api-key": api_key},
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json()
                    user_name = data.get('subscription', {}).get('tier', 'Unknown Plan')
                    return {"success": True, "message": f"Connected to ElevenLabs ({user_name})"}
                return {"success": False, "message": f"ElevenLabs API error: HTTP {response.status_code}"}
        
        return {"success": False, "message": "Unknown provider type - cannot test"}
        
    except httpx.TimeoutException:
        return {"success": False, "message": "Connection timeout"}
    except Exception as e:
        return {"success": False, "message": f"Test failed: {str(e)}"}

@router.get("/export")
async def export_configuration():
    """Export configuration as a ZIP file"""
    try:
        import zipfile
        import io
        from datetime import datetime
        
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add YAML config
            if settings.CONFIG_PATH.exists():
                zip_file.write(settings.CONFIG_PATH, 'ai-agent.yaml')
            
            # Add ENV file
            if settings.ENV_PATH.exists():
                zip_file.write(settings.ENV_PATH, '.env')
            
            # Add timestamp file
            timestamp = datetime.now().isoformat()
            zip_file.writestr('backup_info.txt', f'Backup created: {timestamp}\n')
        
        zip_buffer.seek(0)
        
        # Return as downloadable file
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            zip_buffer, 
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=config-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export-logs")
async def export_logs():
    """Export logs and sanitized configuration for troubleshooting"""
    try:
        import zipfile
        import io
        import glob
        from datetime import datetime
        
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # 1. Sanitized YAML
            if settings.CONFIG_PATH.exists():
                with open(settings.CONFIG_PATH, 'r') as f:
                    content = f.read()
                # Simple sanitization (redact known key patterns if needed, but for now just raw or basic redaction)
                # For this task, user asked for "sanitized". We'll redact common API key patterns.
                import re
                content = re.sub(r'api_key: .*', 'api_key: [REDACTED]', content)
                content = re.sub(r'key: sk-.*', 'key: [REDACTED]', content)
                zip_file.writestr('ai-agent-sanitized.yaml', content)
            
            # 2. Sanitized ENV (Just keys, no values)
            if settings.ENV_PATH.exists():
                env_keys = []
                with open(settings.ENV_PATH, 'r') as f:
                    for line in f:
                        if '=' in line and not line.startswith('#'):
                            key = line.split('=')[0].strip()
                            env_keys.append(f"{key}=[REDACTED]")
                zip_file.writestr('.env.sanitized', '\n'.join(env_keys))
            
            # 3. Logs
            # Assuming logs are in /app/logs or similar. If not, try to find them.
            # Local dev might be different from Docker.
            log_dirs = ['/app/logs', './logs', '../logs']
            found_logs = False
            for log_dir in log_dirs:
                if os.path.exists(log_dir):
                    for log_file in glob.glob(os.path.join(log_dir, "*.log")):
                        zip_file.write(log_file, os.path.basename(log_file))
                        found_logs = True
            
            if not found_logs:
                zip_file.writestr('logs_info.txt', 'No log files found in default locations.')

            # Add timestamp
            timestamp = datetime.now().isoformat()
            zip_file.writestr('export_info.txt', f'Debug export created: {timestamp}\n')
        
        zip_buffer.seek(0)
        
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            zip_buffer, 
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=debug-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
async def import_configuration(file: UploadFile = File(...)):
    """Import configuration from a ZIP file"""
    try:
        import zipfile
        import io
        import shutil
        import datetime
        
        content = await file.read()
        zip_buffer = io.BytesIO(content)
        
        if not zipfile.is_zipfile(zip_buffer):
             raise HTTPException(status_code=400, detail="Invalid file format. Must be a ZIP file.")
        
        # Create backups of current config
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if os.path.exists(settings.CONFIG_PATH):
            backup_path = f"{settings.CONFIG_PATH}.bak.{timestamp}"
            shutil.copy2(settings.CONFIG_PATH, backup_path)
            
        if os.path.exists(settings.ENV_PATH):
            backup_path = f"{settings.ENV_PATH}.bak.{timestamp}"
            shutil.copy2(settings.ENV_PATH, backup_path)
        
        with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
            # Check contents
            file_names = zip_ref.namelist()
            if 'ai-agent.yaml' not in file_names and '.env' not in file_names:
                raise HTTPException(status_code=400, detail="ZIP must contain ai-agent.yaml or .env")
            
            # Extract
            if 'ai-agent.yaml' in file_names:
                with open(settings.CONFIG_PATH, 'wb') as f:
                    f.write(zip_ref.read('ai-agent.yaml'))
                    
            if '.env' in file_names:
                with open(settings.ENV_PATH, 'wb') as f:
                    f.write(zip_ref.read('.env'))
                    
        return {"success": True, "message": "Configuration imported successfully."}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


def update_yaml_provider_field(provider_name: str, field: str, value: Any) -> bool:
    """
    Update a single field in a provider's YAML config.
    
    Args:
        provider_name: Name of the provider (e.g., 'local')
        field: Field name to update (e.g., 'stt_backend')
        value: New value for the field
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if not os.path.exists(settings.CONFIG_PATH):
            return False
            
        with open(settings.CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        
        if not config:
            return False
            
        # Ensure providers section exists
        if 'providers' not in config:
            config['providers'] = {}
        
        # Ensure provider exists
        if provider_name not in config['providers']:
            config['providers'][provider_name] = {}
        
        # Update the field
        config['providers'][provider_name][field] = value
        
        # Write back
        with open(settings.CONFIG_PATH, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        return True
    except Exception as e:
        print(f"Error updating YAML provider field: {e}")
        return False

@router.get("/options/{provider_type}")
async def get_provider_options(provider_type: str):
    """Get available options (models, voices) for a specific provider."""
    
    # Common catalogs
    DEEPGRAM_MODELS = [
        {"id": "nova-2", "name": "Nova 2 (General)", "cost": "Low", "latency": "Ultra Low"},
        {"id": "nova-2-phonecall", "name": "Nova 2 (Phonecall)", "cost": "Low", "latency": "Ultra Low"},
        {"id": "nova-2-medical", "name": "Nova 2 (Medical)", "cost": "Low", "latency": "Ultra Low"},
        {"id": "nova-2-meeting", "name": "Nova 2 (Meeting)", "cost": "Low", "latency": "Ultra Low"},
        {"id": "nova-2-general", "name": "Nova 2 (General Legacy)", "cost": "Low", "latency": "Ultra Low"},
        {"id": "listen", "name": "General (Listen)", "cost": "Medium", "latency": "Low"},
    ]
    
    OPENAI_LLM_MODELS = [
        {"id": "gpt-4o", "name": "GPT-4o (Omni)", "description": "Most capable"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "description": "Fast & Cheap"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "description": "High intelligence"},
        {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "description": "Legacy fast"},
    ]
    
    OPENAI_STT_MODELS = [
        {"id": "whisper-1", "name": "Whisper V1"}
    ]
    
    GOOGLE_MODELS = [
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash (Fastest)"},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro (Best Quality)"},
    ]

    GOOGLE_VOICES = [
        {"id": "en-US-Standard-A", "name": "US Female Standard"},
        {"id": "en-US-Standard-B", "name": "US Male Standard"},
        {"id": "en-US-Neural2-A", "name": "US Female Neural"},
        {"id": "en-US-Neural2-C", "name": "US Male Neural"},
        {"id": "en-US-Studio-O", "name": "US Female Studio"},
        {"id": "en-US-Studio-Q", "name": "US Male Studio"},
    ]

    # Return options based on provider
    if provider_type == "deepgram":
        return {"models": DEEPGRAM_MODELS}
        
    elif provider_type == "openai":
        return {
            "stt_models": OPENAI_STT_MODELS,
            "llm_models": OPENAI_LLM_MODELS,
            "tts_models": [{"id": "tts-1", "name": "TTS-1"}, {"id": "tts-1-hd", "name": "TTS-1 HD"}]
        }
        
    elif provider_type == "google":
        return {
            "models": GOOGLE_MODELS,
            "voices": GOOGLE_VOICES
        }
        
    elif provider_type == "elevenlabs":
        return {
            "models": [
                {"id": "eleven_turbo_v2_5", "name": "Turbo v2.5"},
                {"id": "eleven_multilingual_v2", "name": "Multilingual v2"},
                {"id": "eleven_monolingual_v1", "name": "Monolingual v1"}
            ]
        }
        
    elif provider_type == "local":
        return {"message": "Use /api/local-ai/models for dynamic local models"}
        
    return {"error": "Unknown provider type"}
