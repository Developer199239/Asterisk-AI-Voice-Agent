"""
STT Service - Main Entry Point

This service handles speech-to-text processing.
It adapts the existing stt_handler.py from the v1.0 architecture.
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

class STTService:
    def __init__(self):
        self.config = CallControllerConfig()
        self.redis_client = RedisMessageQueue()
        self.running = False

    async def start(self):
        """Start the STT service"""
        logger.info("Starting STT Service - v2.0")
        
        try:
            # Connect to Redis
            await self.redis_client.connect()
            logger.info("Connected to Redis")
            
            # Subscribe to new call events
            await self.redis_client.subscribe(["calls:new"], self._handle_new_call)
            logger.info("Subscribed to calls:new")
            
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
            logger.error(f"Failed to start STT service: {e}")
            raise

    async def _handle_new_call(self, channel: str, message: dict):
        """Handle new call events"""
        try:
            logger.info(f"Received new call on {channel}: {message}")
            
            # TODO: Process RTP audio stream
            # TODO: Perform speech-to-text conversion
            # TODO: Publish transcription to stt:transcription:complete
            
            logger.info("New call processed successfully")
            
        except Exception as e:
            logger.error(f"Error handling new call: {e}")

    async def stop(self):
        """Stop the STT service"""
        logger.info("Stopping STT Service")
        self.running = False
        await self.redis_client.disconnect()

async def main():
    """Main entry point"""
    service = STTService()
    
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