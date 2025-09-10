"""
LLM Service - Main Entry Point

This service handles language model operations for the AI Voice Agent.
It processes transcription data and generates appropriate responses using OpenAI.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
import structlog
from typing import Dict, Any

from shared.health_check import create_health_check_app
import uvicorn

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from shared.logging_config import setup_logging
from shared.config import load_config, LLMServiceConfig
from llm_service import LLMService

# Load configuration and set up logging
config = load_config("llm_service")
setup_logging(log_level=config.log_level)

logger = structlog.get_logger(__name__)


async def main():
    """Main entry point."""
    try:
        # Load configuration from environment
        config = LLMServiceConfig(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL"),
            primary_model=os.getenv("LLM_PRIMARY_MODEL", "gpt-4o"),
            fallback_model=os.getenv("LLM_FALLBACK_MODEL", "gpt-3.5-turbo"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.8")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            conversation_ttl=int(os.getenv("LLM_CONVERSATION_TTL", "3600")),
            max_conversation_tokens=int(os.getenv("LLM_MAX_CONVERSATION_TOKENS", "4000")),
            system_message=os.getenv("LLM_SYSTEM_MESSAGE", "You are a helpful AI assistant for Jugaar LLC."),
            enable_debug_logging=os.getenv("LLM_DEBUG_LOGGING", "true").lower() == "true"
        )
        
        # Validate required configuration
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        # Create and start service
        service = LLMService(config)
        await service.start()
        
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())