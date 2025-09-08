"""
Shared Configuration System for Asterisk AI Voice Agent v2.0

This module provides centralized configuration management for all microservices
using Pydantic v2 for validation and type safety.
"""

from typing import Optional, Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
import os
from pathlib import Path


class BaseConfig(BaseSettings):
    """Base configuration class with common settings"""
    
    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level for the service"
    )
    
    # Redis Configuration
    redis_url: str = Field(
        default="redis://redis:6379",
        description="Redis connection URL for message queue"
    )
    
    class Config:
        env_file = Path(__file__).parent.parent / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


class AsteriskConfig(BaseConfig):
    """Asterisk-specific configuration"""
    
    # Asterisk Connection
    asterisk_host: str = Field(
        default="voiprnd.nemtclouddispatch.com",
        description="Asterisk server hostname or IP"
    )
    asterisk_version: str = Field(
        default="16",
        description="Asterisk version for compatibility"
    )
    asterisk_port: int = Field(
        default=8088,
        description="Asterisk ARI port"
    )
    
    # ARI Configuration
    ari_username: str = Field(
        default="AIAgent",
        description="ARI username for authentication"
    )
    ari_password: str = Field(
        default="c4d5359e2f9ddd394cd6aa116c1c6a96",
        description="ARI password for authentication"
    )
    
    @property
    def ari_url(self) -> str:
        """Generate ARI WebSocket URL"""
        return f"ws://{self.asterisk_host}:{self.asterisk_port}/ari/events?api_key={self.ari_username}:{self.ari_password}"


class RTPEngineConfig(BaseConfig):
    """RTPEngine media proxy configuration"""
    
    rtpengine_host: str = Field(
        default="rtpengine",
        description="RTPEngine server hostname"
    )
    rtpengine_port: int = Field(
        default=2223,
        description="RTPEngine control port"
    )
    
    @property
    def rtpengine_url(self) -> str:
        """Generate RTPEngine control URL"""
        return f"http://{self.rtpengine_host}:{self.rtpengine_port}"


class AIProviderConfig(BaseConfig):
    """AI provider configuration"""
    
    # OpenAI Configuration
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API key for STT, LLM, and TTS"
    )
    
    # Deepgram Configuration
    deepgram_api_key: Optional[str] = Field(
        default=None,
        description="Deepgram API key for alternative STT"
    )
    
    # LLM Configuration
    fallback_llm_model: str = Field(
        default="gpt-3.5-turbo",
        description="Fallback LLM model for error recovery"
    )
    
    @field_validator('openai_api_key')
    @classmethod
    def validate_openai_key(cls, v):
        if v is None or v == "":
            raise ValueError("OpenAI API key is required")
        return v


class CallControllerConfig(AsteriskConfig, RTPEngineConfig, AIProviderConfig):
    """Call Controller service configuration"""
    
    # Service-specific settings
    service_name: str = "call_controller"
    health_check_port: int = 16000
    
    # Call handling settings
    max_concurrent_calls: int = Field(
        default=10,
        description="Maximum number of concurrent calls"
    )
    call_timeout_seconds: int = Field(
        default=300,
        description="Maximum call duration in seconds"
    )


class STTServiceConfig(AIProviderConfig, AsteriskConfig):
    """STT Service configuration"""
    
    service_name: str = "stt_service"
    health_check_port: int = 8001
    rtp_listen_port: int = 5004
    
    # Audio processing settings
    sample_rate: int = Field(
        default=16000,
        description="Audio sample rate for processing"
    )
    chunk_size: int = Field(
        default=1024,
        description="Audio chunk size for processing"
    )


