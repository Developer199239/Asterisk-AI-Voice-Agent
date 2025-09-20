"""
Shared Configuration System for Asterisk AI Voice Agent v2.0

This module provides centralized configuration management for all microservices
using Pydantic v2 for validation and type safety.
"""

import os
import yaml
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

# Determine the absolute path to the project root from this file's location
# This makes the config loading independent of the current working directory.
_PROJ_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AsteriskConfig(BaseModel):
    host: str
    port: int = Field(default=8088)
    username: str
    password: str
    app_name: str = Field(default="ai-voice-agent")

class ExternalMediaConfig(BaseModel):
    rtp_host: str = Field(default="0.0.0.0")
    rtp_port: int = Field(default=18080)
    codec: str = Field(default="ulaw")  # ulaw or slin16
    direction: str = Field(default="both")  # both, sendonly, recvonly
    jitter_buffer_ms: int = Field(default=20)


class LocalProviderConfig(BaseModel):
    stt_model: str
    llm_model: str
    tts_voice: str
    temperature: float = Field(default=0.8)
    max_tokens: int = Field(default=150)
    
class LLMConfig(BaseModel):
    initial_greeting: str = "Hello, I am an AI Assistant for Jugaar LLC. How can I help you today."
    prompt: str = "You are a helpful AI assistant."
    model: str = "gpt-4o"
    api_key: Optional[str] = None


class VADConfig(BaseModel):
    # WebRTC VAD settings
    webrtc_aggressiveness: int = 0
    webrtc_start_frames: int = 3
    webrtc_end_silence_frames: int = 50
    
    # Utterance settings - optimized for 4+ second duration
    min_utterance_duration_ms: int = 4000
    max_utterance_duration_ms: int = 10000
    utterance_padding_ms: int = 200
    
    # Fallback settings
    fallback_enabled: bool = True
    fallback_interval_ms: int = 4000
    fallback_buffer_size: int = 128000


class AppConfig(BaseModel):
    default_provider: str
    providers: Dict[str, Any]
    asterisk: AsteriskConfig
    llm: LLMConfig
    audio_transport: str = Field(default="externalmedia")  # 'externalmedia' | 'legacy'
    downstream_mode: str = Field(default="file")  # 'file' | 'stream'
    external_media: Optional[ExternalMediaConfig] = Field(default_factory=ExternalMediaConfig)
    vad: Optional[VADConfig] = Field(default_factory=VADConfig)

def load_config(path: str = "config/ai-agent.yaml") -> AppConfig:
    # If the provided path is not absolute, resolve it relative to the project root.
    if not os.path.isabs(path):
        path = os.path.join(_PROJ_DIR, path)

    try:
        with open(path, 'r') as f:
            config_str = f.read()

        # Substitute environment variables
        config_str_expanded = os.path.expandvars(config_str)
        
        config_data = yaml.safe_load(config_str_expanded)

        # Manually construct and inject the Asterisk and LLM configs from environment variables.
        # This keeps secrets out of the YAML file and aligns with the Pydantic model.
        config_data['asterisk'] = {
            "host": os.getenv("ASTERISK_HOST"),
            "username": os.getenv("ASTERISK_ARI_USERNAME"),
            "password": os.getenv("ASTERISK_ARI_PASSWORD"),
            "app_name": "asterisk-ai-voice-agent"
        }
        
        config_data['llm'] = {
            "initial_greeting": os.getenv("GREETING", "Hello, how can I help you?"),
            "prompt": os.getenv("AI_ROLE", "You are a helpful assistant."),
            "model": "gpt-4o",
            "api_key": os.getenv("OPENAI_API_KEY")
        }

        # Defaults for new flags if not present in YAML
        config_data.setdefault('audio_transport', os.getenv('AUDIO_TRANSPORT', 'externalmedia'))
        config_data.setdefault('downstream_mode', os.getenv('DOWNSTREAM_MODE', 'file'))
        if 'streaming' not in config_data:
            config_data['streaming'] = {}

        return AppConfig(**config_data)
    except FileNotFoundError:
        # Re-raise with a more informative error message
        raise FileNotFoundError(f"Configuration file not found at the resolved path: {path}")
    except yaml.YAMLError as e:
        # Re-raise with a more informative error message
        raise yaml.YAMLError(f"Error parsing YAML file at {path}: {e}")
