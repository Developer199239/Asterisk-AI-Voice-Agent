"""
LLM Service - Main Entry Point

This service manages the conversation logic and context.
It adapts the existing llm_handler.py from the v1.0 architecture.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from config import CallControllerConfig
from redis_client import RedisClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        self.config = CallControllerConfig()
        self.redis_client = RedisClient()
        self.running = False

    async def start(self):
        """Start the LLM service"""
        logger.info("Starting LLM Service - v2.0")
        
        try:
            # Connect to Redis
            await self.redis_client.connect()
            logger.info("Connected to Redis")
            
            # Subscribe to STT transcription events
            await self.redis_client.subscribe("stt:transcription:complete")
            logger.info("Subscribed to stt:transcription:complete")
            
            self.running = True
            
            # Main service loop
            while self.running:
                try:
                    # Process Redis messages
                    message = await self.redis_client.get_message()
                    if message:
                        await self._handle_transcription(message)
                        
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.error(f"Failed to start LLM service: {e}")
            raise

    async def _handle_transcription(self, message):
        """Handle STT transcription completion"""
        try:
            logger.info(f"Received transcription: {message}")
            
            # TODO: Process transcription and generate response
            # TODO: Publish response to llm:response:ready
            
            logger.info("Transcription processed successfully")
            
        except Exception as e:
            logger.error(f"Error handling transcription: {e}")

    async def stop(self):
        """Stop the LLM service"""
        logger.info("Stopping LLM Service")
        self.running = False
        await self.redis_client.disconnect()

async def main():
    """Main entry point"""
    service = LLMService()
    
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