class LLMServiceConfig(AIProviderConfig, AsteriskConfig):
    """LLM Service configuration"""
    
    service_name: str = "llm_service"
    health_check_port: int = 8002
    
    # OpenAI LLM specific settings
    openai_base_url: Optional[str] = Field(default=None, description="OpenAI API base URL")
    primary_model: str = Field(default="gpt-4o", description="Primary LLM model")
    fallback_model: str = Field(default="gpt-3.5-turbo", description="Fallback LLM model")
    temperature: float = Field(default=0.8, description="LLM temperature")
    max_tokens: int = Field(default=4096, description="LLM max tokens")
    system_message: str = Field(default="You are a helpful AI assistant for Jugaar LLC.", description="LLM system message")
    enable_debug_logging: bool = Field(default=False, description="Enable debug logging for conversation manager")

    # Conversation settings
    max_conversation_history: int = Field(
        default=20,
        description="Maximum conversation turns to keep in memory"
    )
    conversation_ttl: int = Field(default=3600, description="Time-to-live for conversation history in seconds")
    max_conversation_tokens: int = Field(default=4000, description="Maximum tokens for conversation history")
    token_limit: int = Field(default=4096, description="Token limit for conversation history")
    conversation_timeout: int = Field(default=600, description="Conversation timeout in seconds")
    response_timeout_seconds: int = Field(
        default=30,
        description="Maximum time to wait for LLM response"
    )


class TTSServiceConfig(AIProviderConfig, AsteriskConfig):
    """TTS Service configuration"""
    
    service_name: str = "tts_service"
    health_check_port: int = 8003
    
    # OpenAI TTS specific settings
    openai_base_url: Optional[str] = Field(default=None, description="OpenAI API base URL")
    voice: str = Field(default="alloy", description="TTS voice")
    model: str = Field(default="tts-1", description="TTS model")
    audio_format: str = Field(default="mp3", description="TTS audio format")
    speed: float = Field(default=1.0, description="TTS speed")

    # Audio file management settings
    base_directory: str = Field(default="/shared/audio", description="Base directory for audio files")
    temp_directory: str = Field(default="/tmp/tts_audio", description="Temporary directory for audio files")
    file_ttl: int = Field(default=300, description="Time-to-live for audio files in seconds")
    max_file_size: int = Field(default=10485760, description="Maximum file size for audio files in bytes")
    enable_debug_logging: bool = Field(default=False, description="Enable debug logging for file manager")
    enable_fallback: bool = Field(default=True, description="Enable fallback to Asterisk's SayAlpha")
    fallback_mode: str = Field(default="sayalpha", description="Fallback mode: 'sayalpha', 'saydigits', 'sayphonetic', or 'disabled'")

    # Audio output settings
    output_sample_rate: int = Field(
        default=16000,
        description="Output audio sample rate"
    )
    output_format: str = Field(
        default="wav",
        description="Output audio format"
    )


def load_config(service_name: str) -> BaseConfig:
    """
    Load configuration for a specific service
    
    Args:
        service_name: Name of the service (call_controller, stt_service, etc.)
        
    Returns:
        Appropriate configuration object for the service
        
    Raises:
        ValueError: If service_name is not recognized
    """
    config_map = {
        "call_controller": CallControllerConfig,
        "stt_service": STTServiceConfig,
        "llm_service": LLMServiceConfig,
        "tts_service": TTSServiceConfig,
    }
    
    if service_name not in config_map:
        raise ValueError(f"Unknown service: {service_name}")
    
    return config_map[service_name]()


def validate_required_env_vars():
    """
    Validate that all required environment variables are set
    
    Raises:
        ValueError: If any required environment variables are missing
    """
    required_vars = [
        "OPENAI_API_KEY",
        "DEEPGRAM_API_KEY",
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")


if __name__ == "__main__":
    # Test configuration loading
    try:
        config = load_config("call_controller")
        print(f"✅ Configuration loaded successfully for {config.service_name}")
        print(f"   ARI URL: {config.ari_url}")
        print(f"   Redis URL: {config.redis_url}")
        print(f"   RTPEngine URL: {config.rtpengine_url}")
    except Exception as e:
        print(f"❌ Configuration error: {e}")
