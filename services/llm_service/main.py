"""
LLM Service - Main Entry Point

This service handles language model processing and conversation management.
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

class LLMService:
    def __init__(self):
        self.config = CallControllerConfig()
        self.redis_client = RedisMessageQueue()
        self.running = False

    async def start(self):
        """Start the LLM service"""
        logger.info("Starting LLM Service - v2.0")
        
        try:
            # Connect to Redis
            await self.redis_client.connect()
            logger.info("Connected to Redis")
            
            # Subscribe to transcription events
            await self.redis_client.subscribe(["stt:transcription:complete"], self._handle_transcription)
            logger.info("Subscribed to stt:transcription:complete")
            
            self.running = True
            
            # Start listening for messages
            await self.redis_client.start_listening()
            
            # Main service loop
            while self.running:
                try:
                    await asyncio.sleep(1)
                except KeyboardInterrupt:
                    break
                    
        except Exception as e:
            logger.error(f"Failed to start LLM service: {e}")
            raise

    async def _handle_transcription(self, channel: str, message: dict):
        """Handle transcription completion events"""
        try:
            logger.info(f"Received transcription on {channel}: {message}")
            
            # TODO: Process transcription with LLM
            # TODO: Generate response
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