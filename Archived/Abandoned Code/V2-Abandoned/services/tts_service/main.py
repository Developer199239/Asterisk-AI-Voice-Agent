"""
TTS Service - Main Entry Point

This service handles text-to-speech processing and audio file management
using OpenAI TTS API and shared volume file storage.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any

import structlog

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from shared.logging_config import setup_logging
from shared.config import load_config, TTSServiceConfig
from shared.health_check import create_health_check_app
import uvicorn

from tts_service import TTSService, FallbackMode

# Load configuration and set up logging
config = load_config("tts_service")
setup_logging(log_level=config.log_level)

logger = structlog.get_logger(__name__)


async def main():
    """Main entry point."""
    try:
        # Load configuration from environment
        # config = TTSServiceConfig(
        #     redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        #     openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        #     openai_base_url=os.getenv("OPENAI_BASE_URL"),
        #     voice=os.getenv("TTS_VOICE", "alloy"),
        #     model=os.getenv("TTS_MODEL", "tts-1"),
        #     audio_format=os.getenv("TTS_AUDIO_FORMAT", "mp3"),
        #     speed=float(os.getenv("TTS_SPEED", "1.0")),
        #     base_directory=os.getenv("TTS_BASE_DIRECTORY", "/shared/audio"),
        #     temp_directory=os.getenv("TTS_TEMP_DIRECTORY", "/tmp/tts_audio"),
        #     file_ttl=int(os.getenv("TTS_FILE_TTL", "300")),
        #     max_file_size=int(os.getenv("TTS_MAX_FILE_SIZE", "10485760")),  # 10MB
        #     enable_debug_logging=os.getenv("TTS_DEBUG_LOGGING", "true").lower() == "true"
        # )
        
        # Validate required configuration
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        # Create and start service
        service = TTSService(config)
        await service.start()
        
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())