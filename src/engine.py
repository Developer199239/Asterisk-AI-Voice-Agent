import asyncio
import os
import random
import signal
import struct
import uuid
import audioop
import base64
from typing import Dict, Any, Optional, List

from .ari_client import ARIClient
from aiohttp import web
from .config import AppConfig, load_config, DeepgramProviderConfig, LocalProviderConfig
from .logging_config import get_logger, configure_logging
from .providers.base import AIProviderInterface
from .audiosocket_server import AudioSocketServer
from .providers.deepgram import DeepgramProvider
from .providers.local import LocalProvider

logger = get_logger(__name__)

class AudioFrameProcessor:
    """Processes audio in 20ms frames to prevent voice queue backlog."""
    
    def __init__(self, frame_size: int = 160):  # 20ms at 8kHz = 160 samples
        self.frame_size = frame_size
        self.buffer = bytearray()
        self.frame_bytes = frame_size * 2  # 2 bytes per sample (PCM16)
    
    def process_audio(self, audio_data: bytes) -> List[bytes]:
        """Process audio data and return complete frames."""
        # Accumulate audio in buffer
        self.buffer.extend(audio_data)
        
        # Extract complete frames
        frames = []
        while len(self.buffer) >= self.frame_bytes:
            frame = bytes(self.buffer[:self.frame_bytes])
            self.buffer = self.buffer[self.frame_bytes:]
            frames.append(frame)
        
        # Debug frame processing
        if len(frames) > 0:
            logger.debug("🎤 AVR FrameProcessor - Frames Generated",
                        input_bytes=len(audio_data),
                        buffer_before=len(self.buffer) + (len(frames) * self.frame_bytes),
                        buffer_after=len(self.buffer),
                        frames_generated=len(frames),
                        frame_size=self.frame_bytes)
        
        return frames
    
    def flush(self) -> bytes:
        """Flush remaining audio in buffer."""
        remaining = bytes(self.buffer)
        self.buffer = bytearray()
        return remaining

