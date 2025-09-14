import asyncio
import os
import random
import signal
import struct
import uuid
import audioop
import base64
from typing import Dict, Any

from .ari_client import ARIClient
from .config import AppConfig, load_config, DeepgramProviderConfig, LocalProviderConfig
from .logging_config import get_logger, configure_logging
from .providers.base import AIProviderInterface
from .providers.deepgram import DeepgramProvider
from .providers.local import LocalProvider

logger = get_logger(__name__)


class Engine:
    """The main application engine."""

    def __init__(self, config: AppConfig):
        self.config = config
        base_url = f"http://{config.asterisk.host}:{config.asterisk.port}/ari"
        self.ari_client = ARIClient(
            username=config.asterisk.username,
            password=config.asterisk.password,
            base_url=base_url,
            app_name=config.asterisk.app_name
        )
        self.providers: Dict[str, AIProviderInterface] = {}
        self.active_calls: Dict[str, Dict[str, Any]] = {}
        # Audio buffering for better playback quality
        self.audio_buffers: Dict[str, bytes] = {}
        self.buffer_size = 1600  # 200ms of audio at 8kHz (1600 bytes of ulaw)

        # Event handlers
        self.ari_client.on_event("StasisStart", self._handle_stasis_start)
        self.ari_client.on_event("StasisEnd", self._handle_stasis_end)
        self.ari_client.on_event("ChannelDtmfReceived", self._handle_dtmf_received)

    async def on_rtp_packet(self, packet: bytes, addr: tuple):
        """Handle incoming RTP packets from the UDP server."""
        # This is a simplified handler. A real implementation would parse RTP headers
        # to map the audio to the correct call based on SSRC or other identifiers.
        # For now, we assume a single active call and forward audio to its provider.
        if self.active_calls:
            channel_id = list(self.active_calls.keys())[0]
            call_data = self.active_calls[channel_id]
            provider = call_data.get("provider")
            if provider:
                # The first 12 bytes of an RTP packet are the header. The rest is payload.
                audio_payload = packet[12:]
                await provider.send_audio(audio_payload)

    async def _on_ari_event(self, event: Dict[str, Any]):
        """Default event handler for unhandled ARI events."""
        logger.debug("Received unhandled ARI event", event_type=event.get("type"), event=event)

    async def start(self):
        """Connect to ARI and start the engine."""
        await self._load_providers()
        await self.ari_client.connect()
        asyncio.create_task(self.ari_client.start_listening())
        logger.info("Engine started and listening for calls.")

    async def stop(self):
        """Disconnect from ARI and stop the engine."""
        for channel_id in list(self.active_calls.keys()):
            await self._cleanup_call(channel_id)
        await self.ari_client.disconnect()
        # if self.pipeline: # This line is removed as per the edit hint
        #     await self.pipeline.stop()
        logger.info("Engine stopped.")

    async def _load_providers(self):
        """Load and initialize AI providers from the configuration."""
        logger.info("Loading AI providers...")
        for name, provider_config_data in self.config.providers.items():
            try:
                if name == "local":
                    config = LocalProviderConfig(**provider_config_data)
                    provider = LocalProvider(config, self.on_provider_event)
                    self.providers[name] = provider
                    logger.info(f"Provider '{name}' loaded successfully.")
                elif name == "deepgram":
                    # Deepgram provider requires both Deepgram and OpenAI API keys
                    deepgram_config = DeepgramProviderConfig(**provider_config_data)
                    
                    # Validate OpenAI dependency for Deepgram
                    if not self.config.llm.api_key:
                        logger.error(f"Deepgram provider requires OpenAI API key in LLM config")
                        continue
                    
                    provider = DeepgramProvider(deepgram_config, self.config.llm, self.on_provider_event)
                    self.providers[name] = provider
                    logger.info(f"Provider '{name}' loaded successfully with OpenAI LLM dependency.")
                else:
                    logger.warning(f"Unknown provider type: {name}")
                    continue
                    
            except Exception as e:
                logger.error(f"Failed to load provider '{name}': {e}", exc_info=True)
        
        # Validate that default provider is available
        if self.config.default_provider not in self.providers:
            available_providers = list(self.providers.keys())
            logger.error(f"Default provider '{self.config.default_provider}' not available. Available providers: {available_providers}")
        else:
            logger.info(f"Default provider '{self.config.default_provider}' is available and ready.")

    async def _handle_stasis_start(self, event: dict):
        """Handle a new call entering the Stasis application."""
        # Debug: Log the full event structure
        logger.debug("StasisStart event received", event_data=event)
        
        channel_id = event["channel"]["id"]
        channel_name = event["channel"]["name"]
        
        # CRITICAL: Ignore snoop channels to prevent infinite loops
        if channel_name.startswith("Snoop/"):
            logger.debug("Ignoring snoop channel", channel_id=channel_id, channel_name=channel_name)
            return
            
        caller_info = event["channel"]["caller"]
        logger.info(
            "New call received",
            channel_id=channel_id,
            caller={"name": caller_info["name"], "number": caller_info["number"]},
        )
        
        args = event.get('args', [])
        provider_name = args[0] if args else self.config.default_provider
        provider = self.providers.get(provider_name)

        if not provider:
            logger.error(f"Provider '{provider_name}' not found for channel {channel_id}.")
            await self.ari_client.hangup_channel(channel_id)
            return

        self.active_calls[channel_id] = {"provider": provider}
        
        try:
            await self.ari_client.answer_channel(channel_id)

            # PROVEN ARCHITECTURE: Create snoop channel for audio capture
            snoop_id = await self.ari_client.start_audio_snoop(channel_id, self.config.asterisk.app_name)
            
            if not snoop_id:
                logger.error("Failed to create snoop channel", channel_id=channel_id)
                await self._cleanup_call(channel_id)
                return

            # Store snoop channel info for cleanup
            self.active_calls[channel_id]["snoop_channel_id"] = snoop_id

            # CRITICAL: Create mixing bridge and add BOTH channels (architect's solution)
            bridge_id = await self.ari_client.create_bridge("mixing")
            if bridge_id:
                # Add both the main channel and snoop channel to the bridge
                logger.info("Adding main channel to bridge", channel_id=channel_id, bridge_id=bridge_id)
                await self.ari_client.add_channel_to_bridge(bridge_id, channel_id)
                
                logger.info("Adding snoop channel to bridge", snoop_id=snoop_id, bridge_id=bridge_id)
                await self.ari_client.add_channel_to_bridge(bridge_id, snoop_id)
                
                # Store bridge info for cleanup
                self.active_calls[channel_id]["bridge_id"] = bridge_id
                
                # Small delay to ensure bridge is fully established
                await asyncio.sleep(0.1)
                
                logger.info("✅ Bridge created and both channels added successfully", 
                          channel_id=channel_id, 
                          snoop_id=snoop_id, 
                          bridge_id=bridge_id)
            else:
                logger.error("Failed to create bridge", channel_id=channel_id)
                await self._cleanup_call(channel_id)
                return

            # Set up audio frame handler for this call (after bridge is established)
            self.ari_client.set_audio_frame_handler(self._handle_audio_frame)
            logger.debug("Audio frame handler set after bridge establishment", channel_id=channel_id)

            # Start the provider's session, which sets up audio handlers
            logger.debug("Starting provider session", channel_id=channel_id, provider=provider_name)
            await provider.start_session(channel_id)
            logger.debug("Provider session started successfully", channel_id=channel_id)
            
            # Play initial greeting now that models are pre-loaded
            if hasattr(provider, 'play_initial_greeting'):
                logger.debug("Playing initial greeting", channel_id=channel_id)
                await provider.play_initial_greeting(channel_id)
                logger.debug("Initial greeting played", channel_id=channel_id)
            else:
                logger.debug("Provider does not have play_initial_greeting method", channel_id=channel_id)

        except Exception as e:
            logger.error("Error during StasisStart handling", channel_id=channel_id, exc_info=True)
            await self._cleanup_call(channel_id)

    async def _load_local_models(self, provider, channel_id: str):
        """Load local models and return True when ready."""
        try:
            # Models should already be pre-loaded, just start the session
            await provider.start_session("", self.config.llm.prompt)
            return True
        except Exception as e:
            logger.error("Failed to load local models", channel_id=channel_id, error=str(e))
            return False

    def _create_provider(self, provider_name: str, provider_config_data: Any) -> AIProviderInterface:
        logger.debug(f"Creating provider: {provider_name}")
        
        provider_map = {
            "deepgram": DeepgramProvider,
            "local": LocalProvider
        }

        provider_class = provider_map.get(provider_name)
        
        if not provider_class:
            raise ValueError(f"Unknown provider: {provider_name}")

        # Each provider might have a different constructor signature.
        # We handle that here.
        if provider_name == "deepgram":
            provider_config = DeepgramProviderConfig(**provider_config_data)
            return DeepgramProvider(provider_config, self.config.llm, self.on_provider_event)
        elif provider_name == "local":
            provider_config = LocalProviderConfig(**provider_config_data)
            return LocalProvider(provider_config, self.on_provider_event)

        raise ValueError(f"Provider '{provider_name}' does not have a creation rule.")

    async def _handle_audio_frame(self, audio_data: bytes):
        """Handle raw audio frames from snoop channels."""
        try:
            # Find the active call (assuming single call for now)
            # In a multi-call scenario, we'd need to track which snoop belongs to which call
            active_channel_id = None
            for channel_id, call_data in self.active_calls.items():
                if call_data.get('snoop_channel_id'):
                    active_channel_id = channel_id
                    break
                    
            if not active_channel_id:
                logger.warning("No active call found for audio frame")
                return
                
            call_data = self.active_calls.get(active_channel_id)
            if not call_data:
                logger.debug("No call data found for active channel")
                return
                
            provider = call_data.get('provider')
            if not provider:
                logger.debug("No provider found for active call")
                return

            # Forward audio data to the provider for STT processing
            await provider.send_audio(audio_data)
            logger.debug(f"Forwarded {len(audio_data)} bytes of audio to provider for channel {active_channel_id}")
            
        except Exception as e:
            logger.error("Error processing audio frame", error=str(e), exc_info=True)

    async def _handle_dtmf_received(self, event_data: dict):
        """Handle DTMF events from snoop channels."""
        channel = event_data.get('channel', {})
        channel_id = channel.get('id')
        digit = event_data.get('digit')
        
        # Find the main channel this snoop belongs to
        main_channel_id = None
        for main_id, call_data in self.active_calls.items():
            if call_data.get('snoop_channel_id') == channel_id:
                main_channel_id = main_id
                break
                
        if main_channel_id and digit:
            logger.info(f"DTMF received: {digit}", channel_id=main_channel_id)
            # Forward DTMF to provider if it supports it
            call_data = self.active_calls.get(main_channel_id)
            if call_data:
                provider = call_data.get('provider')
                if provider and hasattr(provider, 'handle_dtmf'):
                    await provider.handle_dtmf(digit)

    async def on_provider_event(self, event: Dict[str, Any]):
        """Callback for providers to send events back to the engine."""
        event_type = event.get("type")
        
        if event_type == "AgentAudio":
            # Handle audio data from the provider - now we need to play it back
            audio_data = event.get("data")
            if audio_data:
                # For now, we'll send to all active calls
                # In a more sophisticated implementation, we'd track which call this audio belongs to
                for channel_id, call_data in self.active_calls.items():
                    # Play audio on the main call channel, not the snoop channel
                    # The snoop channel is for receiving audio, the main channel is for playing audio
                    await self.ari_client.play_audio_response(channel_id, audio_data)
                    logger.debug(f"Sent {len(audio_data)} bytes of audio to call channel {channel_id}")
        elif event_type == "Transcription":
            # Handle transcription data
            text = event.get("text", "")
            logger.info(f"Transcription: {text}")
        else:
            logger.debug(f"Unhandled provider event: {event_type}")

    async def _play_audio_to_channel(self, channel_id: str, audio_data: bytes):
        """Convert audio data to a temp WAV file and play it to the channel."""
        if not audio_data:
            logger.warning("No audio data to play.", channel_id=channel_id)
            return

        try:
            # Create a temporary WAV file from the raw audio data (assuming it's ulaw)
            temp_file_path = await self.ari_client.create_audio_file_from_ulaw(audio_data)

            if temp_file_path:
                await self.ari_client.play_audio_file(channel_id, temp_file_path)
                # Schedule cleanup of the temp file
                asyncio.create_task(self.ari_client.cleanup_audio_file(temp_file_path, delay=2.0))
        except Exception as e:
            logger.error("Failed to play audio to channel", channel_id=channel_id, exc_info=True)

    async def _flush_audio_buffer(self, channel_id: str):
        """Flush the audio buffer and play the accumulated audio."""
        try:
            if channel_id not in self.audio_buffers or not self.audio_buffers[channel_id]:
                return
                
            audio_data = self.audio_buffers[channel_id]
            buffer_size = len(audio_data)
            self.audio_buffers[channel_id] = b""
            
            logger.debug(f"Flushing audio buffer for channel {channel_id}: {buffer_size} bytes")
            
            # Create WAV file from ulaw data
            wav_file_path = await self.ari_client.create_audio_file_from_ulaw(audio_data)
            
            if wav_file_path:
                # Set additional channel variables for debugging
                await self.ari_client.send_command(
                    "POST",
                    f"channels/{channel_id}/variable",
                    data={"variable": "AUDIO_BUFFER_SIZE", "value": str(buffer_size)}
                )
                
                # Play the WAV file
                success = await self.ari_client.play_audio_file(channel_id, wav_file_path)
                
                if success:
                    # Schedule cleanup of the audio file - TEMPORARILY DISABLED FOR TESTING
                    # asyncio.create_task(self.ari_client.cleanup_audio_file(wav_file_path))
                    logger.info(f"Audio file created and played successfully: {wav_file_path} (buffer: {buffer_size} bytes)")
                else:
                    # Clean up immediately if playback failed - TEMPORARILY DISABLED FOR TESTING
                    # await self.ari_client.cleanup_audio_file(wav_file_path, delay=0)
                    logger.error(f"Audio playback failed, but keeping file for debugging: {wav_file_path} (buffer: {buffer_size} bytes)")
            else:
                logger.error(f"Failed to create WAV file from {buffer_size} bytes of audio data")
                    
        except Exception as e:
            logger.error(f"Error flushing audio buffer for channel {channel_id}: {e}")

    async def _handle_stasis_end(self, event_data: dict):
        """Handle a call leaving the Stasis application."""
        channel_id = event_data.get('channel', {}).get('id')
        await self._cleanup_call(channel_id)

    async def _cleanup_call(self, channel_id: str):
        """Cleanup resources associated with a call."""
        if channel_id in self.active_calls:
            call_data = self.active_calls[channel_id]
            provider = call_data.get("provider")
            if provider:
                await provider.stop_session()
            
            # Stop snoop channel
            await self.ari_client.stop_audio_snoop(channel_id)
            
            # Clean up bridge if it exists
            bridge_id = call_data.get("bridge_id")
            if bridge_id:
                try:
                    await self.ari_client.send_command("DELETE", f"bridges/{bridge_id}")
                    logger.debug("Bridge destroyed", bridge_id=bridge_id)
                except Exception as e:
                    logger.warning("Failed to destroy bridge", bridge_id=bridge_id, error=str(e))
            
            # Clean up any remaining audio files for this call
            await self.ari_client.cleanup_call_files(channel_id)
            
            del self.active_calls[channel_id]
            logger.debug("Call resources cleaned up", channel_id=channel_id)
        else:
            # Check if this is a snoop channel trying to clean up
            if channel_id.startswith("snoop_"):
                logger.debug("Snoop channel cleanup attempted for non-active call", channel_id=channel_id)
            else:
                logger.debug("No active call found for cleanup", channel_id=channel_id)

    async def _play_ring_tone(self, channel_id: str, duration: float = 15.0):
        """Play a ringing tone to the channel."""
        logger.info("Starting ring tone", channel_id=channel_id, duration=duration)
        try:
            await self.ari_client.play_media(channel_id, "tone:ring")
            await asyncio.sleep(duration)
        except asyncio.CancelledError:
            logger.info("Ring tone cancelled", channel_id=channel_id)
            # Explicitly stop the playback
            # This requires a playback ID, which complicates things.
            # For now, we rely on hanging up or answering to stop it.
        except Exception as e:
            logger.error("Error playing ring tone", channel_id=channel_id, exc_info=True)


async def main():
    configure_logging(log_level=os.getenv("LOG_LEVEL", "DEBUG"))
    config = load_config()
    engine = Engine(config)

    shutdown_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    service_task = loop.create_task(engine.start())
    await shutdown_event.wait()

    await engine.stop()
    service_task.cancel()
    try:
        await service_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("AI Voice Agent has shut down.")
