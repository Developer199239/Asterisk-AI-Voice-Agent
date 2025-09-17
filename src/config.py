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

class RTPConfig(BaseModel):
    host: str = Field(default="127.0.0.1")
    port_range: list = Field(default=[10000, 10100])
    sample_rate: int = Field(default=8000)
    samples_per_packet: int = Field(default=160)

class DeepgramProviderConfig(BaseModel):
    api_key: str
    model: str
    tts_model: str

class OpenAIProviderConfig(BaseModel):
    api_key: str
    model: str
    voice: str

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

class StreamingTimeouts(BaseModel):
    provider_ms: int = 15000
    handshake_ms: int = 15000

class StreamingBargeIn(BaseModel):
    enabled: bool = False
    vad_threshold_db: int = -30
    min_speech_ms: int = 200

class StreamingConfig(BaseModel):
    sample_rate_hz: int = 16000
    chunk_duration_ms: int = 20
    jitter_buffer_ms: int = 120
    keepalive_ms: int = 10000
    timeouts: StreamingTimeouts = Field(default_factory=StreamingTimeouts)
    barge_in: StreamingBargeIn = Field(default_factory=StreamingBargeIn)

class AppConfig(BaseModel):
    default_provider: str
    providers: Dict[str, Any]
    asterisk: AsteriskConfig
    llm: LLMConfig
    audio_transport: str = Field(default="external_media")  # 'external_media' | 'audiosocket' | 'legacy'
    downstream_mode: str = Field(default="file")  # 'file' | 'stream'
    streaming: Optional[StreamingConfig] = Field(default_factory=StreamingConfig)
    rtp: Optional[RTPConfig] = Field(default_factory=RTPConfig)

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
        config_data.setdefault('audio_transport', os.getenv('AUDIO_TRANSPORT', 'audiosocket'))
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
