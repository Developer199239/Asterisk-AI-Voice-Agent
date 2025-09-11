import asyncio
import os
import random
import signal
import struct
import uuid
import audioop
from typing import Dict, Any

from .ari_client import ARIClient
from .config import AppConfig, load_config, DeepgramProviderConfig, LocalProviderConfig
from .logging_config import get_logger, configure_logging
from .rtp_handler import RTPPacketizer
from .providers.base import AIProviderInterface
from .providers.deepgram import DeepgramProvider
from .providers.local import LocalProvider
from .udp_server import UDPServer
from .rtp_packet import RtpPacket

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
        self.udp_server = UDPServer(self._forward_audio_to_agent)

        self.setup_event_handlers()

    def setup_event_handlers(self):
        self.ari_client.on_event('StasisStart', self._handle_stasis_start)
        self.ari_client.on_event('StasisEnd', self._handle_stasis_end)

    async def start(self):
        await self.ari_client.connect()
        await self.udp_server.start("127.0.0.1", 0) # Dynamic port
        await self.ari_client.start_listening()

    async def stop(self):
        for channel_id in list(self.active_calls.keys()):
            await self._cleanup_call(channel_id)
        if self.ari_client:
            await self.ari_client.disconnect()
        self.udp_server.stop()

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

            self.active_calls[channel_id] = {
                "provider": provider,
                "rtp_packetizer": RTPPacketizer(ssrc=random.randint(0, 4294967295)),
                "models_ready": False
            }
            
            # Set up media immediately
            preferred_codec = provider.supported_codecs[0]
            media_channel_response = await self.ari_client.create_external_media_channel(
                app_name=self.config.asterisk.app_name,
                external_host=f"127.0.0.1:{self.udp_server.port}",
                format=preferred_codec
            )
            media_channel_id = media_channel_response['id']
            self.active_calls[channel_id]['media_channel_id'] = media_channel_id
            
            asterisk_rtp_addr = ("127.0.0.1", int(media_channel_response["channelvars"]["UNICASTRTP_LOCAL_PORT"]))
            self.active_calls[channel_id]['asterisk_rtp_addr'] = asterisk_rtp_addr
            
            bridge = await self.ari_client.create_bridge()
            bridge_id = bridge['id']
            self.active_calls[channel_id]['bridge_id'] = bridge_id
            
            await self.ari_client.add_channel_to_bridge(bridge_id, channel_id)
            await self.ari_client.add_channel_to_bridge(bridge_id, media_channel_id)
            
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

    async def on_provider_event(self, event: Dict[str, Any]):
        """Callback for providers to send events back to the engine."""
        event_type = event.get("type")
        
        if event_type == "AgentAudio":
            # Handle audio data from the provider
            audio_data = event.get("data")
            if audio_data:
                # Find the active call for this audio
                # For now, we'll send to all active calls
                for channel_id, call_data in self.active_calls.items():
                    if "rtp_packetizer" in call_data and "asterisk_rtp_addr" in call_data:
                        rtp_packetizer = call_data["rtp_packetizer"]
                        asterisk_rtp_addr = call_data["asterisk_rtp_addr"]
                        
                        # Convert ulaw audio to RTP packets and send
                        rtp_packet = rtp_packetizer.packetize(audio_data, payload_type=0)
                        await self.udp_server.send_rtp_packet(rtp_packet, asterisk_rtp_addr)
                        logger.debug(f"Sent {len(audio_data)} bytes of ulaw audio to {asterisk_rtp_addr}")
        elif event_type == "Transcription":
            # Handle transcription data
            text = event.get("text", "")
            logger.info(f"Transcription: {text}")
        else:
            logger.debug(f"Unhandled provider event: {event_type}")

    async def _handle_ai_event(self, event: Dict[str, Any], channel_id: str):
        event_type = event.get("type")
        if event_type == 'AgentAudio':
            audio_payload = event.get("data")
            if audio_payload:
                await self._play_ai_audio(channel_id, audio_payload)

    async def _play_ai_audio(self, channel_id: str, audio_payload: bytes):
        call_info = self.active_calls.get(channel_id)
        if not call_info:
            return

        destination_addr = call_info.get('asterisk_rtp_addr')
        packetizer = call_info.get('rtp_packetizer')

        if not destination_addr or not packetizer:
            return

        chunk_size = 160
        delay = 0.020

        for i in range(0, len(audio_payload), chunk_size):
            chunk = audio_payload[i:i+chunk_size]
            rtp_packet = packetizer.packetize(chunk, payload_type=0)
            self.udp_server.transport.sendto(rtp_packet, destination_addr)
            await asyncio.sleep(delay)

    async def _forward_audio_to_agent(self, data: bytes, addr: tuple):
        call_info = next(iter(self.active_calls.values()), None)
        if not call_info:
            return

        try:
            rtp_packet = RtpPacket.parse(data)
            provider = call_info.get('provider')
            if provider:
                await provider.send_audio(rtp_packet.payload)
        except Exception as e:
            logger.error("Error processing RTP packet", exc_info=True)

    async def _handle_stasis_end(self, event_data: dict):
        channel_id = event_data.get('channel', {}).get('id')
        await self._cleanup_call(channel_id)

    async def _cleanup_call(self, channel_id: str):
        call_info = self.active_calls.pop(channel_id, None)
        if not call_info:
            return
        
        provider = call_info.get('provider')
        if provider:
            await provider.stop_session()

        media_channel_id = call_info.get('media_channel_id')
        if media_channel_id:
            try:
                await self.ari_client.hangup_channel(media_channel_id)
            except Exception: pass

        bridge_id = call_info.get('bridge_id')
        if bridge_id:
            try:
                await self.ari_client.destroy_bridge(bridge_id)
            except Exception: pass

    async def _play_ring_tone(self, channel_id: str, duration: float = 10.0):
        """Play ring tone while models are loading."""
        call_data = self.active_calls.get(channel_id)
        if not call_data:
            return
            
        rtp_packetizer = call_data.get('rtp_packetizer')
        asterisk_rtp_addr = call_data.get('asterisk_rtp_addr')
        
        if not rtp_packetizer or not asterisk_rtp_addr:
            return
            
        logger.info("Starting ring tone", channel_id=channel_id, duration=duration)
        
        # Generate ring tone (440Hz sine wave)
        sample_rate = 8000
        frequency = 440  # A4 note
        chunk_size = 160  # 20ms at 8kHz
        samples_per_chunk = chunk_size
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            while (asyncio.get_event_loop().time() - start_time) < duration:
                # Check if models are ready
                if call_data.get('models_ready', False):
                    logger.info("Models ready, stopping ring tone", channel_id=channel_id)
                    break
                    
                # Generate sine wave chunk
                chunk_duration = samples_per_chunk / sample_rate
                t = asyncio.get_event_loop().time() - start_time
                
                # Create sine wave samples
                samples = []
                for i in range(samples_per_chunk):
                    sample_time = t + (i / sample_rate)
                    # Ring pattern: 2 seconds on, 4 seconds off
                    ring_cycle = (sample_time % 6.0)
                    if ring_cycle < 2.0:  # Ring on
                        amplitude = 0.3 * (1.0 if ring_cycle < 1.0 else 0.5)  # Fade in/out
                        # Generate sine wave and clamp to valid 16-bit range
                        sine_value = 0.5 * (1 + (sample_time * frequency * 2 * 3.14159) % (2 * 3.14159))
                        sample = int(amplitude * 16000 * sine_value)  # Reduced amplitude
                        sample = max(-32768, min(32767, sample))  # Clamp to 16-bit range
                    else:  # Ring off
                        sample = 0
                    samples.append(sample)
                
                try:
                    # Convert to ulaw - need to pack as 16-bit little-endian
                    pcm_data = struct.pack('<' + 'h' * len(samples), *samples)
                    ulaw_data = audioop.lin2ulaw(pcm_data, 2)
                    
                    # Packetize and send
                    rtp_packet = rtp_packetizer.packetize(ulaw_data, payload_type=0)
                    await self.udp_server.send_rtp_packet(rtp_packet, asterisk_rtp_addr)
                    logger.debug(f"Sent ring tone packet ({len(ulaw_data)} bytes) to {asterisk_rtp_addr}")
                    
                except Exception as audio_error:
                    logger.error("Audio generation error", channel_id=channel_id, error=str(audio_error))
                    # Continue with silence if audio generation fails
                    silence_data = b'\x00' * chunk_size
                    rtp_packet = rtp_packetizer.packetize(silence_data, payload_type=0)
                    await self.udp_server.send_rtp_packet(rtp_packet, asterisk_rtp_addr)
                
                await asyncio.sleep(0.02)  # 20ms delay
                
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
