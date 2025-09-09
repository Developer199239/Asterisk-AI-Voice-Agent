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
import random
import struct
import os
from typing import Any, Callable, Coroutine, Dict, List

import aiohttp
import asyncio
from aiohttp import web
from shared.config import CallControllerConfig, load_config
from shared.logging_config import get_logger, configure_logging
from shared.redis_client import RedisMessageQueue, CallControlMessage, CallNewMessage, Channels
from services.call_controller.ari_client import ARIClient
from shared.udp_server import UDPServer
from services.call_controller.deepgram_agent_client import DeepgramAgentClient

logger = get_logger(__name__)

# --- RTP Packetizer ---
class RTPPacketizer:
    def __init__(self, ssrc):
        self.sequence_number = random.randint(0, 65535)
        self.timestamp = random.randint(0, 4294967295)
        self.ssrc = ssrc
        logger.debug(f"RTP Packetizer initialized.", initial_seq=self.sequence_number, initial_ts=self.timestamp, ssrc=self.ssrc)

    def packetize(self, payload: bytes) -> bytes:
        header = struct.pack('!BBHII',
            0b10000000,  # Version 2, no padding, no extension, no CSRC
            96,          # Payload Type 96 (Dynamic for slin16)
            self.sequence_number,
            self.timestamp,
            self.ssrc
        )
        self.sequence_number = (self.sequence_number + 1) % 65536
        # slin16 is 2 bytes per sample. Timestamp increases by number of samples.
        self.timestamp = (self.timestamp + len(payload) // 2) % 4294967296
        return header + payload

class CallControllerService:
    def __init__(self, config: CallControllerConfig):
        self.config = config
        self.ari_client = ARIClient(
            self.config.asterisk.username,
            self.config.asterisk.password,
            f"http://{self.config.asterisk.host}:{self.config.asterisk.asterisk_port}/ari",
            self.config.asterisk.app_name
        )
        # self.rtpengine_client = RTPEngineClient(self.config.rtpengine) # No longer needed
        self.redis_queue = RedisMessageQueue(self.config.redis)
        self.active_calls: Dict[str, Dict[str, Any]] = {}
        self.running = False
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.setup_event_handlers()
        self.udp_server = UDPServer(self._forward_audio_to_agent)
        self.http_server_task = None

    def setup_event_handlers(self):
        self.ari_client.on_event('StasisStart', self._handle_stasis_start)
        self.ari_client.on_event('StasisEnd', self._handle_stasis_end)
        self.ari_client.on_event('ChannelDtmfReceived', self._handle_dtmf_received)
        self.ari_client.on_event('PlaybackStarted', self._handle_playback_started)
        self.ari_client.on_event('PlaybackFinished', self._handle_playback_finished)
        self.ari_client.on_event('ChannelStateChange', self._handle_channel_state_change)
        # self.udp_server = UDPServer('0.0.0.0', 54321) # This line is moved to __init__

    async def _cleanup_stale_resources(self):
        """Find and clean up any channels or bridges left over from previous runs."""
        logger.info("Cleaning up stale ARI resources...")
        try:
            app_name = self.config.asterisk.app_name
            
            # Use the ARI endpoint to get subscriptions for our app specifically
            app_details = await self.ari_client.get_app(app_name)
            if not app_details:
                logger.warning("Could not get details for ARI application", app_name=app_name)
                return

            stale_channel_ids = app_details.get('channel_ids', [])
            stale_bridge_ids = app_details.get('bridge_ids', [])

            # First, hang up all stale channels.
            for channel_id in stale_channel_ids:
                logger.info("Hanging up stale channel", channel_id=channel_id)
                try:
                    await self.ari_client.hangup_channel(channel_id)
                except Exception as e:
                    logger.warning("Could not hang up stale channel", channel_id=channel_id, error=e)
            
            # Give a moment for channels to hang up before destroying bridges
            await asyncio.sleep(1)

            # Then, destroy all stale bridges.
            for bridge_id in stale_bridge_ids:
                logger.info("Destroying stale bridge", bridge_id=bridge_id)
                try:
                    await self.ari_client.destroy_bridge(bridge_id)
                except Exception as e:
                    logger.warning("Could not destroy stale bridge", bridge_id=bridge_id, error=e)

            logger.info("Finished cleaning up stale resources.")
        except Exception as e:
            logger.error("Error during stale resource cleanup", exc_info=True)

    async def start(self):
        logger.info(f"Starting service {self.config.service_name}")
        await self.redis_queue.connect()
        # await self.rtpengine_client.connect() # No longer needed
        await self.ari_client.connect()
        
        # Clean up any leftover resources from a previous run
        await self._cleanup_stale_resources()

        # Start UDP server in a background task
        # The UDPServer now needs the host and port to be explicitly passed to its start method.
        # We'll use a dynamic port to avoid conflicts.
        # Let's define host and port here for clarity.
        udp_host = "0.0.0.0"
        udp_port = 0 # 0 means the OS will pick an available port
        self.udp_server_task = asyncio.create_task(self.udp_server.start(udp_host, udp_port))


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

        # This is the fix for the recursive loop. We only handle SIP/PJSIP channels.
        if not (channel.get('name', '').startswith("SIP/") or channel.get('name', '').startswith("PJSIP/")):
            logger.debug("Ignoring non-SIP/PJSIP channel", channel_name=channel.get('name'))
            return

        logger.info("New call received", channel_id=channel_id, caller=channel.get('caller'))
        
        call_id = f"call-{uuid.uuid4()}"
        
        try:
            # Answer the incoming channel first
            await self.ari_client.answer_channel(channel_id)
            logger.info("Channel answered", channel_id=channel_id)

            # Store preliminary call state
            self.active_calls[channel_id] = {
                "call_id": call_id,
                "channel_data": channel,
                "agent_client": None,
                "media_channel_id": None,
                "bridge_id": None,
                "rtp_packetizer": RTPPacketizer(ssrc=random.randint(0, 4294967295)) # Create packetizer per call
            }

            # Set up and start the Deepgram Agent client
            agent_client = DeepgramAgentClient(self._handle_deepgram_event)
            await agent_client.connect(self.config.deepgram, self.config.llm)
            self.active_calls[channel_id]['agent_client'] = agent_client
            logger.info("Deepgram Agent client connected", call_id=call_id)

            # Create the externalMedia channel for two-way audio
            logger.info("Creating externalMedia channel...")
            media_channel_response = await self.ari_client.create_external_media_channel(
                app_name=self.config.asterisk.app_name,
                # With host networking, we can use localhost to communicate with Asterisk
                external_host=f"127.0.0.1:{self.udp_server.port}",
                format="slin16"
            )
            # The response body *is* the channel object, not nested under a 'channel' key.
            if not media_channel_response or 'id' not in media_channel_response:
                raise Exception(f"Failed to create externalMedia channel. Response: {media_channel_response}")
            
            media_channel_id = media_channel_response['id']
            self.active_calls[channel_id]['media_channel_id'] = media_channel_id
            
            # NETWORKING FIX: With host networking, Asterisk's local RTP port is on localhost.
            asterisk_rtp_host = "127.0.0.1"
            asterisk_rtp_port = int(media_channel_response["channelvars"]["UNICASTRTP_LOCAL_PORT"])
            self.active_calls[channel_id]['asterisk_rtp_addr'] = (asterisk_rtp_host, asterisk_rtp_port)

            logger.info(
                "externalMedia channel created",
                media_channel_id=media_channel_id,
                rtp_addr=self.active_calls[channel_id]['asterisk_rtp_addr']
            )

            # Reverse lookup for cleanup
            self.active_calls[media_channel_id] = self.active_calls[channel_id]

            # Bridge the incoming call with the media channel
            bridge = await self.ari_client.create_bridge()
            bridge_id = bridge['id']
            self.active_calls[channel_id]['bridge_id'] = bridge_id
            
            await self.ari_client.add_channel_to_bridge(bridge_id, channel_id)
            await self.ari_client.add_channel_to_bridge(bridge_id, media_channel_id)
            logger.info("Incoming call and media channel bridged", bridge_id=bridge_id)

        except Exception as e:
            logger.error("Error handling StasisStart", channel_id=channel_id, exc_info=True)
            await self._cleanup_call(channel_id)

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
            # This event now contains the audio payload to be played back.
            audio_payload_b64 = event.get("data")
            if audio_payload_b64:
                await self._play_deepgram_audio(channel_id, audio_payload_b64)

        elif event_type == "UserStartedSpeaking":
            logger.debug("Handling UserStartedSpeaking event")
            # This event now contains the audio payload to be played back.
            audio_payload_b64 = event.get("payload")
            if audio_payload_b64:
                await self._play_deepgram_audio(channel_id, audio_payload_b64)

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

    async def _play_deepgram_audio(self, channel_id: str, audio_payload_b64: str):
        call_info = self.active_calls.get(channel_id)
        if not call_info:
            logger.warning("Could not find call info to play audio for channel", channel_id=channel_id)
            return

        rtp_packetizer = call_info.get('rtp_packetizer')
        asterisk_addr = call_info.get('asterisk_rtp_addr')

        if not rtp_packetizer or not asterisk_addr:
            logger.warning("Missing RTP packetizer or Asterisk address for call", call_id=call_info.get('call_id'))
            return

        try:
            audio_payload = base64.b64decode(audio_payload_b64)
            logger.debug("Received audio from Deepgram", payload_size=len(audio_payload), call_id=call_info.get('call_id'))

            # Deepgram sends audio in chunks. A common size is 640 bytes for 20ms of L16 audio.
            # We will packetize and send it as is.
            rtp_packet = rtp_packetizer.packetize(audio_payload)
            
            logger.debug("Sending RTP packet to Asterisk",
                         addr=asterisk_addr,
                         seq=rtp_packetizer.sequence_number,
                         ts=rtp_packetizer.timestamp,
                         ssrc=rtp_packetizer.ssrc,
                         size=len(rtp_packet))
                         
            await self.udp_server.send(rtp_packet, asterisk_addr)

        except Exception as e:
            logger.error("Failed to process and send audio to Asterisk", error=e, call_id=call_info.get('call_id'))


async def main():
    logger.info("Starting Call Controller Service")
    configure_logging(log_level=os.getenv("LOG_LEVEL", "DEBUG"))
    config = load_config('call_controller')
    service = CallControllerService(config)

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
