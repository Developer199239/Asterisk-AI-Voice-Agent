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
import base64
import wave

from shared.config import load_config
from services.call_controller.ari_client import ARIClient
from shared.redis_client import RedisMessageQueue, CallControlMessage, CallNewMessage, Channels
from services.call_controller.udp_server import UDPServer
from services.call_controller.deepgram_agent_client import DeepgramAgentClient

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
        self.udp_server = UDPServer('0.0.0.0', 54322, self._forward_audio_to_agent)

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
        incoming_channel_id = channel.get('id')
        if not incoming_channel_id:
            logger.warning("StasisStart event with no channel ID")
            return

        # This is the fix for the recursive loop. We only handle SIP/PJSIP channels.
        if not (channel.get('name', '').startswith("SIP/") or channel.get('name', '').startswith("PJSIP/")):
            logger.debug("Ignoring non-SIP/PJSIP channel", channel_name=channel.get('name'))
            return

        logger.info("New call received", channel_id=incoming_channel_id, caller=channel.get('caller'))
        
        call_id = f"call-{uuid.uuid4()}"
        
        try:
            # Answer the incoming channel first
            await self.ari_client.answer_channel(incoming_channel_id)
            logger.info("Channel answered", channel_id=incoming_channel_id)

            # Store preliminary call state
            self.active_calls[incoming_channel_id] = {
                'channel_data': channel, 
                'state': 'answered',
                'call_id': call_id,
                'request_id': None # We will populate this on Welcome event
            }

            # Set up and start the Deepgram Agent client
            agent_client = DeepgramAgentClient(self._handle_deepgram_event)
            await agent_client.connect(self.config.deepgram, self.config.llm)
            self.active_calls[incoming_channel_id]['agent_client'] = agent_client
            logger.info("Deepgram Agent client connected", call_id=call_id)

            # Create the externalMedia channel for two-way audio
            logger.info("Creating externalMedia channel...")
            media_channel_response = await self.ari_client.create_external_media_channel(
                app_name=self.config.asterisk.app_name,
                external_host=f"{self.udp_server.host}:{self.udp_server.port}"
            )
            # The response body *is* the channel object, not nested under a 'channel' key.
            if not media_channel_response or 'id' not in media_channel_response:
                raise Exception(f"Failed to create externalMedia channel. Response: {media_channel_response}")
            
            media_channel_id = media_channel_response['id']
            self.active_calls[incoming_channel_id]['media_channel_id'] = media_channel_id
            logger.info("externalMedia channel created", media_channel_id=media_channel_id)

            # Add media_channel_id to active_calls for reverse lookup
            self.active_calls[media_channel_id] = self.active_calls[incoming_channel_id]

            # Bridge the incoming call with the media channel
            bridge = await self.ari_client.create_bridge()
            bridge_id = bridge['id']
            self.active_calls[incoming_channel_id]['bridge_id'] = bridge_id
            
            await self.ari_client.add_channel_to_bridge(bridge_id, incoming_channel_id)
            await self.ari_client.add_channel_to_bridge(bridge_id, media_channel_id)
            logger.info("Incoming call and media channel bridged", bridge_id=bridge_id)

        except Exception as e:
            logger.error("Error handling StasisStart", channel_id=incoming_channel_id, exc_info=True)
            await self._cleanup_call(incoming_channel_id)

    async def _handle_stasis_end(self, event_data: dict):
        channel = event_data.get('channel', {})
        channel_id = channel.get('id')
        logger.info("StasisEnd event received for channel", channel_id=channel_id)
        
        # Find the primary call record associated with this channel (either incoming or media)
        call_info = self.active_calls.get(channel_id)
        if call_info:
            primary_channel_id = call_info.get('channel_data', {}).get('id')
            if primary_channel_id:
                await self._cleanup_call(primary_channel_id)
            else:
                logger.warning("Could not determine primary channel ID from StasisEnd event", channel_id=channel_id)
        else:
            logger.warning("Received StasisEnd for a channel not in active_calls", channel_id=channel_id)


    async def _cleanup_call(self, channel_id: str):
        if channel_id in self.active_calls:
            call_info = self.active_calls[channel_id]
            
            # Use a copy of keys to avoid issues with modifying dict during iteration
            active_channel_ids = list(self.active_calls.keys())
            
            # Clean up all related entries from active_calls
            for key_id in active_channel_ids:
                if self.active_calls.get(key_id) == call_info:
                    del self.active_calls[key_id]

            # Hang up the media channel if it exists
            media_channel_id = call_info.get('media_channel_id')
            if media_channel_id:
                logger.info("Hanging up media channel", channel_id=media_channel_id)
                try:
                    await self.ari_client.hangup_channel(media_channel_id)
                except Exception as e:
                    logger.warning("Could not hang up media channel", channel_id=media_channel_id, error=e)

            # Hang up the incoming channel if it exists and is still up
            incoming_channel_id = call_info.get('channel_data', {}).get('id')
            if incoming_channel_id and incoming_channel_id != media_channel_id:
                logger.info("Hanging up incoming channel", channel_id=incoming_channel_id)
                try:
                    await self.ari_client.hangup_channel(incoming_channel_id)
                except Exception as e:
                    logger.warning("Could not hang up incoming channel", channel_id=incoming_channel_id, error=e)

            # Destroy the bridge if it exists
            bridge_id = call_info.get('bridge_id')
            if bridge_id:
                logger.info("Destroying bridge", bridge_id=bridge_id)
                try:
                    await self.ari_client.destroy_bridge(bridge_id)
                except Exception as e:
                    logger.warning("Could not destroy bridge", bridge_id=bridge_id, error=e)

            agent_client = call_info.get('agent_client')
            if agent_client:
                await agent_client.disconnect()
                logger.info("Deepgram Agent client disconnected for call", call_id=call_info.get('call_id'))
            
            logger.info("Cleaned up all resources for call", call_id=call_info.get('call_id'))


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

    async def _handle_deepgram_event(self, event: dict):
        """Handle incoming events from the Deepgram Agent client."""
        logger.info("Received event from Deepgram Agent", dg_event=event)
        event_type = event.get('type')
        request_id = event.get('request_id')

        # Find the channel_id associated with this request_id
        channel_id = None
        call_info_to_update = None
        for cid, info in self.active_calls.items():
            if info.get('request_id') == request_id:
                channel_id = cid
                break
            # If request_id is not yet set, we might be processing the Welcome event
            if info.get('request_id') is None and event_type == 'Welcome':
                channel_id = cid
                call_info_to_update = info
                break
        
        if call_info_to_update and event_type == 'Welcome':
            call_info_to_update['request_id'] = request_id
            logger.info("Associated request_id with channel", request_id=request_id, channel_id=channel_id)


        if not channel_id:
            logger.warning("Could not find channel for request_id", request_id=request_id)
            return

        if event_type == 'AgentAudio':
            audio_data = event.get('data')

            if not audio_data:
                logger.warning("AgentAudio event missing data", event=event)
                return

            try:
                # Decode the base64 audio data
                decoded_audio = base64.b64decode(audio_data)

                # Save the audio to a temporary WAV file
                # Note: This assumes mono, 16-bit PCM at 8000 Hz, which is common for telephony.
                # Deepgram's output format should be verified.
                temp_filename = f"/tmp/agent_audio_{channel_id}_{uuid.uuid4()}.wav"
                with wave.open(temp_filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(8000)
                    wf.writeframes(decoded_audio)

                # Play the audio file on the channel
                await self.ari_client.play_media(channel_id, f"sound:{temp_filename[:-4]}") # ARI needs path without extension
                
            except Exception as e:
                logger.error("Error handling AgentAudio event", exc_info=True)

    async def _forward_audio_to_agent(self, data: bytes, addr: tuple):
        """
        This is the callback for the UDP server. It finds the appropriate
        Deepgram agent client and forwards the audio payload.
        """
        logger.debug("UDP server received a packet", size=len(data), source_addr=addr)
        active_agent_client = None
        # Find the active agent client. This simple approach works for one call at a time.
        # For multi-call, we'd need a way to map UDP source addr to a call.
        for call_info in self.active_calls.values():
            if 'agent_client' in call_info:
                active_agent_client = call_info['agent_client']
                break

        if active_agent_client:
            if len(data) > 12: # Basic RTP header check
                audio_payload = data[12:]
                logger.debug(
                    "Forwarding audio payload to Deepgram agent...",
                    payload_size=len(audio_payload)
                )
                await active_agent_client.send_audio(audio_payload)
            else:
                logger.warning("Received a packet too small to be RTP", size=len(data), source_addr=addr)
        else:
            logger.warning("Received UDP packet but no active agent client", source_addr=addr)


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
