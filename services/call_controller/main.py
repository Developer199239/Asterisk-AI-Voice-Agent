"""
Call Controller Service - Main Entry Point

This service manages the call lifecycle via ARI and controls the media proxy.
It replaces engine.py, sip_client.py, and call_session.py from the v1.0 architecture.
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional
from aiohttp import web

from shared.health_check import create_health_check_app
import uvicorn

# Add shared modules to path
# sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from shared.logging_config import setup_logging
from shared.config import load_config, CallControllerConfig
from shared.redis_client import get_redis_queue, Channels, CallNewMessage, CallControlMessage
from ari_client import ARIClient, ARIEvent
# from rtpengine_client import RTPEngineClient
from call_state_machine import CallStateMachine, CallState, CallData
import structlog
from shared.logging_config import set_correlation_id


# Load configuration and set up logging
config = load_config("call_controller")
setup_logging(log_level=config.log_level)

logger = structlog.get_logger(__name__)


class CallControllerService:
    """Main call controller service"""
    
    def __init__(self):
        self.config: Optional[CallControllerConfig] = None
        self.ari_client: Optional[ARIClient] = None
        # self.rtpengine_client: Optional[RTPEngineClient] = None
        self.redis_queue = None
        self.state_machine = CallStateMachine()
        self.running = False
        
    async def start(self):
        """Start the call controller service"""
        try:
            # Load configuration
            self.config = load_config("call_controller")
            logger.info(f"Loaded configuration for {self.config.service_name}")
            
            # Initialize Redis message queue
            self.redis_queue = await get_redis_queue(self.config.redis_url)
            logger.info("Connected to Redis message queue")
            
            # Initialize ARI client
            self.ari_client = ARIClient(
                host=self.config.asterisk_host,
                port=8088,  # Standard ARI port
                username=self.config.ari_username,
                password=self.config.ari_password
            )
            await self.ari_client.connect()
            logger.info("Connected to Asterisk ARI")
            
            # # Initialize RTPEngine client
            # self.rtpengine_client = RTPEngineClient(
            #     host=self.config.rtpengine_host,
            #     port=self.config.rtpengine_port
            # )
            # await self.rtpengine_client.connect()
            # logger.info("Connected to RTPEngine")
            
            # Set up event handlers
            self._setup_ari_handlers()
            self._setup_redis_handlers()
            self._setup_state_handlers()
            
            # Start services
            self.running = True
            await self._start_services()
            
        except Exception as e:
            logger.error(f"Failed to start call controller service: {e}")
            await self.stop()
            raise
    
    async def stop(self):
        """Stop the call controller service"""
        logger.info("Stopping call controller service...")
        self.running = False
        
        # Stop ARI client
        if self.ari_client:
            await self.ari_client.disconnect()
        
        # # Stop RTPEngine client
        # if self.rtpengine_client:
        #     await self.rtpengine_client.disconnect()
        
        # Stop Redis queue
        if self.redis_queue:
            await self.redis_queue.disconnect()
        
        logger.info("Call controller service stopped")
    
    def _setup_ari_handlers(self):
        """Set up ARI event handlers"""
        self.ari_client.add_event_handler("StasisStart", self._handle_stasis_start)
        self.ari_client.add_event_handler("StasisEnd", self._handle_stasis_end)
        self.ari_client.add_event_handler("ChannelDtmfReceived", self._handle_dtmf)
        self.ari_client.add_event_handler("PlaybackStarted", self._handle_playback_started)
        self.ari_client.add_event_handler("PlaybackFinished", self._handle_playback_finished)
    
    def _setup_redis_handlers(self):
        """Set up Redis message handlers"""
        # Subscribe to call control messages
        asyncio.create_task(self.redis_queue.subscribe(
            [Channels.CALLS_CONTROL_PLAY, Channels.CALLS_CONTROL_STOP, "barge_in:detected"],
            self._handle_call_control
        ))
    
    def _setup_state_handlers(self):
        """Set up call state machine handlers"""
        # State entry handlers
        self.state_machine.add_state_handler(CallState.ANSWERED, self._handle_call_answered)
        self.state_machine.add_state_handler(CallState.LISTENING, self._handle_call_listening)
        self.state_machine.add_state_handler(CallState.SPEAKING, self._handle_call_speaking)
        self.state_machine.add_state_handler(CallState.ENDED, self._handle_call_ended)
        
        # Transition handlers
        self.state_machine.add_transition_handler(
            CallState.RINGING, CallState.ANSWERED, self._handle_call_answered_transition
        )
    
    async def _start_health_check_server(self):
        """Start the health check server."""
        dependency_checks = [
            ("ari", self.ari_client.health_check),
            ("redis", self.redis_queue.health_check),
            # ("rtpengine", self.rtpengine_client.health_check),
        ]
        app = create_health_check_app("call_controller", dependency_checks)
        
        config = uvicorn.Config(app, host="0.0.0.0", port=self.config.health_check_port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def _start_services(self):
        """Start all background services"""
        tasks = [
            asyncio.create_task(self._start_health_check_server()),
            asyncio.create_task(self.ari_client.start_listening()),
            asyncio.create_task(self.redis_queue.start_listening()),
            asyncio.create_task(self._timeout_checker()),
            asyncio.create_task(self._health_checker())
        ]
        
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in background services: {e}")
            raise
    
    async def _health_endpoint(self, request):
        """Health check endpoint"""
        return web.json_response({
            "status": "healthy",
            "service": "call_controller",
            "timestamp": asyncio.get_event_loop().time()
        })
    
    # ARI Event Handlers
    
    async def _handle_stasis_start(self, event: ARIEvent):
        """Handle StasisStart event - new call received"""
        try:
            channel_id = event.data["channel"]["id"]
            set_correlation_id(channel_id)
            
            caller_id = event.data.get("caller", {}).get("number")
            caller_name = event.data.get("caller", {}).get("name")
            
            # Create new call
            call_id = self.state_machine.create_call(channel_id, caller_id, caller_name)
            
            # Answer the call
            await self.ari_client.answer_channel(channel_id)
            
            # Transition to answered state
            self.state_machine.transition_call(call_id, CallState.ANSWERED)
            
            # Publish call new message
            message = CallNewMessage(
                message_id=f"call-{call_id}",
                source_service="call_controller",
                call_id=call_id,
                channel_id=channel_id,
                caller_id=caller_id,
                caller_name=caller_name
            )
            await self.redis_queue.publish(Channels.CALLS_NEW, message)
            
            logger.info(f"Handled new call {call_id} from {caller_id}")
            
        except Exception as e:
            logger.error(f"Error handling StasisStart: {e}")
    
    async def _handle_stasis_end(self, event: ARIEvent):
        """Handle StasisEnd event - call ended"""
        try:
            channel_id = event.data["channel"]["id"]
            set_correlation_id(channel_id)
            call_data = self.state_machine.get_call_by_channel(channel_id)
            
            if call_data:
                self.state_machine.end_call(call_data.call_id, "stasis_end")
                logger.info(f"Call {call_data.call_id} ended via StasisEnd")
            
        except Exception as e:
            logger.error(f"Error handling StasisEnd: {e}")
    
    async def _handle_dtmf(self, event: ARIEvent):
        """Handle DTMF input"""
        try:
            channel_id = event.data["channel"]["id"]
            set_correlation_id(channel_id)
            digit = event.data["digit"]
            
            call_data = self.state_machine.get_call_by_channel(channel_id)
            if call_data:
                logger.info(f"DTMF {digit} received on call {call_data.call_id}")
                
                # Handle special DTMF commands
                if digit == "*":
                    # Hangup call
                    await self.ari_client.hangup_channel(channel_id)
                elif digit == "#":
                    # Transfer call (placeholder)
                    self.state_machine.transition_call(call_data.call_id, CallState.TRANSFERRING)
            
        except Exception as e:
            logger.error(f"Error handling DTMF: {e}")
    
    async def _handle_playback_started(self, event: ARIEvent):
        """Handle playback started event"""
        try:
            channel_id = event.data["playback"]["target_uri"].split(":")[1]
            set_correlation_id(channel_id)
            call_data = self.state_machine.get_call_by_channel(channel_id)
            
            if call_data and call_data.state == CallState.LISTENING:
                self.state_machine.transition_call(call_data.call_id, CallState.SPEAKING)
                logger.info(f"Started speaking on call {call_data.call_id}")
            
        except Exception as e:
            logger.error(f"Error handling playback started: {e}")
    
    async def _handle_playback_finished(self, event: ARIEvent):
        """Handle playback finished event"""
        try:
            channel_id = event.data["playback"]["target_uri"].split(":")[1]
            set_correlation_id(channel_id)
            call_data = self.state_machine.get_call_by_channel(channel_id)
            
            if call_data and call_data.state == CallState.SPEAKING:
                self.state_machine.transition_call(call_data.call_id, CallState.LISTENING)
                logger.info(f"Finished speaking on call {call_data.call_id}")
            
        except Exception as e:
            logger.error(f"Error handling playback finished: {e}")
    
    # Redis Message Handlers
    
    async def _handle_call_control(self, channel: str, message_data: dict):
        """Handle call control messages from Redis"""
        if channel == "barge_in:detected":
            await self._handle_barge_in(message_data)
            return

        try:
            channel_id = message_data.get("channel_id")
            set_correlation_id(channel_id)
            action = message_data.get("action")
            call_id = message_data.get("call_id")
            
            call_data = self.state_machine.get_call(call_id)
            if not call_data:
                logger.warning(f"Call {call_id} not found for control action {action}")
                return
            
            if action == "play":
                # Play audio file
                audio_file = message_data.get("audio_file")
                if audio_file:
                    await self.ari_client.play_media(call_data.channel_id, audio_file)
                    logger.info(f"Playing {audio_file} on call {call_id}")
            
            elif action == "stop":
                # Stop current playback
                await self.ari_client.stop_media(call_data.channel_id)
                logger.info(f"Stopped playback on call {call_id}")
            
            elif action == "hangup":
                # Hangup call
                await self.ari_client.hangup_channel(call_data.channel_id)
                logger.info(f"Hanging up call {call_id}")
            
        except Exception as e:
            logger.error(f"Error handling call control: {e}")

    async def _handle_barge_in(self, message_data: dict):
        """Handle barge-in events from Redis"""
        try:
            channel_id = message_data.get("channel_id")
            if not channel_id:
                return

            set_correlation_id(channel_id)
            call_data = self.state_machine.get_call_by_channel(channel_id)
            
            if call_data and call_data.state == CallState.SPEAKING:
                logger.info("Barge-in detected, stopping playback", call_id=call_data.call_id)
                await self.ari_client.stop_media(call_data.channel_id)
                self.state_machine.transition_call(call_data.call_id, CallState.LISTENING)
        
        except Exception as e:
            logger.error("Error handling barge-in", exc_info=True)

    # State Machine Handlers
    
    async def _handle_call_answered(self, call_data: CallData):
        """Handle call answered state"""
        logger.info(f"Call {call_data.call_id} answered, transitioning to listening")
        # Transition to listening state after a brief delay
        await asyncio.sleep(1)
        self.state_machine.transition_call(call_data.call_id, CallState.LISTENING)
    
    async def _handle_call_listening(self, call_data: CallData):
        """Handle call listening state"""
        logger.info(f"Call {call_data.call_id} is listening for user input")
        # In a real implementation, this would trigger STT service
    
    async def _handle_call_speaking(self, call_data: CallData):
        """Handle call speaking state"""
        logger.info(f"Call {call_data.call_id} is speaking")
        # In a real implementation, this would handle TTS playback
    
    async def _handle_call_ended(self, call_data: CallData):
        """Handle call ended state"""
        logger.info(f"Call {call_data.call_id} ended")
        # Cleanup call after a delay
        await asyncio.sleep(5)
        self.state_machine.cleanup_call(call_data.call_id)
    
    async def _handle_call_answered_transition(self, call_data: CallData, old_state, new_state):
        """Handle transition to answered state"""
        logger.info(f"Call {call_data.call_id} transitioned from {old_state} to {new_state}")
    
    # Background Tasks
    
    async def _timeout_checker(self):
        """Check for timed out calls"""
        while self.running:
            try:
                timed_out_calls = self.state_machine.check_timeouts()
                for call_id in timed_out_calls:
                    logger.warning(f"Call {call_id} timed out")
                
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Error in timeout checker: {e}")
                await asyncio.sleep(30)
    
    async def _health_checker(self):
        """Check service health"""
        while self.running:
            try:
                # Check ARI health
                ari_health = await self.ari_client.health_check()
                if not ari_health:
                    logger.error("ARI health check failed")
                
                # # Check RTPEngine health
                # rtpengine_health = await self.rtpengine_client.health_check()
                # if not rtpengine_health:
                #     logger.error("RTPEngine health check failed")
                
                # Check Redis health
                redis_health = await self.redis_queue.health_check()
                if not redis_health:
                    logger.error("Redis health check failed")
                
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in health checker: {e}")
                await asyncio.sleep(60)


async def main():
    """Main entry point"""
    service = CallControllerService()
    
    # Set up signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(service.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await service.start()
        logger.info("Call Controller Service started successfully")
        
        # Keep running
        while service.running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Service error: {e}")
    finally:
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
