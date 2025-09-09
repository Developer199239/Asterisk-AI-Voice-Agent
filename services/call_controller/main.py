"""
Call Controller Service - Main Entry Point

This service manages the call lifecycle via ARI and controls the media proxy.
It replaces engine.py, sip_client.py, and call_session.py from the v1.0 architecture.
"""

import asyncio
import structlog
import signal
from typing import Dict, Any, List, Callable
import uuid
import json
from concurrent.futures import ThreadPoolExecutor

from shared.config import load_config
from services.call_controller.ari_client import ARIClient
from shared.redis_client import RedisMessageQueue, CallControlMessage, CallNewMessage, Channels
from services.call_controller.udp_server import UDPServer

logger = structlog.get_logger(__name__)

class CallControllerService:
    def __init__(self):
        self.config = load_config('call_controller')
        self.ari_client = ARIClient(self.config.asterisk)
        # self.rtpengine_client = RTPEngineClient(self.config.rtpengine) # No longer needed
        self.redis_queue = RedisMessageQueue(self.config.redis)
        self.active_calls: Dict[str, Any] = {}
        self.running = False
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.setup_event_handlers()
        self.udp_server = UDPServer('0.0.0.0', 54322)

    def setup_event_handlers(self):
        self.ari_client.on_event('StasisStart', self._handle_stasis_start)
        self.ari_client.on_event('StasisEnd', self._handle_stasis_end)
        self.ari_client.on_event('ChannelDtmfReceived', self._handle_dtmf_received)
        self.ari_client.on_event('PlaybackStarted', self._handle_playback_started)
        self.ari_client.on_event('PlaybackFinished', self._handle_playback_finished)
        self.ari_client.on_event('ChannelStateChange', self._handle_channel_state_change)
        # self.udp_server = UDPServer('0.0.0.0', 54321) # This line is moved to __init__

    async def start(self):
        logger.info(f"Starting service {self.config.service_name}")
        await self.redis_queue.connect()
        # await self.rtpengine_client.connect() # No longer needed
        await self.ari_client.connect()

        # Start UDP server in a background task
        asyncio.create_task(self.udp_server.start())

        asyncio.create_task(self.listen_for_control_messages())

        self.running = True
        logger.info("Call controller service components started, entering main loop.")
        await self.ari_client.start_listening()

    async def stop(self):
        logger.info("Stopping call controller service...")
        self.running = False
        for channel_id in list(self.active_calls.keys()):
            await self._cleanup_call(channel_id)
        if self.ari_client:
            await self.ari_client.disconnect()
        # if self.rtpengine_client:
        #     await self.rtpengine_client.disconnect()
        if self.redis_queue:
            await self.redis_queue.disconnect()
        
        self.udp_server.stop()
        logger.info("Call controller service stopped")

    async def _handle_control_message(self, channel: str, message_data: dict):
        """Handler for incoming Redis control messages."""
        try:
            control_message = CallControlMessage.model_validate(message_data)
            logger.debug("Received control message", data=control_message)

            if control_message.action == "play":
                # Assuming 'file_path' is in parameters
                file_path = control_message.parameters.get("file_path")
                if file_path:
                    await self.ari_client.play_media(control_message.call_id, f"sound:{file_path}")
            elif control_message.action == "stop_playback":
                logger.info("Received stop_playback command", call_id=control_message.call_id)

        except Exception as e:
            logger.error("Error processing control message", exc_info=True, raw_message=message_data)

    async def listen_for_control_messages(self):
        logger.info("Subscribing to control messages from Redis...")
        control_channels = [
            Channels.CALLS_CONTROL_PLAY,
            Channels.CALLS_CONTROL_STOP
        ]
        await self.redis_queue.subscribe(control_channels, self._handle_control_message)
        await self.redis_queue.start_listening()
        logger.info("Stopped listening for control messages.")

    async def _handle_stasis_start(self, event_data: dict):
        channel = event_data.get('channel', {})
        channel_id = channel.get('id')
        if not channel_id:
            logger.warning("StasisStart event with no channel ID")
            return

        logger.info("New call received", channel_id=channel_id, caller=channel.get('caller'))
        self.active_calls[channel_id] = {'channel_data': channel, 'state': 'ringing'}

        try:
            # Generate a unique call ID for tracking across services
            call_id = f"call-{uuid.uuid4()}"
            self.active_calls[channel_id]['call_id'] = call_id

            # sdp = event_data.get('channel', {}).get('dialplan', {}).get('exten')
            # rtp_info = await self.rtpengine_client.offer(sdp, call_id=call_id)
            # self.active_calls[channel_id]['rtp_info'] = rtp_info

            await self.ari_client.answer_channel(channel_id)
            self.active_calls[channel_id]['state'] = 'answered'
            logger.info("Channel answered", channel_id=channel_id)

            # Add a small delay to ensure the channel is fully up in ARI
            await asyncio.sleep(1)

            # Start forwarding media to our UDP server
            logger.info("Issuing externalMedia command to Asterisk...")
            await self.ari_client.send_command(
                "POST",
                f"channels/{channel_id}/externalMedia",
                data={
                    "app": self.config.asterisk.app_name,
                    "external_host": f"127.0.0.1:54322",
                    "format": "slin16"
                }
            )
            logger.info("externalMedia command sent successfully.")

            new_call_message = CallNewMessage(
                message_id=f"msg-{uuid.uuid4()}",
                source_service=self.config.service_name,
                call_id=call_id,
                channel_id=channel_id,
                caller_id=channel.get('caller', {}).get('number'),
                caller_name=channel.get('caller', {}).get('name')
            )
            await self.redis_queue.publish(Channels.CALLS_NEW, new_call_message)
            logger.info("Published new call event to Redis", channel_id=channel_id, call_id=call_id)

            # Generate a basic AI response
            await self._generate_ai_response(channel_id, call_id)

        except Exception as e:
            logger.error("Error handling StasisStart", channel_id=channel_id, exc_info=True)
            await self._cleanup_call(channel_id)

    async def _handle_stasis_end(self, event_data: dict):
        channel_id = event_data.get('channel', {}).get('id')
        logger.info("Call ended", channel_id=channel_id)
        await self._cleanup_call(channel_id)

    async def _cleanup_call(self, channel_id: str):
        if channel_id in self.active_calls:
            # rtp_info = self.active_calls[channel_id].get('rtp_info')
            # if rtp_info:
            #     await self.rtpengine_client.delete(rtp_info['call-id'])
            del self.active_calls[channel_id]
            logger.info("Cleaned up call resources", channel_id=channel_id)

    async def _handle_dtmf_received(self, event_data: dict):
        channel_id = event_data.get('channel', {}).get('id')
        digit = event_data.get('digit')
        logger.info("DTMF received", channel_id=channel_id, digit=digit)

    async def _handle_playback_started(self, event_data: dict):
        playback = event_data.get('playback', {})
        logger.info("Playback started", playback_id=playback.get('id'), channel_id=playback.get('target_uri'))

    async def _handle_playback_finished(self, event_data: dict):
        playback = event_data.get('playback', {})
        logger.info("Playback finished", playback_id=playback.get('id'), channel_id=playback.get('target_uri'))

    async def _handle_channel_state_change(self, event_data: dict):
        channel = event_data.get('channel', {})
        logger.debug("Channel state changed", channel_id=channel.get('id'), state=channel.get('state'))

    async def _generate_ai_response(self, channel_id: str, call_id: str):
        """Generate a basic AI response for the call."""
        try:
            # For now, just play a simple greeting message
            greeting_text = "Hello, I am an AI Assistant for Jugaar LLC. How can I help you today?"
            logger.info("Generating AI response", channel_id=channel_id, call_id=call_id)
            
            # Use a simple sound file for testing
            await self.ari_client.play_media(channel_id, "sound:1-yes-2-no")
            
            # Publish a message to trigger LLM processing
            llm_message = {
                'channel_id': channel_id,
                'call_id': call_id,
                'action': 'generate_response',
                'text': greeting_text
            }
            # Use Redis client directly for raw dict messages
            await self.redis_queue.redis.publish('llm:response:ready', json.dumps(llm_message))
            logger.info("Published LLM message", channel_id=channel_id)
            
        except Exception as e:
            logger.error("Error generating AI response", channel_id=channel_id, exc_info=True)

async def main():
    service = CallControllerService()

    # Create a future that will complete upon receiving a shutdown signal
    shutdown_event = asyncio.Event()

    def _signal_handler(*args):
        logger.info("Shutdown signal received.")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    service_task = loop.create_task(service.start())

    # Wait until the shutdown signal is received
    await shutdown_event.wait()

    # Once signal is received, gracefully stop the service
    logger.info("Gracefully stopping service...")
    await service.stop()
    service_task.cancel()
    try:
        await service_task
    except asyncio.CancelledError:
        logger.info("Service task cancelled.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Call controller service has shut down.")
