"""
TTS Service - Main Entry Point

This service handles text-to-speech synthesis.
It adapts the existing tts_handler.py from the v1.0 architecture.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from config import CallControllerConfig
from redis_client import RedisMessageQueue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TTSService:
    def __init__(self):
        self.config = CallControllerConfig()
        self.redis_client = RedisMessageQueue()
        self.running = False

    async def start(self):
        """Start the TTS service"""
        logger.info("Starting TTS Service - v2.0")
        
        try:
            # Connect to Redis
            await self.redis_client.connect()
            logger.info("Connected to Redis")
            
            # Subscribe to LLM response events
            await self.redis_client.subscribe("llm:response:ready")
            logger.info("Subscribed to llm:response:ready")
            
            self.running = True
            
            # Main service loop
            while self.running:
                try:
                    # Process Redis messages
                    message = await self.redis_client.get_message()
                    if message:
                        await self._handle_llm_response(message)
                        
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.error(f"Failed to start TTS service: {e}")
            raise

    async def _handle_llm_response(self, message):
        """Handle LLM response for TTS synthesis"""
        try:
            logger.info(f"Received LLM response: {message}")
            
            # TODO: Convert text to speech
            # TODO: Generate audio file
            # TODO: Publish audio to tts:audio:ready
            
            logger.info("TTS synthesis completed successfully")
            
        except Exception as e:
            logger.error(f"Error handling LLM response: {e}")

    async def stop(self):
        """Stop the TTS service"""
        logger.info("Stopping TTS Service")
        self.running = False
        await self.redis_client.disconnect()

async def main():
    """Main entry point"""
    service = TTSService()
    
    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Service failed: {e}")
        sys.exit(1)
    finally:
        await service.stop()

if __name__ == "__main__":
    asyncio.run(main())