"""
Shared Configuration System for Asterisk AI Voice Agent v2.0

This module provides centralized configuration management for all microservices
using Pydantic v2 for validation and type safety.
"""

import os
import yaml
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class AsteriskConfig(BaseModel):
    host: str
    port: int = Field(default=8088)
    username: str
    password: str
    app_name: str = Field(default="ai-voice-agent")

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
    api_key: str

class AppConfig(BaseModel):
    default_provider: str
    providers: Dict[str, Any]
    asterisk: AsteriskConfig
    llm: LLMConfig

def load_config(path: str = "config/ai-agent.yaml") -> AppConfig:
    with open(path, 'r') as f:
        config_str = f.read()

    # Substitute environment variables
    config_str_expanded = os.path.expandvars(config_str)
    
    config_data = yaml.safe_load(config_str_expanded)

    # Manually wire in some config for now until we fully move to YAML
    # This is a temporary step to keep the POC working
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

    return AppConfig(**config_data)