class VoiceActivityDetector:
    """Simple VAD to reduce unnecessary audio processing."""
    
    def __init__(self, speech_threshold: float = 0.1, silence_frames: int = 10):
        self.speech_threshold = speech_threshold
        self.max_silence_frames = silence_frames
        self.silence_frames = 0
        self.is_speaking = False
    
    def is_speech(self, audio_energy: float) -> bool:
        """Determine if audio contains speech."""
        if audio_energy > self.speech_threshold:
            self.silence_frames = 0
            if not self.is_speaking:
                self.is_speaking = True
                logger.debug("🎤 AVR VAD - Speech Started", 
                           energy=f"{audio_energy:.4f}", 
                           threshold=f"{self.speech_threshold:.4f}")
            return True
        else:
            self.silence_frames += 1
            if self.is_speaking and self.silence_frames >= self.max_silence_frames:
                self.is_speaking = False
                logger.debug("🎤 AVR VAD - Speech Ended", 
                           silence_frames=self.silence_frames,
                           max_silence=self.max_silence_frames)
            return self.silence_frames < self.max_silence_frames


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
        self.conn_to_channel: Dict[str, str] = {}
        self.channel_to_conn: Dict[str, str] = {}
        self.conn_to_caller: Dict[str, str] = {}  # conn_id -> caller_channel_id
        self.pending_channel_for_bind: Optional[str] = None
        # Audio buffering for better playback quality
        self.audio_buffers: Dict[str, bytes] = {}
        self.buffer_size = 1600  # 200ms of audio at 8kHz (1600 bytes of ulaw)
        self.audiosocket_server: Any = None
        # Headless sessions for AudioSocket-only mode (no ARI channel)
        self.headless_sessions: Dict[str, Dict[str, Any]] = {}
        # Bridge and Local channel tracking for Local Channel Bridge pattern
        self.bridges: Dict[str, str] = {}  # channel_id -> bridge_id
        # Frame processing and VAD for optimized audio handling
        self.frame_processors: Dict[str, AudioFrameProcessor] = {}  # conn_id -> processor
        self.vad_detectors: Dict[str, VoiceActivityDetector] = {}  # conn_id -> VAD
        self.local_channels: Dict[str, str] = {}  # channel_id -> local_channel_id
        # Map our synthesized UUID extension to the real ARI caller channel id
        self.uuidext_to_channel: Dict[str, str] = {}
        # NEW: Caller channel tracking for dual StasisStart handling
        self.caller_channels: Dict[str, Dict[str, Any]] = {}  # caller_channel_id -> call_data
        self.pending_local_channels: Dict[str, str] = {}  # local_channel_id -> caller_channel_id
        # Debug counter for inbound AudioSocket audio frames per connection
        self._audio_rx_debug: Dict[str, int] = {}
        # Keepalive tasks per AudioSocket connection
        self._keepalive_tasks: Dict[str, asyncio.Task] = {}
        # Health server runner
        self._health_runner: Optional[web.AppRunner] = None

        # Event handlers
        self.ari_client.on_event("StasisStart", self._handle_stasis_start)
        self.ari_client.on_event("StasisEnd", self._handle_stasis_end)
        self.ari_client.on_event("ChannelDestroyed", self._handle_channel_destroyed)
        self.ari_client.on_event("ChannelDtmfReceived", self._handle_dtmf_received)
        # Bind AudioSocket connections robustly using variable events
        self.ari_client.on_event("ChannelVarset", self._handle_channel_varset)

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
        # Log transport and downstream modes
        logger.info("Runtime modes", audio_transport=self.config.audio_transport, downstream_mode=self.config.downstream_mode)

        # Prepare AudioSocket server scaffold (non-invasive for current release)
        if self.config.audio_transport == "audiosocket":
            host = os.getenv("AUDIOSOCKET_HOST", "127.0.0.1")
            port = int(os.getenv("AUDIOSOCKET_PORT", "8090"))
            # Wire on_audio callback to route chunks to provider
            self.audiosocket_server = AudioSocketServer(host=host, port=port,
                                                       on_audio=self._on_audiosocket_audio,
                                                       on_accept=self._on_audiosocket_accept,
                                                       on_close=self._on_audiosocket_close)
            asyncio.create_task(self.audiosocket_server.start())

        # Start lightweight health endpoint
        try:
            asyncio.create_task(self._start_health_server())
        except Exception:
            logger.debug("Health server failed to start", exc_info=True)
        await self.ari_client.connect()
        asyncio.create_task(self.ari_client.start_listening())
        logger.info("Engine started and listening for calls.")

    async def stop(self):
        """Disconnect from ARI and stop the engine."""
        for channel_id in list(self.active_calls.keys()):
            await self._cleanup_call(channel_id)
        await self.ari_client.disconnect()
        # Stop AudioSocket server if running
        if hasattr(self, 'audiosocket_server') and self.audiosocket_server:
            await self.audiosocket_server.stop()
        # Stop health server
        try:
            if self._health_runner:
                await self._health_runner.cleanup()
        except Exception:
            logger.debug("Health server cleanup error", exc_info=True)
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

    def _is_caller_channel(self, channel: dict) -> bool:
        """Check if this is a caller channel (SIP, PJSIP, etc.)"""
        channel_name = channel.get('name', '')
        return any(channel_name.startswith(prefix) for prefix in ['SIP/', 'PJSIP/', 'DAHDI/', 'IAX2/'])

    def _is_local_channel(self, channel: dict) -> bool:
        """Check if this is a Local channel"""
        channel_name = channel.get('name', '')
        return channel_name.startswith('Local/')

    def _find_caller_for_local(self, local_channel_id: str) -> Optional[str]:
        """Find the caller channel that corresponds to this Local channel."""
        # Check if we have a pending Local channel mapping
        if local_channel_id in self.pending_local_channels:
            return self.pending_local_channels[local_channel_id]
        
        # Fallback: search through caller channels
        for caller_id, call_data in self.caller_channels.items():
            if call_data.get('local_channel_id') == local_channel_id:
                return caller_id
        
        return None

    async def _handle_stasis_start(self, event: dict):
        """Handle StasisStart events - Hybrid ARI approach with single handler."""
        logger.info("🎯 HYBRID ARI - StasisStart event received", event_data=event)
        channel = event.get('channel', {})
        channel_id = channel.get('id')
        channel_name = channel.get('name', '')
        
        logger.info("🎯 HYBRID ARI - Channel analysis", 
                   channel_id=channel_id,
                   channel_name=channel_name,
                   is_caller=self._is_caller_channel(channel),
                   is_local=self._is_local_channel(channel))
        
        if self._is_caller_channel(channel):
            # This is the caller channel entering Stasis - MAIN FLOW
            logger.info("🎯 HYBRID ARI - Processing caller channel", channel_id=channel_id)
            await self._handle_caller_stasis_start_hybrid(channel_id, channel)
        elif self._is_local_channel(channel):
            # This is the Local channel entering Stasis - NOW EXPECTED!
            logger.info("🎯 HYBRID ARI - Local channel entered Stasis", 
                       channel_id=channel_id,
                       channel_name=channel_name)
            # Now add the Local channel to the bridge
            await self._handle_local_stasis_start_hybrid(channel_id, channel)
        else:
            logger.warning("🎯 HYBRID ARI - Unknown channel type in StasisStart", 
                          channel_id=channel_id, 
                          channel_name=channel_name)

    async def _handle_caller_stasis_start_hybrid(self, caller_channel_id: str, channel: dict):
        """Handle caller channel entering Stasis - Hybrid ARI approach."""
        caller_info = channel.get('caller', {})
        logger.info("🎯 HYBRID ARI - Caller channel entered Stasis", 
                    channel_id=caller_channel_id,
                    caller_name=caller_info.get('name'),
                    caller_number=caller_info.get('number'))
        
        # Check if call is already in progress
        if caller_channel_id in self.caller_channels:
            logger.warning("🎯 HYBRID ARI - Caller already in progress", channel_id=caller_channel_id)
            return
        
        try:
            # Step 1: Answer the caller
            logger.info("🎯 HYBRID ARI - Step 1: Answering caller channel", channel_id=caller_channel_id)
            await self.ari_client.answer_channel(caller_channel_id)
            logger.info("🎯 HYBRID ARI - Step 1: ✅ Caller channel answered", channel_id=caller_channel_id)
            
            # Step 2: Create bridge immediately
            logger.info("🎯 HYBRID ARI - Step 2: Creating bridge immediately", channel_id=caller_channel_id)
            bridge_id = await self.ari_client.create_bridge(bridge_type="mixing")
            if not bridge_id:
                raise RuntimeError("Failed to create mixing bridge")
            logger.info("🎯 HYBRID ARI - Step 2: ✅ Bridge created", 
                       channel_id=caller_channel_id, 
                       bridge_id=bridge_id)
            
            # Step 3: Add caller to bridge
            logger.info("🎯 HYBRID ARI - Step 3: Adding caller to bridge", 
                       channel_id=caller_channel_id, 
                       bridge_id=bridge_id)
            caller_success = await self.ari_client.add_channel_to_bridge(bridge_id, caller_channel_id)
            if not caller_success:
                raise RuntimeError("Failed to add caller channel to bridge")
            logger.info("🎯 HYBRID ARI - Step 3: ✅ Caller added to bridge", 
                       channel_id=caller_channel_id, 
                       bridge_id=bridge_id)
            
            # Step 4: Store caller info with bridge
            self.caller_channels[caller_channel_id] = {
                "status": "bridge_ready",
                "channel": channel,
                "local_channel_id": None,
                "bridge_id": bridge_id
            }
            self.bridges[caller_channel_id] = bridge_id
            logger.info("🎯 HYBRID ARI - Step 4: ✅ Caller info stored", 
                       channel_id=caller_channel_id, 
                       bridge_id=bridge_id)
            
            # Step 5: Originate Local channel with minimal dialplan
            logger.info("🎯 HYBRID ARI - Step 5: Originating Local channel", channel_id=caller_channel_id)
            await self._originate_local_channel_hybrid(caller_channel_id)
            
        except Exception as e:
            logger.error("🎯 HYBRID ARI - Failed to handle caller StasisStart", 
                        caller_channel_id=caller_channel_id, 
                        error=str(e), exc_info=True)
            await self._cleanup_call(caller_channel_id)

    async def _handle_local_stasis_start_hybrid(self, local_channel_id: str, channel: dict):
        """Handle Local channel entering Stasis - Hybrid ARI approach."""
        logger.info("🎯 HYBRID ARI - Processing Local channel StasisStart", 
                   local_channel_id=local_channel_id)
        
        # Find the caller channel that this Local channel belongs to
        caller_channel_id = self._find_caller_for_local(local_channel_id)
        if not caller_channel_id:
            logger.error("🎯 HYBRID ARI - No caller found for Local channel", 
                        local_channel_id=local_channel_id)
            await self.ari_client.hangup_channel(local_channel_id)
            return
        
        # Check if caller channel exists and has a bridge
        if caller_channel_id not in self.caller_channels:
            logger.error("🎯 HYBRID ARI - Caller channel not found for Local channel", 
                        local_channel_id=local_channel_id,
                        caller_channel_id=caller_channel_id)
            await self.ari_client.hangup_channel(local_channel_id)
            return
        
        bridge_id = self.caller_channels[caller_channel_id]["bridge_id"]
        
        try:
            # Add Local channel to bridge
            logger.info("🎯 HYBRID ARI - Adding Local channel to bridge", 
                       local_channel_id=local_channel_id,
                       bridge_id=bridge_id)
            local_success = await self.ari_client.add_channel_to_bridge(bridge_id, local_channel_id)
            if local_success:
                logger.info("🎯 HYBRID ARI - ✅ Local channel added to bridge", 
                           local_channel_id=local_channel_id,
                           bridge_id=bridge_id)
                # Update caller info
                self.caller_channels[caller_channel_id]["local_channel_id"] = local_channel_id
                self.caller_channels[caller_channel_id]["status"] = "connected"
                self.local_channels[caller_channel_id] = local_channel_id
                
                # Start provider session
                await self._start_provider_session_hybrid(caller_channel_id, local_channel_id)
            else:
                logger.error("🎯 HYBRID ARI - Failed to add Local channel to bridge", 
                           local_channel_id=local_channel_id,
                           bridge_id=bridge_id)
                await self.ari_client.hangup_channel(local_channel_id)
        except Exception as e:
            logger.error("🎯 HYBRID ARI - Failed to handle Local channel StasisStart", 
                        local_channel_id=local_channel_id,
                        error=str(e), exc_info=True)
            await self.ari_client.hangup_channel(local_channel_id)

    async def _handle_caller_stasis_start(self, caller_channel_id: str, channel: dict):
        """Handle caller channel entering Stasis - LEGACY (kept for reference)."""
        caller_info = channel.get('caller', {})
        logger.info("Caller channel entered Stasis", 
                    channel_id=caller_channel_id,
                    caller_name=caller_info.get('name'),
                    caller_number=caller_info.get('number'))
        
        # Check if call is already in progress
        if caller_channel_id in self.caller_channels:
            logger.warning("Caller already in progress", channel_id=caller_channel_id)
            return
        
        try:
            # Answer the caller
            await self.ari_client.answer_channel(caller_channel_id)
            logger.info("Caller channel answered", channel_id=caller_channel_id)
            
            # Store caller info
            self.caller_channels[caller_channel_id] = {
                "status": "waiting_for_local",
                "channel": channel,
                "local_channel_id": None,
                "bridge_id": None
            }
            
            # Originate Local channel
            await self._originate_local_channel(caller_channel_id)
            
        except Exception as e:
            logger.error("Failed to handle caller StasisStart", 
                        caller_channel_id=caller_channel_id, 
                        error=str(e), exc_info=True)
            await self._cleanup_call(caller_channel_id)

    async def _handle_local_stasis_start(self, local_channel_id: str, channel: dict):
        """Handle Local channel entering Stasis."""
        logger.info("Local channel entered Stasis", 
                    channel_id=local_channel_id,
                    channel_name=channel.get('name'))
        
        try:
            # Find the caller this Local channel belongs to
            caller_channel_id = self._find_caller_for_local(local_channel_id)
            if not caller_channel_id:
                logger.error("No caller found for Local channel", local_channel_id=local_channel_id)
                await self.ari_client.hangup_channel(local_channel_id)
                return
            
            # Update caller info with Local channel ID
            if caller_channel_id in self.caller_channels:
                self.caller_channels[caller_channel_id]["local_channel_id"] = local_channel_id
                self.local_channels[caller_channel_id] = local_channel_id
            
            # Create bridge and connect channels
            await self._create_bridge_and_connect(caller_channel_id, local_channel_id)
            
        except Exception as e:
            logger.error("Failed to handle Local StasisStart", 
                        local_channel_id=local_channel_id, 
                        error=str(e), exc_info=True)
            # Clean up both channels
            caller_channel_id = self._find_caller_for_local(local_channel_id)
            if caller_channel_id:
                await self._cleanup_call(caller_channel_id)
            await self.ari_client.hangup_channel(local_channel_id)

    async def _originate_local_channel_hybrid(self, caller_channel_id: str):
        """Originate Local channel for AudioSocket - Hybrid ARI approach."""
        # Generate UUID for AudioSocket binding
        audio_uuid = str(uuid.uuid4())
        local_endpoint = f"Local/{audio_uuid}@ai-audiosocket/n"
        
        orig_params = {
            "endpoint": local_endpoint,
            "extension": audio_uuid,  # Use UUID as extension for AudioSocket binding
            "context": "ai-audiosocket",  # Minimal dialplan context
            "priority": "1",
            "timeout": "30",
            "app": self.config.asterisk.app_name,  # CRITICAL: Enter Stasis application
        }
        
        logger.info("🎯 HYBRID ARI - Originating Local channel", 
                    endpoint=local_endpoint, 
                    caller_channel_id=caller_channel_id,
                    audio_uuid=audio_uuid)
        
        try:
            response = await self.ari_client.send_command("POST", "channels", params=orig_params)
            if response and response.get("id"):
                local_channel_id = response["id"]
                # Store mapping for AudioSocket binding
                self.pending_local_channels[local_channel_id] = caller_channel_id
                self.uuidext_to_channel[audio_uuid] = caller_channel_id
                logger.info("🎯 HYBRID ARI - Local channel originated", 
                           local_channel_id=local_channel_id, 
                           caller_channel_id=caller_channel_id,
                           audio_uuid=audio_uuid)
                
                # Store Local channel info - will be added to bridge when StasisStart event arrives
                if caller_channel_id in self.caller_channels:
                    self.caller_channels[caller_channel_id]["pending_local_channel_id"] = local_channel_id
                    logger.info("🎯 HYBRID ARI - Local channel originated, waiting for StasisStart", 
                               local_channel_id=local_channel_id,
                               caller_channel_id=caller_channel_id)
                else:
                    logger.error("🎯 HYBRID ARI - Caller channel not found for Local channel", 
                               local_channel_id=local_channel_id,
                               caller_channel_id=caller_channel_id)
                    raise RuntimeError("Caller channel not found")
            else:
                raise RuntimeError("Failed to originate Local channel")
        except Exception as e:
            logger.error("🎯 HYBRID ARI - Local channel originate failed", 
                        caller_channel_id=caller_channel_id,
                        audio_uuid=audio_uuid,
                        error=str(e), exc_info=True)
            raise

    async def _originate_local_channel(self, caller_channel_id: str):
        """Originate Local channel for AudioSocket - LEGACY (kept for reference)."""
        local_endpoint = f"Local/{caller_channel_id}@ai-agent-media-fork/n"
        
        orig_params = {
            "endpoint": local_endpoint,
            "extension": caller_channel_id,
            "context": "ai-agent-media-fork",
            "priority": "1",
            "timeout": "30",
            "app": self.config.asterisk.app_name,
        }
        
        logger.info("Originating Local channel", 
                    endpoint=local_endpoint, 
                    caller_channel_id=caller_channel_id)
        
        try:
            response = await self.ari_client.send_command("POST", "channels", params=orig_params)
            if response and response.get("id"):
                local_channel_id = response["id"]
                # Store pending mapping
                self.pending_local_channels[local_channel_id] = caller_channel_id
                logger.info("Local channel originated", 
                           local_channel_id=local_channel_id, 
                           caller_channel_id=caller_channel_id)
            else:
                raise RuntimeError("Failed to originate Local channel")
        except Exception as e:
            logger.error("Local channel originate failed", 
                        caller_channel_id=caller_channel_id, 
                        error=str(e), exc_info=True)
            raise

    async def _create_bridge_and_connect(self, caller_channel_id: str, local_channel_id: str):
        """Create bridge and connect both channels."""
        try:
            # Create mixing bridge
            bridge_id = await self.ari_client.create_bridge(bridge_type="mixing")
            if not bridge_id:
                raise RuntimeError("Failed to create mixing bridge")
            
            logger.info("Bridge created", bridge_id=bridge_id, 
                       caller_channel_id=caller_channel_id, 
                       local_channel_id=local_channel_id)
            
            # Add both channels to bridge
            caller_success = await self.ari_client.add_channel_to_bridge(bridge_id, caller_channel_id)
            local_success = await self.ari_client.add_channel_to_bridge(bridge_id, local_channel_id)
            
            if not caller_success:
                logger.error("Failed to add caller channel to bridge", 
                            bridge_id=bridge_id, caller_channel_id=caller_channel_id)
                raise RuntimeError("Failed to add caller channel to bridge")
            
            if not local_success:
                logger.error("Failed to add Local channel to bridge", 
                            bridge_id=bridge_id, local_channel_id=local_channel_id)
                raise RuntimeError("Failed to add Local channel to bridge")
            
            # Store bridge info
            self.bridges[caller_channel_id] = bridge_id
            if caller_channel_id in self.caller_channels:
                self.caller_channels[caller_channel_id]["bridge_id"] = bridge_id
                self.caller_channels[caller_channel_id]["status"] = "connected"
            
            logger.info("Channels successfully bridged", 
                       bridge_id=bridge_id, 
                       caller_channel_id=caller_channel_id, 
                       local_channel_id=local_channel_id)
            
            # Start provider session and bind AudioSocket
            await self._start_provider_session(caller_channel_id, local_channel_id)
            
        except Exception as e:
            logger.error("Failed to create bridge and connect channels", 
                        caller_channel_id=caller_channel_id, 
                        local_channel_id=local_channel_id, 
                        error=str(e), exc_info=True)
            await self._cleanup_call(caller_channel_id)

    async def _start_provider_session_hybrid(self, caller_channel_id: str, local_channel_id: str):
        """Start provider session - Hybrid ARI approach."""
        try:
            logger.info("🎯 HYBRID ARI - Starting provider session", 
                       local_channel_id=local_channel_id, 
                       caller_channel_id=caller_channel_id)
            
            # Get provider
            provider = self.providers.get(self.config.default_provider)
            if not provider:
                logger.error("🎯 HYBRID ARI - Default provider not found", provider=self.config.default_provider)
                return
            
            # Start provider session
            logger.info("🎯 HYBRID ARI - Starting provider session", provider=self.config.default_provider)
            await provider.start_session(local_channel_id)
            
            # Store in active calls
            bridge_id = self.caller_channels.get(caller_channel_id, {}).get("bridge_id")
            self.active_calls[local_channel_id] = {
                "provider": provider,
                "conversation_state": "greeting",
                "bridge_id": bridge_id,
                "local_channel_id": local_channel_id,
                "caller_channel_id": caller_channel_id
            }
            
            # Also store reverse mapping for DTMF
            self.active_calls[caller_channel_id] = {
                "provider": provider,
                "conversation_state": "greeting",
                "bridge_id": bridge_id,
                "local_channel_id": local_channel_id,
                "caller_channel_id": caller_channel_id
            }
            
            logger.info("🎯 HYBRID ARI - ✅ Provider session started", 
                       local_channel_id=local_channel_id, 
                       caller_channel_id=caller_channel_id,
                       provider=self.config.default_provider)
            
            # Play initial greeting
            await self._play_initial_greeting_hybrid(caller_channel_id, local_channel_id)
            
        except Exception as e:
            logger.error("🎯 HYBRID ARI - Failed to start provider session", 
                        local_channel_id=local_channel_id, 
                        caller_channel_id=caller_channel_id,
                        error=str(e), exc_info=True)

    async def _play_initial_greeting_hybrid(self, caller_channel_id: str, local_channel_id: str):
        """Play initial greeting - Hybrid ARI approach with AudioSocket streaming."""
        try:
            logger.info("🎯 HYBRID ARI - Playing initial greeting via AudioSocket", 
                       caller_channel_id=caller_channel_id,
                       local_channel_id=local_channel_id)
            
            # Get provider for greeting
            provider = self.providers.get(self.config.default_provider)
            if not provider:
                logger.error("🎯 HYBRID ARI - Provider not found for greeting")
                return
            
            # Generate greeting audio
            greeting_text = self.config.llm.initial_greeting
            logger.info("🎯 HYBRID ARI - Generating greeting audio", text=greeting_text)
            
            # Use provider to generate TTS
            audio_data = await provider.text_to_speech(greeting_text)
            if audio_data:
                # Stream audio via AudioSocket instead of file-based playback
                await self._stream_audio_via_audiosocket(caller_channel_id, audio_data)
                logger.info("🎯 HYBRID ARI - ✅ Initial greeting streamed via AudioSocket", 
                           caller_channel_id=caller_channel_id,
                           audio_size=len(audio_data))
            else:
                logger.warning("🎯 HYBRID ARI - No greeting audio generated")
                
        except Exception as e:
            logger.error("🎯 HYBRID ARI - Failed to play initial greeting", 
                        caller_channel_id=caller_channel_id,
                        local_channel_id=local_channel_id,
                        error=str(e), exc_info=True)

    async def _start_provider_session(self, caller_channel_id: str, local_channel_id: str):
        """Start provider session and bind AudioSocket - LEGACY (kept for reference)."""
        try:
            # Get provider
            provider = self.providers.get(self.config.default_provider)
            if not provider:
                logger.error("Default provider not found", provider=self.config.default_provider)
                return
            
            # Start provider session
            await provider.start_session(local_channel_id)
            
            # Store in active calls
            bridge_id = self.caller_channels.get(caller_channel_id, {}).get("bridge_id")
            self.active_calls[local_channel_id] = {
                "provider": provider,
                "conversation_state": "greeting",
                "bridge_id": bridge_id,
                "local_channel_id": local_channel_id,
                "caller_channel_id": caller_channel_id
            }
            
            # Also store reverse mapping for DTMF
            self.active_calls[caller_channel_id] = {
                "provider": provider,
                "conversation_state": "greeting",
                "bridge_id": bridge_id,
                "local_channel_id": local_channel_id,
                "caller_channel_id": caller_channel_id
            }
            
            logger.info("Provider session started", 
                       local_channel_id=local_channel_id, 
                       caller_channel_id=caller_channel_id,
                       provider=self.config.default_provider)
            
            # AudioSocket will bind automatically via ChannelVarset
            logger.info("Ready for AudioSocket binding", local_channel_id=local_channel_id)
            
        except Exception as e:
            logger.error("Failed to start provider session", 
                        local_channel_id=local_channel_id, 
                        caller_channel_id=caller_channel_id,
                        error=str(e), exc_info=True)

    async def _bind_connection_to_channel(self, conn_id: str, channel_id: str, provider_name: str):
        """Bind an accepted AudioSocket connection to a Stasis channel and start provider.

        Plays a one-time test prompt to validate audio path, then proceeds with provider flow.
        """
        try:
            # If a connection is already bound to this channel, reject extras to avoid idle sockets
            existing = self.channel_to_conn.get(channel_id)
            if existing and existing != conn_id:
                logger.info("Rejecting extra AudioSocket connection for already-bound channel",
                            channel_id=channel_id, existing_conn=existing, new_conn=conn_id)
                try:
                    await self.audiosocket_server.close_connection(conn_id)
                except Exception:
                    logger.debug("Error closing extra AudioSocket connection", conn_id=conn_id, exc_info=True)
                return

            self.conn_to_channel[conn_id] = channel_id
            self.channel_to_conn[channel_id] = conn_id
            logger.info("AudioSocket connection bound to channel", channel_id=channel_id, conn_id=conn_id)
            provider = self.active_calls.get(channel_id, {}).get('provider')
            if not provider:
                provider = self.providers.get(provider_name)
                if provider:
                    self.active_calls[channel_id] = {"provider": provider}
            # Hint upstream audio format for providers: AudioSocket delivers PCM16@8k by default
            try:
                if provider and hasattr(provider, 'set_input_mode'):
                    provider.set_input_mode('pcm16_8k')
                    logger.info("Set provider upstream input mode", channel_id=channel_id, conn_id=conn_id, mode='pcm16_8k', provider=provider_name)
            except Exception:
                logger.debug("Could not set provider input mode on bind", channel_id=channel_id, conn_id=conn_id, exc_info=True)

            # Start AudioSocket keepalive task to prevent idle timeouts in Asterisk app
            try:
                if conn_id in self._keepalive_tasks:
                    t = self._keepalive_tasks.pop(conn_id, None)
                    if t and not t.done():
                        t.cancel()
                self._keepalive_tasks[conn_id] = asyncio.create_task(self._audiosocket_keepalive(conn_id))
                logger.debug("Started AudioSocket keepalive", conn_id=conn_id)
            except Exception:
                logger.debug("Failed to start keepalive task", channel_id=channel_id, conn_id=conn_id, exc_info=True)
            # Remove demo-congrats/test tone; rely on provider greeting to start the dialog
            logger.debug("Skipping demo test playback; provider greeting will start the dialog", channel_id=channel_id)
            # Start provider session and optional greeting
            if provider:
                # Check if provider session already exists for this channel
                if channel_id in self.active_calls and self.active_calls[channel_id].get('provider'):
                    logger.debug("Provider session already exists, skipping", channel_id=channel_id)
                else:
                    logger.debug("Starting provider session", channel_id=channel_id, provider=provider_name)
                    await provider.start_session(channel_id)
                    logger.debug("Provider session started successfully", channel_id=channel_id)
                    
                    # Play initial greeting only when AudioSocket connects
                    if hasattr(provider, 'play_initial_greeting'):
                        logger.info("🔊 GREETING - Playing initial greeting", channel_id=channel_id)
                        await provider.play_initial_greeting(channel_id)
                        logger.info("🔊 GREETING - Played successfully", channel_id=channel_id)
        except Exception:
            logger.error("Error binding connection to channel", channel_id=channel_id, conn_id=conn_id, exc_info=True)

    async def _handle_channel_varset(self, event_data: dict):
        """Bind any pending AudioSocket connection when AUDIOSOCKET_UUID variable is set.

        The dialplan now generates a proper UUID, so we bind the AudioSocket to the Local channel.
        """
        try:
            variable = event_data.get('variable') or event_data.get('name')
            if variable != 'AUDIOSOCKET_UUID':
                return
            
            # Get the Local channel ID from the event
            channel = event_data.get('channel', {})
            local_channel_id = channel.get('id')
            if not local_channel_id:
                return
                
            # Find the corresponding caller channel ID
            caller_channel_id = None
            for caller_id, call_data in self.active_calls.items():
                if call_data.get('local_channel_id') == local_channel_id:
                    caller_channel_id = caller_id
                    break
            
            if not caller_channel_id:
                logger.warning("No caller channel found for Local channel", local_channel_id=local_channel_id)
                return
                
            if local_channel_id in self.channel_to_conn:
                return
                
            # Bind any already-accepted connection
            if hasattr(self, 'audiosocket_server') and self.audiosocket_server:
                conn_id = None
                try:
                    conn_id = self.audiosocket_server.try_get_connection_nowait()
                except Exception:
                    conn_id = None
                if conn_id:
                    await self._bind_connection_to_channel(conn_id, local_channel_id, self.config.default_provider)
                else:
                    # Remember channel; will bind on next accept
                    self.pending_channel_for_bind = local_channel_id
            logger.info("ChannelVarset bound or queued", variable=variable, target_channel_id=local_channel_id)
        except Exception:
            logger.debug("Error in ChannelVarset handler", exc_info=True)

    def _on_audiosocket_accept(self, conn_id: str):
        """Bind AudioSocket connection - Hybrid ARI approach."""
        try:
            logger.info("🎯 HYBRID ARI - AudioSocket connection accepted", conn_id=conn_id)
            
            # Initialize frame processor and VAD for this connection
            self.frame_processors[conn_id] = AudioFrameProcessor()
            self.vad_detectors[conn_id] = VoiceActivityDetector()
            logger.debug("🎯 HYBRID ARI - Audio processing components initialized", conn_id=conn_id)
            
            # CRITICAL FIX: Find the Local channel that has the AudioSocket connection
            # We need to find the Local channel that was just originated and is waiting for this connection
            local_channel_id = None
            caller_channel_id = None
            
            # Debug: Log all active channels and their status
            logger.info("🎯 HYBRID ARI - DEBUG: Searching for Local channel with AudioSocket connection")
            logger.info("🎯 HYBRID ARI - DEBUG: Active caller channels:", 
                       caller_channels=list(self.caller_channels.keys()),
                       caller_statuses={cid: data.get("status") for cid, data in self.caller_channels.items()})
            logger.info("🎯 HYBRID ARI - DEBUG: Pending local channels:", 
                       pending_local_channels=list(self.pending_local_channels.keys()))
            logger.info("🎯 HYBRID ARI - DEBUG: Local channels mapping:", 
                       local_channels=list(self.local_channels.keys()))
            
            # Look for a Local channel that was just originated and is waiting for AudioSocket
            for cid, call_data in self.caller_channels.items():
                if call_data.get("status") == "connected" and call_data.get("local_channel_id"):
                    local_channel_id = call_data["local_channel_id"]
                    caller_channel_id = cid
                    logger.info("🎯 HYBRID ARI - DEBUG: Found connected caller with Local channel", 
                               caller_channel_id=cid, 
                               local_channel_id=local_channel_id)
                    break
            
            if not local_channel_id or not caller_channel_id:
                logger.warning("🎯 HYBRID ARI - No Local channel found for AudioSocket connection", 
                              conn_id=conn_id,
                              local_channel_id=local_channel_id,
                              caller_channel_id=caller_channel_id)
                # Start headless session as fallback
                provider_name = self.config.default_provider
                provider = self.providers.get(provider_name)
                if provider:
                    logger.info("🎯 HYBRID ARI - Starting headless session as fallback", conn_id=conn_id)
                    asyncio.get_event_loop().create_task(self._start_headless_session(conn_id, provider))
                return
            
            # CRITICAL FIX: Bind AudioSocket to Local channel, not caller channel
            logger.info("🎯 HYBRID ARI - Binding AudioSocket to Local channel", 
                       conn_id=conn_id, 
                       local_channel_id=local_channel_id,
                       caller_channel_id=caller_channel_id)
            
            # Store connection mapping - CRITICAL: Map to Local channel
            self.conn_to_channel[conn_id] = local_channel_id  # Map to Local channel
            self.channel_to_conn[local_channel_id] = conn_id  # Map Local channel to connection
            
            # Also store reverse mapping for caller channel lookup
            self.conn_to_caller[conn_id] = caller_channel_id
            
            # Set provider input mode
            provider = self.providers.get(self.config.default_provider)
            if provider and hasattr(provider, 'set_input_mode'):
                provider.set_input_mode('pcm16_8k')
                logger.info("🎯 HYBRID ARI - Set provider input mode to pcm16_8k", conn_id=conn_id)
            
            logger.info("🎯 HYBRID ARI - ✅ AudioSocket connection bound to Local channel", 
                       conn_id=conn_id, 
                       local_channel_id=local_channel_id,
                       caller_channel_id=caller_channel_id)
            
        except Exception as e:
            logger.error("🎯 HYBRID ARI - Error in AudioSocket accept handler", 
                        conn_id=conn_id, 
                        error=str(e), exc_info=True)

    async def _start_headless_session(self, conn_id: str, provider: AIProviderInterface):
        """Start provider session without ARI channel; stream via AudioSocket."""
        try:
            logger.info("Starting headless session", conn_id=conn_id)
            await provider.start_session(conn_id)
            self.headless_sessions[conn_id] = {"provider": provider, "conversation_state": "greeting"}
            # Initial greeting will be played when AudioSocket connects
            # This prevents multiple greetings from being played
        except Exception:
            logger.error("Failed to start headless session", conn_id=conn_id, exc_info=True)

    def _on_audiosocket_close(self, conn_id: str):
        """Cleanup headless session when AudioSocket closes."""
        try:
            session = self.headless_sessions.pop(conn_id, None)
            if session:
                provider = session.get('provider')
                if provider:
                    asyncio.get_event_loop().create_task(provider.stop_session())
                logger.info("Headless session cleaned up", conn_id=conn_id)
            
            # Clean up frame processor and VAD
            self.frame_processors.pop(conn_id, None)
            self.vad_detectors.pop(conn_id, None)
            
            # Cancel keepalive task if running
            try:
                t = self._keepalive_tasks.pop(conn_id, None)
                if t and not t.done():
                    t.cancel()
            except Exception:
                logger.debug("Keepalive cancel failed", conn_id=conn_id, exc_info=True)
        except Exception:
            logger.debug("Error cleaning up headless session", conn_id=conn_id, exc_info=True)

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
        """Handle raw audio frames from AudioSocket connections."""
        try:
            # Find the active call (assuming single call for now)
            # For AudioSocket, we can use any active call since there should only be one
            active_channel_id = None
            for channel_id, call_data in self.active_calls.items():
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

            # Check conversation state
            conversation_state = call_data.get('conversation_state', 'greeting')
            
            if conversation_state == 'greeting':
                # During greeting phase, ignore incoming audio
                logger.debug("Ignoring audio during greeting phase", channel_id=active_channel_id)
                return
            elif conversation_state == 'listening':
                # During listening phase, buffer audio for conversation
                await self._handle_conversation_audio(active_channel_id, audio_data, call_data, provider)
            else:
                logger.debug("Unknown conversation state", state=conversation_state, channel_id=active_channel_id)
            
        except Exception as e:
            logger.error("Error processing audio frame", error=str(e), exc_info=True)

    async def _handle_conversation_audio(self, channel_id: str, audio_data: bytes, call_data: dict, provider):
        """Handle audio during conversation phase with VAD and timeout detection."""
        try:
            # Initialize audio buffer if not exists
            if 'audio_buffer' not in call_data:
                call_data['audio_buffer'] = b''
                call_data['last_audio_time'] = asyncio.get_event_loop().time()
                call_data['silence_start_time'] = None
                call_data['timeout_task'] = None
            
            current_time = asyncio.get_event_loop().time()
            
            # Simple VAD: check audio energy level
            has_voice = self._detect_voice_activity(audio_data)
            
            if has_voice:
                # Voice detected - add to buffer and update timing
                call_data['audio_buffer'] += audio_data
                call_data['last_audio_time'] = current_time
                call_data['silence_start_time'] = None
                
                # Cancel any existing timeout task
                if call_data.get('timeout_task') and not call_data['timeout_task'].done():
                    call_data['timeout_task'].cancel()
                
                # Start new timeout task for silence detection
                call_data['timeout_task'] = asyncio.create_task(
                    self._handle_silence_timeout(channel_id, call_data, provider)
                )
                
                logger.debug("Voice detected, buffering audio", channel_id=channel_id, buffer_size=len(call_data['audio_buffer']))
            else:
                # No voice detected - update silence timing
                if call_data['silence_start_time'] is None:
                    call_data['silence_start_time'] = current_time
                
                # If we have buffered audio and been silent for 1 second, send it
                if call_data['audio_buffer'] and (current_time - call_data['silence_start_time']) >= 1.0:
                    await self._send_buffered_audio(channel_id, call_data, provider)
            
        except Exception as e:
            logger.error("Error handling conversation audio", channel_id=channel_id, error=str(e), exc_info=True)

    def _detect_voice_activity(self, audio_data: bytes) -> bool:
        """Simple VAD based on audio energy level."""
        try:
            import struct
            
            # AudioSocket sends PCM16LE@8kHz directly - no conversion needed
            # Calculate RMS (Root Mean Square) energy
            samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
            rms = sum(sample * sample for sample in samples) / len(samples)
            rms = (rms ** 0.5) / 32768.0  # Normalize to 0-1
            
            # Lower threshold for better sensitivity to phone audio
            voice_threshold = 0.01  # Normalized threshold
            
            has_voice = rms > voice_threshold
            if has_voice:
                logger.debug("Voice activity detected", rms=f"{rms:.4f}", threshold=voice_threshold)
            
            return has_voice
        except Exception as e:
            logger.error("Error in VAD detection", error=str(e), exc_info=True)
            # Fallback: assume voice if we can't detect (conservative approach)
            return True

    async def _handle_silence_timeout(self, channel_id: str, call_data: dict, provider):
        """Handle silence timeout - play 'Are you still there?' greeting."""
        try:
            # Wait for 10 seconds of silence
            await asyncio.sleep(10.0)
            
            # Check if we're still in listening state and have been silent
            if (call_data.get('conversation_state') == 'listening' and 
                call_data.get('silence_start_time') and 
                call_data['audio_buffer']):
                
                logger.info("Silence timeout reached, playing 'Are you still there?'", channel_id=channel_id)
                
                # Change state to processing
                call_data['conversation_state'] = 'processing'
                
                # Send timeout greeting to provider
                timeout_message = {
                    "type": "timeout_greeting",
                    "call_id": channel_id,
                    "message": "Are you still there? I'm here and ready to help."
                }
                
                if hasattr(provider, 'websocket') and provider.websocket:
                    import json
                    await provider.websocket.send(json.dumps(timeout_message))
                    logger.info("Sent timeout greeting to Local AI Server", call_id=channel_id)
                
        except asyncio.CancelledError:
            # Timeout was cancelled (voice detected), this is normal
            logger.debug("Silence timeout cancelled", channel_id=channel_id)
        except Exception as e:
            logger.error("Error in silence timeout handler", channel_id=channel_id, error=str(e), exc_info=True)

    async def _send_buffered_audio(self, channel_id: str, call_data: dict, provider):
        """Send buffered audio to provider for processing."""
        try:
            if not call_data['audio_buffer']:
                logger.debug("No audio buffer to send", channel_id=channel_id)
                return
                
            logger.info("Sending buffered audio to provider for STT→LLM→TTS processing", 
                       channel_id=channel_id, 
                       buffer_size=len(call_data['audio_buffer']),
                       buffer_duration_estimate=f"{len(call_data['audio_buffer']) / 1000:.1f}s")
            
            # Send audio to provider (this may take time for long responses)
            await provider.send_audio(call_data['audio_buffer'])
            
            # Clear buffer and reset timing
            call_data['audio_buffer'] = b''
            call_data['last_audio_time'] = asyncio.get_event_loop().time()
            call_data['silence_start_time'] = None
            
            # Cancel timeout task
            if call_data.get('timeout_task') and not call_data['timeout_task'].done():
                call_data['timeout_task'].cancel()
            
            # Change state to processing while we wait for response
            call_data['conversation_state'] = 'processing'
            logger.info("Audio sent to provider, waiting for STT→LLM→TTS response", channel_id=channel_id)
            
            # Start a timeout task for provider response (30 seconds for long TTS generation)
            call_data['provider_timeout_task'] = asyncio.create_task(
                self._handle_provider_timeout(channel_id, call_data)
            )
            
        except Exception as e:
            logger.error("Error sending buffered audio to provider", channel_id=channel_id, error=str(e), exc_info=True)
            # Reset state to listening on error to allow retry
            call_data['conversation_state'] = 'listening'

    async def _handle_provider_timeout(self, channel_id: str, call_data: dict):
        """Handle timeout waiting for provider response."""
        try:
            # Wait for 30 seconds for provider response
            await asyncio.sleep(30.0)
            
            # Check if we're still waiting for a response
            if call_data.get('conversation_state') == 'processing':
                logger.warning("Provider response timeout - no audio received within 30 seconds", channel_id=channel_id)
                
                # Reset to listening state to allow user to try again
                call_data['conversation_state'] = 'listening'
                
                # Cancel any pending timeout tasks
                if call_data.get('timeout_task') and not call_data['timeout_task'].done():
                    call_data['timeout_task'].cancel()
                
                logger.info("Reset to listening state after provider timeout", channel_id=channel_id)
                
        except asyncio.CancelledError:
            # Timeout was cancelled (response received), this is normal
            logger.debug("Provider timeout cancelled - response received", channel_id=channel_id)
        except Exception as e:
            logger.error("Error in provider timeout handler", channel_id=channel_id, error=str(e), exc_info=True)

    async def _handle_dtmf_received(self, event_data: dict):
        """Handle DTMF events from channels."""
        channel = event_data.get('channel', {})
        channel_id = channel.get('id')
        digit = event_data.get('digit')
        
        if channel_id and digit:
            logger.info(f"DTMF received: {digit}", channel_id=channel_id)
            # Forward DTMF to provider if it supports it
            call_data = self.active_calls.get(channel_id)  # ✅ Move outside if block
            if call_data:
                provider = call_data.get('provider')
                if provider and hasattr(provider, 'handle_dtmf'):
                    await provider.handle_dtmf(digit)

    def _on_audiosocket_audio(self, conn_id: str, audio_data: bytes):
        """Route inbound AudioSocket audio using frame-based processing to prevent voice queue backlog."""
        try:
            # Check if call is still active
            channel_id = self.conn_to_channel.get(conn_id)
            if not channel_id or channel_id not in self.active_calls:
                logger.debug("Audio received for inactive call, ignoring", conn_id=conn_id, channel_id=channel_id)
                return
            
            # Track audio chunks for debugging
            count = self._audio_rx_debug.get(conn_id, 0) + 1
            self._audio_rx_debug[conn_id] = count
            
            # Enhanced debugging for first 10 chunks, then every 50th
            if count <= 10 or count % 50 == 0:
                logger.info("🎤 AUDIO CAPTURE - Chunk Received",
                           conn_id=conn_id,
                           bytes=len(audio_data),
                           chunk_number=count,
                           has_frame_processor=conn_id in self.frame_processors,
                           has_vad_detector=conn_id in self.vad_detectors)
            
            # Get frame processor and VAD for this connection
            frame_processor = self.frame_processors.get(conn_id)
            vad_detector = self.vad_detectors.get(conn_id)
            
            if not frame_processor or not vad_detector:
                logger.warning("🚨 AVR Frame Processing - Missing Components", 
                              conn_id=conn_id,
                              has_frame_processor=frame_processor is not None,
                              has_vad_detector=vad_detector is not None,
                              available_processors=list(self.frame_processors.keys()),
                              available_vads=list(self.vad_detectors.keys()))
                return
            
            # AudioSocket sends PCM16LE@8kHz directly - no conversion needed
            pcm_data = audio_data
            
            # Process audio into frames
            frames = frame_processor.process_audio(pcm_data)
            
            if count <= 10 or count % 50 == 0:
                logger.info("🎤 AUDIO PROCESSING - Frames Generated",
                           conn_id=conn_id,
                           input_bytes=len(pcm_data),
                           frames_generated=len(frames),
                           chunk_number=count)
            
            # Process each frame
            speech_frames = 0
            silence_frames = 0
            
            for frame_idx, frame in enumerate(frames):
                # Calculate energy for VAD
                audio_energy = self._calculate_frame_energy(frame)
                
                # Only process if speech detected
                if vad_detector.is_speech(audio_energy):
                    speech_frames += 1
                    # Route frame to appropriate provider
                    self._route_audio_frame(conn_id, frame, audio_energy)
                else:
                    silence_frames += 1
                    # Log silence frames occasionally
                    if count % 100 == 0:
                        logger.debug("🎤 AVR Frame Processing - Silence Frame Skipped", 
                                     conn_id=conn_id, 
                                     frame_idx=frame_idx,
                                     energy=f"{audio_energy:.4f}",
                                     chunk_number=count)
            
            # Log frame processing summary
            if count <= 10 or count % 50 == 0:
                logger.info("🎤 AUDIO PROCESSING - Summary",
                           conn_id=conn_id,
                           total_frames=len(frames),
                           speech_frames=speech_frames,
                           silence_frames=silence_frames,
                           chunk_number=count)
            
        except Exception as e:
            logger.error("🚨 AVR Frame Processing - Error", 
                         conn_id=conn_id, error=str(e), exc_info=True)
    
    def _calculate_frame_energy(self, frame: bytes) -> float:
        """Calculate audio energy for a single frame."""
        try:
            import struct
            samples = struct.unpack(f'<{len(frame)//2}h', frame)
            energy = sum(sample * sample for sample in samples) / len(samples)
            return (energy ** 0.5) / 32768.0  # Normalize to 0-1
        except Exception:
            return 0.0
    
    def _route_audio_frame(self, conn_id: str, frame: bytes, audio_energy: float):
        """Route a single audio frame to the appropriate provider."""
        try:
            # Route audio to appropriate provider
            channel_id = self.conn_to_channel.get(conn_id)
            if channel_id:
                call_data = self.active_calls.get(channel_id)
                if not call_data:
                    logger.warning("No active call data for audio frame", 
                                   conn_id=conn_id, channel_id=channel_id)
                    return
                provider = call_data.get('provider')
                if provider:
                    asyncio.create_task(provider.send_audio(frame))
                else:
                    logger.warning("No provider found for audio frame", 
                                   conn_id=conn_id, channel_id=channel_id)
            else:
                # Headless mapping by conn_id
                session = self.headless_sessions.get(conn_id)
                if not session:
                    logger.warning("No headless session for audio frame", 
                                   conn_id=conn_id)
                    return
                provider = session.get('provider')
                if provider:
                    asyncio.create_task(provider.send_audio(frame))
                else:
                    logger.warning("No headless provider for audio frame", 
                                   conn_id=conn_id)
        except Exception as e:
            logger.error("Error routing audio frame", 
                         conn_id=conn_id, error=str(e), exc_info=True)

    async def _start_health_server(self):
        """Start a minimal health endpoint exposing engine status."""
        async def handle_health(request):
            try:
                providers = {}
                for name, prov in self.providers.items():
                    ready = False
                    try:
                        if hasattr(prov, 'is_ready'):
                            ready = bool(prov.is_ready())
                    except Exception:
                        ready = False
                    providers[name] = {"ready": ready}
                data = {
                    "ari_connected": bool(self.ari_client and self.ari_client.running),
                    "audiosocket_listening": bool(getattr(self, 'audiosocket_server', None) and getattr(self.audiosocket_server, '_server', None)),
                    "active_calls": len(self.active_calls),
                    "providers": providers,
                }
                return web.json_response(data)
            except Exception:
                return web.json_response({"error": "health handler failed"}, status=500)

        app = web.Application()
        app.router.add_get('/health', handle_health)
        self._health_runner = web.AppRunner(app)
        await self._health_runner.setup()
        site = web.TCPSite(self._health_runner, host=os.getenv('HEALTH_HOST', '0.0.0.0'), port=int(os.getenv('HEALTH_PORT', '15000')))
        await site.start()
        logger.info("Health endpoint started", host=os.getenv('HEALTH_HOST', '0.0.0.0'), port=os.getenv('HEALTH_PORT', '15000'))

    async def _audiosocket_keepalive(self, conn_id: str):
        """Periodically send a short PCM16@8k silence frame to keep AudioSocket alive."""
        try:
            try:
                interval_ms = int(getattr(self.config.streaming, 'keepalive_ms', 10000))
            except Exception:
                interval_ms = 10000
            # Prepare a 20ms silence frame at 8k mono, PCM16LE (320 bytes)
            rate = 8000
            chunk_ms = 20
            samples = int(rate * (chunk_ms / 1000.0))
            silence = b"\x00\x00" * samples
            # Send one immediately upon bind to avoid initial idle gap
            try:
                await self.audiosocket_server.send_audio(conn_id, silence)
                logger.debug("Sent initial AudioSocket keepalive", conn_id=conn_id, bytes=len(silence))
            except Exception:
                logger.debug("Initial keepalive send failed", conn_id=conn_id, exc_info=True)
            while True:
                await asyncio.sleep(max(0.05, interval_ms / 1000.0))
                try:
                    if conn_id not in self.conn_to_channel and conn_id not in self.headless_sessions:
                        break
                    await self.audiosocket_server.send_audio(conn_id, silence)
                except Exception:
                    logger.debug("Keepalive send failed", conn_id=conn_id, exc_info=True)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Keepalive task error", conn_id=conn_id, exc_info=True)

    async def on_provider_event(self, event: Dict[str, Any]):
        """Callback for providers to send events back to the engine."""
        try:
            event_type = event.get("type")
            logger.debug("Received provider event", event_type=event_type, event_keys=list(event.keys()))
            
            if event_type == "AgentAudio":
                # Handle audio data from the provider - now we need to play it back
                audio_data = event.get("data")
                call_id = event.get("call_id")
                if audio_data:
                    # Prefer streaming over AudioSocket only when explicitly enabled
                    if self.config.audio_transport == 'audiosocket' and self.config.downstream_mode == 'stream':
                        sent = False
                        # Headless session routing: call_id equals conn_id
                        if call_id and call_id in self.headless_sessions:
                            conn_id = call_id
                            rate = 8000
                            # AudioSocket expects PCM16LE@8k - no conversion needed
                            out_bytes = audio_data
                            try:
                                await self.audiosocket_server.send_audio(conn_id, out_bytes)
                                logger.info("Streamed provider audio over AudioSocket (headless)", conn_id=conn_id, bytes=len(out_bytes), fmt='slin16', rate=rate)
                                # Update headless state
                                hs = self.headless_sessions.get(conn_id, {})
                                if hs.get('conversation_state') in ('greeting', 'processing'):
                                    hs['conversation_state'] = 'listening'
                                sent = True
                            except Exception:
                                logger.debug("Error streaming headless audio over AudioSocket", exc_info=True)
                        if not sent:
                            for channel_id, call_data in self.active_calls.items():
                                conn_id = self.channel_to_conn.get(channel_id)
                                if not conn_id:
                                    continue
                                # Determine negotiated format
                                fmt = 'ulaw'
                                rate = 8000
                                try:
                                    info = self.audiosocket_server.get_connection_info(conn_id)
                                    if info.get('format'):
                                        fmt = info['format']
                                    if info.get('rate'):
                                        rate = int(info['rate'])
                                except Exception:
                                    pass
                                try:
                                    # AudioSocket expects PCM16LE@8k - no conversion needed
                                    out_bytes = audio_data
                                    # Send downstream over socket
                                    await self.audiosocket_server.send_audio(conn_id, out_bytes)
                                    logger.debug("Streamed provider audio over AudioSocket", channel_id=channel_id, bytes=len(out_bytes), fmt=fmt, rate=rate)
                                except Exception:
                                    logger.debug("Error streaming audio over AudioSocket; falling back to ARI", exc_info=True)
                                    await self._play_audio_via_snoop(channel_id, audio_data)
                else:
                    # File-based playback via ARI (default path) - use bridge playback
                    for channel_id, call_data in self.active_calls.items():
                        await self._play_audio_via_bridge(channel_id, audio_data)
                        logger.info(f"🔊 AUDIO OUTPUT - Sent {len(audio_data)} bytes to call channel {channel_id}")
                        
                        # Update conversation state after playing response
                        conversation_state = call_data.get('conversation_state')
                        if conversation_state == 'greeting':
                            # First response after greeting - transition to listening
                            call_data['conversation_state'] = 'listening'
                            logger.info("Greeting completed, now listening for conversation", channel_id=channel_id)
                        elif conversation_state == 'processing':
                            # Response to user input - transition back to listening
                            call_data['conversation_state'] = 'listening'
                            logger.info("Response played, listening for next user input", channel_id=channel_id)
                            
                            # Cancel provider timeout task since we got a response
                            if call_data.get('provider_timeout_task') and not call_data['provider_timeout_task'].done():
                                call_data['provider_timeout_task'].cancel()
                                logger.debug("Cancelled provider timeout task - response received", channel_id=channel_id)
            elif event_type == "Transcription":
                # Handle transcription data
                text = event.get("text", "")
                logger.info("Received transcription from provider", text=text, text_length=len(text))
            elif event_type == "Error":
                # Handle provider errors
                error_msg = event.get("message", "Unknown provider error")
                logger.error("Provider reported error", error=error_msg, event=event)
            else:
                logger.debug("Unhandled provider event", event_type=event_type, event_keys=list(event.keys()))
        except Exception as e:
            logger.error("Error in provider event handler", event_type=event.get("type"), error=str(e), exc_info=True)

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

    async def _handle_channel_destroyed(self, event_data: dict):
        """Handle a channel being destroyed (caller hung up)."""
        channel_id = event_data.get('channel', {}).get('id')
        cause = event_data.get('cause', 'unknown')
        cause_txt = event_data.get('cause_txt', 'unknown')
        
        logger.info("Channel destroyed event received", 
                   channel_id=channel_id, 
                   cause=cause, 
                   cause_txt=cause_txt)
        
        # Immediately remove from active calls to prevent playback attempts
        if channel_id in self.active_calls:
            logger.debug("Channel was active - cleaning up immediately", channel_id=channel_id)
            await self._cleanup_call(channel_id)
        else:
            logger.debug("Channel was not in active calls", channel_id=channel_id)

    async def _cleanup_call(self, channel_id: str):
        """Cleanup resources associated with a call."""
        logger.debug("Starting call cleanup", channel_id=channel_id)
        
        if channel_id in self.active_calls:
            call_data = self.active_calls[channel_id]
            logger.debug("Call found in active calls", channel_id=channel_id, call_data_keys=list(call_data.keys()))
            
            # Cancel any pending timeout tasks
            timeout_task = call_data.get('timeout_task')
            if timeout_task and not timeout_task.done():
                timeout_task.cancel()
                logger.debug("Cancelled timeout task", channel_id=channel_id)
            
            # Cancel provider timeout task
            provider_timeout_task = call_data.get('provider_timeout_task')
            if provider_timeout_task and not provider_timeout_task.done():
                provider_timeout_task.cancel()
                logger.debug("Cancelled provider timeout task", channel_id=channel_id)
            
            provider = call_data.get("provider")
            if provider:
                logger.debug("Stopping provider session", channel_id=channel_id)
                await provider.stop_session()
                
            # Close bound AudioSocket connection if any
            # CRITICAL FIX: Handle new mapping structure where AudioSocket is bound to Local channel
            conn_id = None
            
            # First, try to find AudioSocket connection via Local channel
            if channel_id in self.caller_channels:
                local_channel_id = self.caller_channels[channel_id].get("local_channel_id")
                if local_channel_id:
                    conn_id = self.channel_to_conn.pop(local_channel_id, None)
                    logger.debug("🎯 CLEANUP - Found AudioSocket connection via Local channel", 
                               caller_channel_id=channel_id,
                               local_channel_id=local_channel_id,
                               conn_id=conn_id)
            
            # Fallback: try direct mapping (for backward compatibility)
            if not conn_id:
                conn_id = self.channel_to_conn.pop(channel_id, None)
                logger.debug("🎯 CLEANUP - Using direct channel mapping", 
                           channel_id=channel_id,
                           conn_id=conn_id)
            
            if conn_id:
                logger.debug("Closing AudioSocket connection", channel_id=channel_id, conn_id=conn_id)
                self.conn_to_channel.pop(conn_id, None)
                self.conn_to_caller.pop(conn_id, None)  # Clean up caller mapping
                # Cancel keepalive task early
                try:
                    t = self._keepalive_tasks.pop(conn_id, None)
                    if t and not t.done():
                        t.cancel()
                except Exception:
                    logger.debug("Keepalive cancel failed during cleanup", conn_id=conn_id, exc_info=True)
                if hasattr(self, 'audiosocket_server') and self.audiosocket_server:
                    try:
                        await self.audiosocket_server.close_connection(conn_id)
                        logger.debug("AudioSocket connection closed", conn_id=conn_id)
                    except Exception:
                        logger.debug("Error closing AudioSocket connection", conn_id=conn_id, exc_info=True)
            
            
            # Clean up local channel if it exists
            local_channel_id = self.local_channels.pop(channel_id, None)
            if local_channel_id:
                logger.debug("Hanging up local channel", channel_id=channel_id, local_channel_id=local_channel_id)
                try:
                    await self.ari_client.hangup_channel(local_channel_id)
                    logger.debug("Local channel hung up successfully", local_channel_id=local_channel_id)
                except Exception as e:
                    logger.warning("Failed to hang up local channel", 
                                 local_channel_id=local_channel_id, 
                                 error=str(e))
            
            # Stop any ongoing Local channel discovery loop
            discovery_task = call_data.get('discovery_task')
            if discovery_task and not discovery_task.done():
                discovery_task.cancel()
                logger.debug("Cancelled Local channel discovery task", channel_id=channel_id)

            # Clean up uuid_ext mapping
            try:
                # Remove any uuid_ext that maps to this channel_id
                for k, v in list(self.uuidext_to_channel.items()):
                    if v == channel_id:
                        self.uuidext_to_channel.pop(k, None)
            except Exception:
                logger.debug("Error cleaning uuidext mapping", channel_id=channel_id, exc_info=True)
            
            # Clean up bridge if it exists
            bridge_id = self.bridges.pop(channel_id, None)
            if bridge_id:
                logger.debug("Destroying bridge", channel_id=channel_id, bridge_id=bridge_id)
                try:
                    await self.ari_client.send_command("DELETE", f"bridges/{bridge_id}")
                    logger.debug("Bridge destroyed successfully", bridge_id=bridge_id)
                except Exception as e:
                    logger.warning("Failed to destroy bridge", bridge_id=bridge_id, error=str(e))
            
            # Clean up any remaining audio files for this call
            logger.debug("Cleaning up audio files", channel_id=channel_id)
            await self.ari_client.cleanup_call_files(channel_id)
            
            # Clean up new caller channel tracking
            if channel_id in self.caller_channels:
                caller_data = self.caller_channels.pop(channel_id, None)
                if caller_data:
                    local_channel_id = caller_data.get('local_channel_id')
                    if local_channel_id:
                        # Clean up pending mapping
                        self.pending_local_channels.pop(local_channel_id, None)
                        logger.debug("Cleaned up caller channel data", 
                                   caller_channel_id=channel_id, 
                                   local_channel_id=local_channel_id)
            
            # Clean up pending Local channel mappings
            for local_id, caller_id in list(self.pending_local_channels.items()):
                if caller_id == channel_id:
                    self.pending_local_channels.pop(local_id, None)
                    logger.debug("Cleaned up pending Local channel mapping", 
                               local_channel_id=local_id, 
                               caller_channel_id=caller_id)

            # Remove from active calls (with safety check for race conditions)
            if channel_id in self.active_calls:
                del self.active_calls[channel_id]
                logger.info("Call resources cleaned up successfully", channel_id=channel_id)
            else:
                logger.debug("Channel already removed from active calls", channel_id=channel_id)
            
            # Also clean up the other channel ID if it exists
            call_data = self.active_calls.get(channel_id)
            if call_data:
                local_channel_id = call_data.get('local_channel_id')
                caller_channel_id = call_data.get('caller_channel_id')
                
                if local_channel_id and local_channel_id != channel_id and local_channel_id in self.active_calls:
                    del self.active_calls[local_channel_id]
                    logger.debug("Removed Local channel from active calls", channel_id=local_channel_id)
                
                if caller_channel_id and caller_channel_id != channel_id and caller_channel_id in self.active_calls:
                    del self.active_calls[caller_channel_id]
                    logger.debug("Removed caller channel from active calls", channel_id=caller_channel_id)
        else:
            logger.debug("Channel not found in active calls", channel_id=channel_id)
            logger.debug("No active call found for cleanup", channel_id=channel_id)

    async def _send_test_tone_over_socket(self, conn_id: str, ms: int = 300):
        """Send a short test tone over AudioSocket (PCM16LE@8k framed) to verify downstream."""
        try:
            rate = 8000
            duration_sec = ms / 1000.0
            freq = 440.0
            import math
            samples = int(rate * duration_sec)
            pcm = bytearray()
            for n in range(samples):
                val = int(0.2 * 32767 * math.sin(2 * math.pi * freq * (n / rate)))
                pcm.extend(val.to_bytes(2, 'little', signed=True))
            await self.audiosocket_server.send_audio(conn_id, bytes(pcm))
            logger.info("Sent test tone over AudioSocket", conn_id=conn_id, fmt='slin16', rate=rate, ms=ms)
        except Exception:
            logger.debug("Error sending test tone", exc_info=True)

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

    async def _stream_audio_via_audiosocket(self, channel_id: str, audio_data: bytes):
        """Stream audio via AudioSocket connection instead of file-based playback."""
        try:
            # CRITICAL FIX: Find the AudioSocket connection for this channel
            # channel_id is the caller channel, but we need to find the Local channel's connection
            conn_id = None
            
            # First, try to find the Local channel for this caller
            if channel_id in self.caller_channels:
                local_channel_id = self.caller_channels[channel_id].get("local_channel_id")
                if local_channel_id:
                    conn_id = self.channel_to_conn.get(local_channel_id)
                    logger.info("🎯 AUDIOSOCKET TTS - Found Local channel for caller", 
                               caller_channel_id=channel_id,
                               local_channel_id=local_channel_id,
                               conn_id=conn_id)
            
            # Fallback: try direct mapping (for backward compatibility)
            if not conn_id:
                conn_id = self.channel_to_conn.get(channel_id)
                logger.info("🎯 AUDIOSOCKET TTS - Using direct channel mapping", 
                           channel_id=channel_id,
                           conn_id=conn_id)
            
            if not conn_id:
                logger.error("🎯 AUDIOSOCKET TTS - No AudioSocket connection found for channel", 
                           channel_id=channel_id,
                           caller_channels=list(self.caller_channels.keys()),
                           channel_to_conn_mappings=list(self.channel_to_conn.keys()))
                # Fallback to file-based playback
                await self.ari_client.play_audio_response(channel_id, audio_data)
                return
            
            logger.info("🎯 AUDIOSOCKET TTS - Streaming audio via AudioSocket", 
                       channel_id=channel_id, 
                       conn_id=conn_id,
                       audio_size=len(audio_data))
            
            # Convert ulaw to PCM16LE for AudioSocket
            # TTS generates ulaw, but AudioSocket expects PCM16LE@8kHz
            pcm_data = self._convert_ulaw_to_pcm16le(audio_data)
            
            # Stream audio in chunks via AudioSocket
            chunk_size = 320  # 20ms at 8kHz PCM16LE (320 bytes)
            for i in range(0, len(pcm_data), chunk_size):
                chunk = pcm_data[i:i + chunk_size]
                if len(chunk) < chunk_size:
                    # Pad last chunk with silence
                    chunk += b'\x00\x00' * ((chunk_size - len(chunk)) // 2)
                
                await self.audiosocket_server.send_audio(conn_id, chunk)
                
                # Small delay to simulate real-time streaming
                await asyncio.sleep(0.02)  # 20ms delay
            
            logger.info("🎯 AUDIOSOCKET TTS - ✅ Audio streamed successfully", 
                       channel_id=channel_id, 
                       conn_id=conn_id,
                       total_chunks=(len(pcm_data) + chunk_size - 1) // chunk_size)
            
        except Exception as e:
            logger.error("🎯 AUDIOSOCKET TTS - Failed to stream audio via AudioSocket", 
                        channel_id=channel_id, 
                        error=str(e), exc_info=True)
            # Fallback to file-based playback
            await self.ari_client.play_audio_response(channel_id, audio_data)

    def _convert_ulaw_to_pcm16le(self, ulaw_data: bytes) -> bytes:
        """Convert ulaw audio data to PCM16LE format for AudioSocket."""
        try:
            import audioop
            # Convert ulaw to linear PCM (16-bit signed)
            pcm_data = audioop.ulaw2lin(ulaw_data, 2)  # 2 bytes per sample
            logger.debug("Converted ulaw to PCM16LE", 
                        ulaw_bytes=len(ulaw_data), 
                        pcm_bytes=len(pcm_data))
            return pcm_data
        except Exception as e:
            logger.error("Failed to convert ulaw to PCM16LE", error=str(e), exc_info=True)
            # Return silence as fallback
            return b'\x00\x00' * (len(ulaw_data) * 2)

    async def _play_audio_via_bridge(self, channel_id: str, audio_data: bytes):
        """Play audio via bridge to avoid interrupting AudioSocket capture."""
        # High-visibility debugging to verify method is called
        logger.info(f"✅✅✅ _play_audio_via_bridge successfully called for channel {channel_id} ✅✅✅")
        
        bridge_id = self.bridges.get(channel_id)
        if not bridge_id:
            logger.error("❌❌❌ No bridge found for channel {channel_id} ❌❌❌")
            # Fallback to direct channel playback
            await self.ari_client.play_audio_response(channel_id, audio_data)
            return

        logger.info("Playing audio via bridge", 
                   channel_id=channel_id, 
                   bridge_id=bridge_id,
                   audio_size=len(audio_data))
        
        try:
            # Save audio to temporary file and play on bridge
            unique_filename = f"response-{uuid.uuid4()}.ulaw"
            container_path = f"/mnt/asterisk_media/ai-generated/{unique_filename}"
            asterisk_media_uri = f"sound:ai-generated/{unique_filename[:-5]}"

            # Write audio file
            with open(container_path, "wb") as f:
                f.write(audio_data)
            
            # Change ownership to asterisk user
            try:
                asterisk_uid = 995
                asterisk_gid = 995
                os.chown(container_path, asterisk_uid, asterisk_gid)
            except Exception as e:
                logger.warning("Failed to change file ownership", path=container_path, error=str(e))

            # Play on bridge
            await self.ari_client.send_command("POST", f"bridges/{bridge_id}/play", 
                                             data={"media": asterisk_media_uri})
            logger.info("Audio played on bridge successfully", bridge_id=bridge_id, media_uri=asterisk_media_uri)
            
        except Exception as e:
            logger.error("Failed to play audio via bridge, falling back to direct playback",
                        channel_id=channel_id, 
                        bridge_id=bridge_id,
                        error=str(e), exc_info=True)
            # Fallback to direct channel playback
            await self.ari_client.play_audio_response(channel_id, audio_data)


async def main():
    configure_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))
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
