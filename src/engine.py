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
    def __init__(self, config: AppConfig):
        self.config = config
        self.ari_client = ARIClient(
            username=config.asterisk.username,
            password=config.asterisk.password,
            base_url=f"http://{config.asterisk.host}:{config.asterisk.port}/ari",
            app_name=config.asterisk.app_name
        )
        self.active_calls: Dict[str, Dict[str, Any]] = {}
        # Audio buffering for better playback quality
        self.audio_buffers: Dict[str, bytes] = {}
        self.buffer_size = 1600  # 200ms of audio at 8kHz (1600 bytes of ulaw)

        self.setup_event_handlers()

    def setup_event_handlers(self):
        self.ari_client.on_event('StasisStart', self._handle_stasis_start)
        self.ari_client.on_event('StasisEnd', self._handle_stasis_end)
        self.ari_client.on_event('ChannelDtmfReceived', self._handle_dtmf_received)
        self.ari_client.on_event('ChannelAudioFrame', self._handle_audio_frame)

    async def start(self):
        await self.ari_client.connect()
        await self.ari_client.start_listening()

    async def stop(self):
        for channel_id in list(self.active_calls.keys()):
            await self._cleanup_call(channel_id)
        if self.ari_client:
            await self.ari_client.disconnect()

    async def _handle_stasis_start(self, event_data: dict):
        channel = event_data.get('channel', {})
        channel_id = channel.get('id')
        if not channel_id:
            return

        if not (channel.get('name', '').startswith("SIP/") or channel.get('name', '').startswith("PJSIP/") or channel.get('name', '').startswith("Local/")):
            return

        logger.info("New call received", channel_id=channel_id, caller=channel.get('caller'))
        
        args = event_data.get('args', [])
        provider_name = args[0] if args else self.config.default_provider
        
        try:
            provider_config_data = self.config.providers.get(provider_name)
            if not provider_config_data:
                raise ValueError(f"Provider '{provider_name}' not found in configuration.")
            provider = self._create_provider(provider_name, provider_config_data)
        except (KeyError, ValueError) as e:
            logger.error(f"Failed to create provider: {e}")
            await self.ari_client.hangup_channel(channel_id)
            return

        try:
            # Answer the call immediately to prevent timeout
            await self.ari_client.answer_channel(channel_id)

            # Start audio streaming using snoop channel
            snoop_channel_id = await self.ari_client.start_audio_streaming(
                channel_id, 
                self.config.asterisk.app_name
            )
            
            if not snoop_channel_id:
                logger.error("Failed to start audio streaming", channel_id=channel_id)
                await self._cleanup_call(channel_id)
                return

            # Set up audio frame handler for this call
            self.ari_client.set_audio_frame_handler(self._handle_audio_frame)

            self.active_calls[channel_id] = {
                "provider": provider,
                "snoop_channel_id": snoop_channel_id,
                "models_ready": False
            }
            
            # Handle different providers
            if provider_name == "local":
                # For local provider, start ring tone and load models in background
                logger.info("Starting ring tone for local provider", channel_id=channel_id)
                ring_task = asyncio.create_task(self._play_ring_tone(channel_id, duration=15.0))
                
                # Load models in background
                model_task = asyncio.create_task(self._load_local_models(provider, channel_id))
                
                # Wait for models to be ready
                models_ready = await model_task
                if models_ready:
                    # Wait for all models to actually be loaded and ready
                    await self._wait_for_models_ready(provider, channel_id, timeout=15.0)
                    self.active_calls[channel_id]['models_ready'] = True
                    
                    # Cancel ring tone and wait for it to finish
                    ring_task.cancel()
                    try:
                        await ring_task
                    except asyncio.CancelledError:
                        pass
                    
                    # Wait a moment to ensure ring tone has stopped
                    await asyncio.sleep(0.1)
                    
                    # Now speak the greeting
                    if hasattr(provider, 'speak'):
                        await provider.speak(self.config.llm.initial_greeting)
                else:
                    # Models failed to load, hang up
                    logger.error("Failed to load local models", channel_id=channel_id)
                    await self._cleanup_call(channel_id)
                    
            else:
                # For Deepgram, start session immediately (no ring needed)
                await provider.start_session("", self.config.llm.prompt)
                
                # Speak the greeting
                if hasattr(provider, 'speak'):
                    await provider.speak(self.config.llm.initial_greeting)

        except Exception as e:
            logger.error("Error handling StasisStart", channel_id=channel_id, exc_info=True)
            await self._cleanup_call(channel_id)

    async def _load_local_models(self, provider, channel_id: str):
        """Load local models and return True when ready."""
        try:
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
                
            # Send raw audio data to provider for processing
            await provider.send_audio(audio_data)
            logger.debug(f"Forwarded {len(audio_data)} bytes of audio to provider")
            
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
        """Play audio data using file playback approach."""
        try:
            call_info = self.active_calls.get(channel_id)
            if not call_info:
                logger.error(f"No call info found for {channel_id}")
                return
                
            # Add audio data to buffer
            if channel_id not in self.audio_buffers:
                self.audio_buffers[channel_id] = b""
                
            self.audio_buffers[channel_id] += audio_data
            
            # If buffer is full enough, flush it
            if len(self.audio_buffers[channel_id]) >= self.buffer_size:
                await self._flush_audio_buffer(channel_id)
                
        except Exception as e:
            logger.error(f"Error playing audio for channel {channel_id}: {e}")

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
        channel_id = event_data.get('channel', {}).get('id')
        await self._cleanup_call(channel_id)

    async def _cleanup_call(self, channel_id: str):
        call_info = self.active_calls.pop(channel_id, None)
        if not call_info:
            return
        
        # Flush any remaining audio in the buffer
        if channel_id in self.audio_buffers and self.audio_buffers[channel_id]:
            await self._flush_audio_buffer(channel_id)
        
        # Clean up audio buffer
        self.audio_buffers.pop(channel_id, None)
        
        provider = call_info.get('provider')
        if provider:
            await provider.stop_session()

        # Stop audio streaming (this will clean up the snoop channel)
        await self.ari_client.stop_audio_streaming(channel_id)
        
        # Hang up the main channel
        await self.ari_client.hangup_channel(channel_id)

    async def _play_ring_tone(self, channel_id: str, duration: float = 10.0):
        """Play ring tone while models are loading using ARI play_media."""
        call_data = self.active_calls.get(channel_id)
        if not call_data:
            return
            
        logger.info("Starting ring tone", channel_id=channel_id, duration=duration)
        
        # Use Asterisk's built-in ring tone
        try:
            # Play a ring tone using Asterisk's built-in sounds
            await self.ari_client.play_media(channel_id, "tone:ring")
            
            # Wait for the duration or until models are ready
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) < duration:
                # Check if models are ready
                if call_data.get('models_ready', False):
                    logger.info("Models ready, stopping ring tone", channel_id=channel_id)
                    break
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            logger.info("Ring tone cancelled", channel_id=channel_id)
        except Exception as e:
            logger.error("Error playing ring tone", channel_id=channel_id, error=str(e))

    async def _wait_for_models_ready(self, provider, channel_id: str, timeout: float = 15.0):
        """Wait for local models to be ready."""
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if hasattr(provider, 'is_ready') and provider.is_ready():
                logger.info("Local models ready", channel_id=channel_id)
                return True
            await asyncio.sleep(0.1)
            
        logger.warning("Models not ready within timeout", channel_id=channel_id, timeout=timeout)
        return False

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
