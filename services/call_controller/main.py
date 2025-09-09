"""
Call Controller Service - Main Entry Point

This service manages the call lifecycle via ARI and controls the media proxy.
It replaces engine.py, sip_client.py, and call_session.py from the v1.0 architecture.
"""

import asyncio
import signal
import traceback

from shared.health_check import create_health_check_app
import uvicorn
import structlog

from shared.logging_config import setup_logging
from shared.config import load_config, CallControllerConfig
from shared.redis_client import RedisMessageQueue, Channels, CallNewMessage
from services.call_controller.ari_client import ARIClient
from services.call_controller.models import ARIEvent
from services.call_controller.rtpengine_client import RTPEngineClient
from services.call_controller.call_state_machine import CallStateMachine, CallState, CallData
from shared.logging_config import set_correlation_id

# Load configuration and set up logging
config = load_config("call_controller")
setup_logging(log_level=config.log_level)

logger = structlog.get_logger(__name__)


class CallControllerService:
    """Main call controller service"""
    
    def __init__(self, config: CallControllerConfig):
        self.config = config
        self.state_machine = CallStateMachine()
        self.redis_client = RedisMessageQueue(config.redis)
        self.ari_client = ARIClient(config.asterisk)
        self.rtpengine_client = RTPEngineClient(config.rtpengine)
        self.running = False
        
    async def start(self):
        """Start the call controller service"""
        logger.info(f"Starting service {self.config.service_name}")
        
        await self.ari_client.connect()
        logger.info("Connected to ARI")

        self.ari_client.add_event_handler("StasisStart", self._handle_stasis_start)
        
        self.running = True
        logger.info("Call controller service components started, entering main loop.")
        await self.ari_client.start_listening()
            
    async def stop(self):
        """Stop the call controller service"""
        logger.info("Stopping call controller service...")
        self.running = False
        
        # Stop ARI client
        if self.ari_client:
            await self.ari_client.disconnect()
        
        logger.info("Call controller service stopped")
    
    async def _handle_stasis_start(self, event: ARIEvent):
        """Handle StasisStart event - new call received"""
        channel_id = event.data["channel"]["id"]
        logger.info(f"Received StasisStart for channel {channel_id}")
        await self.ari_client.answer_channel(channel_id)
        logger.info(f"Answered channel {channel_id}")

    def is_stopped(self) -> bool:
        """Check if the service is stopped."""
        return not self.running


async def main():
    """Main entry point"""
    
    config = load_config("call_controller")
    setup_logging(log_level=config.log_level)
    service = CallControllerService(config)
    
    # Set up signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(service.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    service_task = None
    try:
        service_task = asyncio.create_task(service.start())
        logger.info("Call Controller Service starting...")

        # Keep running until shutdown is triggered
        while not service.is_stopped():
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("Main task cancelled.")
    except Exception as e:
        logger.error(f"Service error in main: {e}", exc_info=True)
    finally:
        if service_task and not service_task.done():
            service_task.cancel()
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
