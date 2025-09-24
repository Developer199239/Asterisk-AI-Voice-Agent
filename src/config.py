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


class AudioSocketConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8090)
    format: str = Field(default="ulaw")  # 'ulaw' or 'slin16'


class LocalProviderConfig(BaseModel):
    stt_model: str
    llm_model: str
    tts_voice: str
    temperature: float = Field(default=0.8)
    max_tokens: int = Field(default=150)


class DeepgramProviderConfig(BaseModel):
    api_key: Optional[str] = None
    model: str = Field(default="nova-2-general")
    tts_model: str = Field(default="aura-asteria-en")
    greeting: Optional[str] = None
    instructions: Optional[str] = None
    input_encoding: str = Field(default="linear16")
    input_sample_rate_hz: int = Field(default=16000)
    continuous_input: bool = Field(default=True)

class BargeInConfig(BaseModel):
    enabled: bool = Field(default=True)
    initial_protection_ms: int = Field(default=200)
    min_ms: int = Field(default=250)
    energy_threshold: int = Field(default=1000)
    cooldown_ms: int = Field(default=500)
    # New: short guard window after TTS ends to avoid self-echo re-capture
    post_tts_end_protection_ms: int = Field(default=250)


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


class StreamingConfig(BaseModel):
    sample_rate: int = Field(default=8000)
    jitter_buffer_ms: int = Field(default=50)
    keepalive_interval_ms: int = Field(default=5000)
    connection_timeout_ms: int = Field(default=10000)
    fallback_timeout_ms: int = Field(default=4000)
    chunk_size_ms: int = Field(default=20)
    min_start_ms: int = Field(default=120)
    low_watermark_ms: int = Field(default=80)
    provider_grace_ms: int = Field(default=500)
    logging_level: str = Field(default="info")


class AppConfig(BaseModel):
    default_provider: str
    providers: Dict[str, Any]
    asterisk: AsteriskConfig
    llm: LLMConfig
    audio_transport: str = Field(default="externalmedia")  # 'externalmedia' | 'legacy'
    downstream_mode: str = Field(default="file")  # 'file' | 'stream'
    external_media: Optional[ExternalMediaConfig] = Field(default_factory=ExternalMediaConfig)
    audiosocket: Optional[AudioSocketConfig] = Field(default_factory=AudioSocketConfig)
    vad: Optional[VADConfig] = Field(default_factory=VADConfig)
    streaming: Optional[StreamingConfig] = Field(default_factory=StreamingConfig)
    barge_in: Optional[BargeInConfig] = Field(default_factory=BargeInConfig)

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

        # AudioSocket configuration defaults
        audiosocket_cfg = config_data.get('audiosocket', {}) or {}
        audiosocket_cfg.setdefault('host', os.getenv('AUDIOSOCKET_HOST', '0.0.0.0'))
        try:
            audiosocket_cfg.setdefault('port', int(os.getenv('AUDIOSOCKET_PORT', audiosocket_cfg.get('port', 8090))))
        except ValueError:
            audiosocket_cfg['port'] = 8090
        # AudioSocket payload format expected by Asterisk dialplan (matches third arg to AudioSocket(...))
        audiosocket_cfg.setdefault('format', os.getenv('AUDIOSOCKET_FORMAT', audiosocket_cfg.get('format', 'ulaw')))
        config_data['audiosocket'] = audiosocket_cfg

        # Barge-in configuration defaults + env overrides
        barge_cfg = config_data.get('barge_in', {}) or {}
        try:
            if 'BARGE_IN_ENABLED' in os.environ:
                barge_cfg['enabled'] = os.getenv('BARGE_IN_ENABLED', 'true').lower() in ('1','true','yes')
            if 'BARGE_IN_INITIAL_PROTECTION_MS' in os.environ:
                barge_cfg['initial_protection_ms'] = int(os.getenv('BARGE_IN_INITIAL_PROTECTION_MS', '200'))
            if 'BARGE_IN_MIN_MS' in os.environ:
                barge_cfg['min_ms'] = int(os.getenv('BARGE_IN_MIN_MS', '250'))
            if 'BARGE_IN_ENERGY_THRESHOLD' in os.environ:
                barge_cfg['energy_threshold'] = int(os.getenv('BARGE_IN_ENERGY_THRESHOLD', '1000'))
            if 'BARGE_IN_COOLDOWN_MS' in os.environ:
                barge_cfg['cooldown_ms'] = int(os.getenv('BARGE_IN_COOLDOWN_MS', '500'))
            if 'BARGE_IN_POST_TTS_END_PROTECTION_MS' in os.environ:
                barge_cfg['post_tts_end_protection_ms'] = int(os.getenv('BARGE_IN_POST_TTS_END_PROTECTION_MS', '250'))
        except ValueError:
            pass
        config_data['barge_in'] = barge_cfg

        return AppConfig(**config_data)
    except FileNotFoundError:
        # Re-raise with a more informative error message
        raise FileNotFoundError(f"Configuration file not found at the resolved path: {path}")
    except yaml.YAMLError as e:
        # Re-raise with a more informative error message
        raise yaml.YAMLError(f"Error parsing YAML file at {path}: {e}")
