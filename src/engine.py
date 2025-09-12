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
                elif name == "deepgram":
                    # Initialize other providers here
                    pass
                logger.info(f"Provider '{name}' loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load provider '{name}'", exc_info=True)

    async def _handle_stasis_start(self, event: dict):
        """Handle a new call entering the Stasis application."""
        channel_id = event["channel"]["id"]
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

            # This now uses externalMedia and bridging
            media_channel_id = await self.ari_client.start_audio_streaming(
                channel_id, self.config.asterisk.app_name
            )
            
            if not media_channel_id:
                logger.error("Failed to start audio streaming", channel_id=channel_id)
                await self._cleanup_call(channel_id)
                return

            # Store media channel info for cleanup
            self.active_calls[channel_id]["media_channel_id"] = media_channel_id

            # Start the provider's session, which sets up audio handlers
            await provider.start_session(channel_id)
            
            # Play initial greeting now that models are pre-loaded
            await provider.play_initial_greeting(channel_id)

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
                return
                
            call_data = self.active_calls.get(active_channel_id)
            if not call_data:
                return
                
            provider = call_data.get('provider')
            if not provider:
                return

            # Phase A: feed STT via in-memory pipeline (Vosk+VAD)
            # if self.pipeline: # This line is removed as per the edit hint
            #     transcript = await self.pipeline.process_stt(audio_data) # This line is removed as per the edit hint
            #     if transcript: # This line is removed as per the edit hint
            #         logger.info("Transcript", text=transcript) # This line is removed as per the edit hint
            #         # Use existing provider path to generate LLM response and TTS # This line is removed as per the edit hint
            #         await provider._generate_llm_response(transcript)  # uses current TTS AgentAudio events # This line is removed as per the edit hint
            # else: # This line is removed as per the edit hint
            #     # Fallback to legacy provider STT if pipeline not available # This line is removed as per the edit hint
            #     await provider.send_audio(audio_data) # This line is removed as per the edit hint
            #     logger.debug(f"Forwarded {len(audio_data)} bytes of audio to provider") # This line is removed as per the edit hint
            
        except Exception as e:
            logger.error("Error processing audio frame", error=str(e))

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
                    await self._play_audio_to_channel(channel_id, audio_data)
                    logger.debug(f"Sent {len(audio_data)} bytes of ulaw audio to channel {channel_id}")
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
            provider = self.active_calls[channel_id].get("provider")
            if provider:
                await provider.stop_session()
            
            await self.ari_client.stop_audio_streaming(channel_id)
            
            del self.active_calls[channel_id]
            logger.debug("Call resources cleaned up", channel_id=channel_id)
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
