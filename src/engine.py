import asyncio
import math
import os
import random
import signal
import struct
import time
import uuid
import audioop
import base64
from collections import deque
from typing import Dict, Any, Optional, List

# Simple audio capture system removed - not used in production

# WebRTC VAD for robust speech detection
try:
    import webrtcvad  # pyright: ignore[reportMissingImports]
    WEBRTC_VAD_AVAILABLE = True
except ImportError:
    WEBRTC_VAD_AVAILABLE = False
    webrtcvad = None

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .ari_client import ARIClient
from aiohttp import web
from pydantic import ValidationError

from .config import (
    AppConfig,
    load_config,
    LocalProviderConfig,
    DeepgramProviderConfig,
)
from .logging_config import get_logger
from .rtp_server import RTPServer
from .audio.audiosocket_server import AudioSocketServer
from .providers.base import AIProviderInterface
from .providers.deepgram import DeepgramProvider
from .providers.local import LocalProvider
from .core import SessionStore, PlaybackManager, ConversationCoordinator
from .core.streaming_playback_manager import StreamingPlaybackManager
from .core.models import CallSession

logger = get_logger(__name__)

class AudioFrameProcessor:
    """Processes audio in 40ms frames to prevent voice queue backlog."""
    
    def __init__(self, frame_size: int = 320):  # 40ms at 8kHz = 320 samples
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
    
    def __init__(self, speech_threshold: float = 0.3, silence_frames: int = 10):
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
        # Set engine reference for event propagation
        self.ari_client.engine = self
        
        # Initialize core components
        self.session_store = SessionStore()
        self.conversation_coordinator = ConversationCoordinator(self.session_store)
        self.playback_manager = PlaybackManager(
            self.session_store,
            self.ari_client,
            conversation_coordinator=self.conversation_coordinator,
        )
        self.conversation_coordinator.set_playback_manager(self.playback_manager)
        
        # Initialize streaming playback manager
        streaming_config = {}
        if hasattr(config, 'streaming') and config.streaming:
            streaming_config = {
                'sample_rate': config.streaming.sample_rate,
                'jitter_buffer_ms': config.streaming.jitter_buffer_ms,
                'keepalive_interval_ms': config.streaming.keepalive_interval_ms,
                'connection_timeout_ms': config.streaming.connection_timeout_ms,
                'fallback_timeout_ms': config.streaming.fallback_timeout_ms,
                'chunk_size_ms': config.streaming.chunk_size_ms,
            }
        # Debug/diagnostics: allow broadcasting outbound frames to all AudioSocket conns
        try:
            streaming_config['audiosocket_broadcast_debug'] = bool(int(os.getenv('AUDIOSOCKET_BROADCAST_DEBUG', '0')))
        except Exception:
            streaming_config['audiosocket_broadcast_debug'] = False
        
        self.streaming_playback_manager = StreamingPlaybackManager(
            self.session_store,
            self.ari_client,
            conversation_coordinator=self.conversation_coordinator,
            fallback_playback_manager=self.playback_manager,
            streaming_config=streaming_config,
            audio_transport=self.config.audio_transport,
        )
        
        self.providers: Dict[str, AIProviderInterface] = {}
        self.conn_to_channel: Dict[str, str] = {}
        self.channel_to_conn: Dict[str, str] = {}
        self.conn_to_caller: Dict[str, str] = {}  # conn_id -> caller_channel_id
        self.audio_socket_server: Optional[AudioSocketServer] = None
        self.audiosocket_conn_to_ssrc: Dict[str, int] = {}
        self.audiosocket_resample_state: Dict[str, Optional[tuple]] = {}
        self.pending_channel_for_bind: Optional[str] = None
        # Support duplicate Local ;1/;2 AudioSocket connections per call
        self.channel_to_conns: Dict[str, set] = {}
        self.audiosocket_primary_conn: Dict[str, str] = {}
        # Audio buffering for better playback quality
        self.audio_buffers: Dict[str, bytes] = {}
        self.buffer_size = 1600  # 200ms of audio at 8kHz (1600 bytes of ulaw)
        self.rtp_server: Optional[Any] = None
        self.headless_sessions: Dict[str, Dict[str, Any]] = {}
        # Bridge and Local channel tracking for Local Channel Bridge pattern
        self.bridges: Dict[str, str] = {}  # channel_id -> bridge_id
        # Frame processing and VAD for optimized audio handling
        self.frame_processors: Dict[str, AudioFrameProcessor] = {}  # conn_id -> processor
        self.vad_detectors: Dict[str, VoiceActivityDetector] = {}  # conn_id -> VAD
        self.local_channels: Dict[str, str] = {}  # channel_id -> legacy local_channel_id
        self.audiosocket_channels: Dict[str, str] = {}  # call_id -> audiosocket_channel_id
        
        # WebRTC VAD for robust speech detection
        self.webrtc_vad = None
        if WEBRTC_VAD_AVAILABLE:
            try:
                # Use VAD configuration section
                aggressiveness = config.vad.webrtc_aggressiveness
                self.webrtc_vad = webrtcvad.Vad(aggressiveness)
                logger.info("🎤 WebRTC VAD initialized", aggressiveness=aggressiveness)
            except Exception as e:
                logger.warning("🎤 WebRTC VAD initialization failed", error=str(e))
                self.webrtc_vad = None
        else:
            logger.warning("🎤 WebRTC VAD not available - install py-webrtcvad")
        # Map our synthesized UUID extension to the real ARI caller channel id
        self.uuidext_to_channel: Dict[str, str] = {}
        # NEW: Caller channel tracking for dual StasisStart handling
        self.pending_local_channels: Dict[str, str] = {}  # local_channel_id -> caller_channel_id
        self.pending_audiosocket_channels: Dict[str, str] = {}  # audiosocket_channel_id -> caller_channel_id
        self._audio_rx_debug: Dict[str, int] = {}
        self._keepalive_tasks: Dict[str, asyncio.Task] = {}
        # Active playbacks are now managed by SessionStore
        # ExternalMedia to caller channel mapping is now managed by SessionStore
        # SSRC to caller channel mapping for RTP audio routing
        self.ssrc_to_caller: Dict[int, str] = {}  # ssrc -> caller_channel_id
        # Health server runner
        self._health_runner: Optional[web.AppRunner] = None

        # Event handlers
        self.ari_client.on_event("StasisStart", self._handle_stasis_start)
        self.ari_client.on_event("StasisEnd", self._handle_stasis_end)
        self.ari_client.on_event("ChannelDestroyed", self._handle_channel_destroyed)
        self.ari_client.on_event("ChannelDtmfReceived", self._handle_dtmf_received)
        self.ari_client.on_event("ChannelVarset", self._handle_channel_varset)

    async def on_rtp_packet(self, packet: bytes, addr: tuple):
        """Handle incoming RTP packets from the UDP server."""
        # ARCHITECT FIX: This legacy bypass fragments STT and bypasses VAD
        # Log warning and disable to ensure all audio goes through VAD
        logger.warning("🚨 LEGACY RTP BYPASS - This method bypasses VAD and fragments STT", 
                      packet_len=len(packet), 
                      addr=addr)
        
        # Disable this bypass to prevent STT fragmentation
        # All audio should go through RTPServer -> _on_rtp_audio -> _process_rtp_audio_with_vad
        return
        
        # LEGACY CODE (disabled):
        # if self.active_calls:
        #     channel_id = list(self.active_calls.keys())[0]
        #     call_data = self.active_calls[channel_id]
        #     provider = call_data.get("provider")
        #     if provider:
        #         # The first 12 bytes of an RTP packet are the header. The rest is payload.
        #         audio_payload = packet[12:]
        #         await provider.send_audio(audio_payload)

    async def _on_ari_event(self, event: Dict[str, Any]):
        """Default event handler for unhandled ARI events."""
        logger.debug("Received unhandled ARI event", event_type=event.get("type"), event=event)

    async def _save_session(self, session: CallSession, *, new: bool = False) -> None:
        """Persist session updates and keep coordinator metrics in sync."""
        await self.session_store.upsert_call(session)
        if self.conversation_coordinator:
            if new:
                await self.conversation_coordinator.register_call(session)
            else:
                await self.conversation_coordinator.sync_from_session(session)

    async def start(self):
        """Connect to ARI and start the engine."""
        await self._load_providers()
        # Log transport and downstream modes
        logger.info("Runtime modes", audio_transport=self.config.audio_transport, downstream_mode=self.config.downstream_mode)

        # Prepare AudioSocket transport
        if self.config.audio_transport == "audiosocket":
            if not self.config.audiosocket:
                raise ValueError("AudioSocket configuration not found")

            host = self.config.audiosocket.host
            port = self.config.audiosocket.port
            self.audio_socket_server = AudioSocketServer(
                host=host,
                port=port,
                on_uuid=self._audiosocket_handle_uuid,
                on_audio=self._audiosocket_handle_audio,
                on_disconnect=self._audiosocket_handle_disconnect,
                on_dtmf=self._audiosocket_handle_dtmf,
            )
            await self.audio_socket_server.start()
            # Configure streaming manager with AudioSocket format expected by dialplan
            as_format = None
            try:
                if self.config.audiosocket and hasattr(self.config.audiosocket, 'format'):
                    as_format = self.config.audiosocket.format
            except Exception:
                as_format = None
            self.streaming_playback_manager.set_transport(
                audio_transport=self.config.audio_transport,
                audiosocket_server=self.audio_socket_server,
                audiosocket_format=as_format,
            )

        # Prepare RTP server for ExternalMedia transport
        if self.config.audio_transport == "externalmedia":
            if not self.config.external_media:
                raise ValueError("ExternalMedia configuration not found")
            
            rtp_host = self.config.external_media.rtp_host
            rtp_port = self.config.external_media.rtp_port
            codec = self.config.external_media.codec
            
            # Create RTP server with callback to route audio to providers
            self.rtp_server = RTPServer(
                host=rtp_host,
                port=rtp_port,
                engine_callback=self._on_rtp_audio,
                codec=codec
            )
            
            # Start RTP server
            await self.rtp_server.start()
            logger.info("RTP server started for ExternalMedia transport", 
                       host=rtp_host, port=rtp_port, codec=codec)
            self.streaming_playback_manager.set_transport(
                rtp_server=self.rtp_server,
                audio_transport=self.config.audio_transport,
            )

        # Start lightweight health endpoint
        try:
            asyncio.create_task(self._start_health_server())
        except Exception:
            logger.debug("Health server failed to start", exc_info=True)
        await self.ari_client.connect()
        # Add PlaybackFinished event handler for timing control
        self.ari_client.add_event_handler("PlaybackFinished", self._on_playback_finished)
        asyncio.create_task(self.ari_client.start_listening())
        logger.info("Engine started and listening for calls.")

    async def stop(self):
        """Disconnect from ARI and stop the engine."""
        # Clean up all sessions from SessionStore
        sessions = await self.session_store.get_all_sessions()
        for session in sessions:
            await self._cleanup_call(session.call_id)
        await self.ari_client.disconnect()
        # Stop RTP server if running
        if hasattr(self, 'rtp_server') and self.rtp_server:
            await self.rtp_server.stop()
        # Stop health server
        if self.audio_socket_server:
            await self.audio_socket_server.stop()
            self.audio_socket_server = None
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
                    
                    # Initialize persistent connection for local provider
                    if hasattr(provider, 'initialize'):
                        await provider.initialize()
                        logger.info(f"Provider '{name}' connection initialized.")
                elif name == "deepgram":
                    deepgram_config = self._build_deepgram_config(provider_config_data)
                    if not deepgram_config:
                        continue

                    # Validate OpenAI dependency for Deepgram
                    if not self.config.llm.api_key:
                        logger.error("Deepgram provider requires OpenAI API key in LLM config")
                        continue

                    provider = DeepgramProvider(deepgram_config, self.config.llm, self.on_provider_event)
                    self.providers[name] = provider
                    logger.info("Provider 'deepgram' loaded successfully with OpenAI LLM dependency.")
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

    def _is_audiosocket_channel(self, channel: dict) -> bool:
        """Check if this is an AudioSocket channel (native channel interface)."""
        channel_name = channel.get('name', '')
        return channel_name.startswith('AudioSocket/')

    def _is_external_media_channel(self, channel: dict) -> bool:
        """Check if this is an ExternalMedia channel"""
        channel_name = channel.get('name', '')
        return channel_name.startswith('UnicastRTP/')

    async def _find_caller_for_local(self, local_channel_id: str) -> Optional[str]:
        """Find the caller channel that corresponds to this Local channel."""
        # Check if we have a pending Local channel mapping
        if local_channel_id in self.pending_local_channels:
            return self.pending_local_channels[local_channel_id]
        
        # Fallback: search through SessionStore
        sessions = await self.session_store.get_all_sessions()
        for session in sessions:
            if session.local_channel_id == local_channel_id:
                return session.caller_channel_id
        
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
            # This is the Local channel entering Stasis - legacy path
            logger.info("🎯 HYBRID ARI - Local channel entered Stasis",
                       channel_id=channel_id,
                       channel_name=channel_name)
            # Now add the Local channel to the bridge
            await self._handle_local_stasis_start_hybrid(channel_id, channel)
        elif self._is_audiosocket_channel(channel):
            logger.info(
                "🎯 HYBRID ARI - AudioSocket channel entered Stasis",
                channel_id=channel_id,
                channel_name=channel_name,
            )
            await self._handle_audiosocket_channel_stasis_start(channel_id, channel)
        elif self._is_external_media_channel(channel):
            # This is an ExternalMedia channel entering Stasis
            logger.info("🎯 EXTERNAL MEDIA - ExternalMedia channel entered Stasis", 
                       channel_id=channel_id,
                       channel_name=channel_name)
            await self._handle_external_media_stasis_start(channel_id, channel)
        else:
            logger.warning("🎯 HYBRID ARI - Unknown channel type in StasisStart", 
                          channel_id=channel_id, 
                          channel_name=channel_name)

    async def _handle_external_media_stasis_start(self, external_media_id: str, channel: dict):
        """Handle ExternalMedia channel entering Stasis."""
        try:
            # Find session by external_media_id
            session = await self.session_store.get_by_channel_id(external_media_id)
            if not session:
                # Fallback: search all sessions for external_media_id
                sessions = await self.session_store.get_all_sessions()
                for s in sessions:
                    if s.external_media_id == external_media_id:
                        session = s
                        break
            
            if not session:
                logger.warning("ExternalMedia channel entered Stasis but no caller found", 
                             external_media_id=external_media_id)
                return
            
            caller_channel_id = session.caller_channel_id
            
            # Add ExternalMedia channel to the bridge
            bridge_id = session.bridge_id
            if bridge_id:
                success = await self.ari_client.add_channel_to_bridge(bridge_id, external_media_id)
                if success:
                    logger.info("🎯 EXTERNAL MEDIA - ExternalMedia channel added to bridge", 
                               external_media_id=external_media_id,
                               bridge_id=bridge_id,
                               caller_channel_id=caller_channel_id)
                    
                    # Start the provider session for ExternalMedia
                    await self._start_provider_session_external_media(caller_channel_id, external_media_id)
                else:
                    logger.error("🎯 EXTERNAL MEDIA - Failed to add ExternalMedia channel to bridge", 
                               external_media_id=external_media_id,
                               bridge_id=bridge_id)
            else:
                logger.error("ExternalMedia channel entered Stasis but no bridge found", 
                           external_media_id=external_media_id,
                           caller_channel_id=caller_channel_id)
                
        except Exception as e:
            logger.error("Error handling ExternalMedia StasisStart", 
                        external_media_id=external_media_id, 
                        error=str(e), 
                        exc_info=True)

    async def _handle_caller_stasis_start_hybrid(self, caller_channel_id: str, channel: dict):
        """Handle caller channel entering Stasis - Hybrid ARI approach."""
        caller_info = channel.get('caller', {})
        logger.info("🎯 HYBRID ARI - Caller channel entered Stasis", 
                    channel_id=caller_channel_id,
                    caller_name=caller_info.get('name'),
                    caller_number=caller_info.get('number'))
        
        # Check if call is already in progress
        existing_session = await self.session_store.get_by_call_id(caller_channel_id)
        if existing_session:
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
            self.bridges[caller_channel_id] = bridge_id
            
            # Step 4: Create CallSession and store in SessionStore
            session = CallSession(
                call_id=caller_channel_id,
                caller_channel_id=caller_channel_id,
                bridge_id=bridge_id,
                provider_name=self.config.default_provider,
                audio_capture_enabled=False,
                status="connected"
            )
            await self._save_session(session, new=True)
            logger.info("🎯 HYBRID ARI - Step 4: ✅ Caller session created and stored", 
                       channel_id=caller_channel_id, 
                       bridge_id=bridge_id)
            
            # Step 5: Create ExternalMedia channel or originate Local channel
            if self.config.audio_transport == "externalmedia":
                logger.info("🎯 EXTERNAL MEDIA - Step 5: Creating ExternalMedia channel", channel_id=caller_channel_id)
                external_media_id = await self._start_external_media_channel(caller_channel_id)
                if external_media_id:
                    # Update session with ExternalMedia ID
                    session.external_media_id = external_media_id
                    session.status = "external_media_created"
                    await self._save_session(session)
                    logger.info("🎯 EXTERNAL MEDIA - ExternalMedia channel created, session updated", 
                               channel_id=caller_channel_id, 
                               external_media_id=external_media_id)
                else:
                    logger.error("🎯 EXTERNAL MEDIA - Failed to create ExternalMedia channel", channel_id=caller_channel_id)
            else:
                logger.info("🎯 HYBRID ARI - Step 5: Originating AudioSocket channel", channel_id=caller_channel_id)
                await self._originate_audiosocket_channel_hybrid(caller_channel_id)
            
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
        caller_channel_id = await self._find_caller_for_local(local_channel_id)
        if not caller_channel_id:
            logger.error("🎯 HYBRID ARI - No caller found for Local channel", 
                        local_channel_id=local_channel_id)
            await self.ari_client.hangup_channel(local_channel_id)
            return
        
        # Check if caller channel exists and has a bridge
        session = await self.session_store.get_by_call_id(caller_channel_id)
        if not session:
            logger.error("🎯 HYBRID ARI - Caller channel not found for Local channel", 
                        local_channel_id=local_channel_id,
                        caller_channel_id=caller_channel_id)
            await self.ari_client.hangup_channel(local_channel_id)
            return
        
        bridge_id = session.bridge_id
        
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
                # Update session with Local channel info
                session.local_channel_id = local_channel_id
                session.status = "connected"
                await self._save_session(session)
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

    async def _handle_audiosocket_channel_stasis_start(self, audiosocket_channel_id: str, channel: dict):
        """Handle AudioSocket channel entering Stasis when using channel interface."""
        logger.info(
            "🎯 HYBRID ARI - Processing AudioSocket channel StasisStart",
            audiosocket_channel_id=audiosocket_channel_id,
            channel_name=channel.get('name'),
        )

        caller_channel_id = self.pending_audiosocket_channels.pop(audiosocket_channel_id, None)
        if not caller_channel_id:
            # Fallback lookup via SessionStore
            sessions = await self.session_store.get_all_sessions()
            for s in sessions:
                if getattr(s, 'audiosocket_channel_id', None) == audiosocket_channel_id:
                    caller_channel_id = s.caller_channel_id
                    break

        if not caller_channel_id:
            logger.error(
                "🎯 HYBRID ARI - No caller found for AudioSocket channel",
                audiosocket_channel_id=audiosocket_channel_id,
            )
            await self.ari_client.hangup_channel(audiosocket_channel_id)
            return

        session = await self.session_store.get_by_call_id(caller_channel_id)
        if not session:
            logger.error(
                "🎯 HYBRID ARI - Session missing for AudioSocket channel",
                audiosocket_channel_id=audiosocket_channel_id,
                caller_channel_id=caller_channel_id,
            )
            await self.ari_client.hangup_channel(audiosocket_channel_id)
            return

        bridge_id = session.bridge_id
        if not bridge_id:
            logger.error(
                "🎯 HYBRID ARI - No bridge available for AudioSocket channel",
                audiosocket_channel_id=audiosocket_channel_id,
                caller_channel_id=caller_channel_id,
            )
            await self.ari_client.hangup_channel(audiosocket_channel_id)
            return

        try:
            added = await self.ari_client.add_channel_to_bridge(bridge_id, audiosocket_channel_id)
            if not added:
                raise RuntimeError("Failed to add AudioSocket channel to bridge")

            logger.info(
                "🎯 HYBRID ARI - ✅ AudioSocket channel added to bridge",
                audiosocket_channel_id=audiosocket_channel_id,
                bridge_id=bridge_id,
                caller_channel_id=caller_channel_id,
            )

            session.audiosocket_channel_id = audiosocket_channel_id
            session.status = "audiosocket_channel_connected"
            await self._save_session(session)

            self.audiosocket_channels[caller_channel_id] = audiosocket_channel_id
            self.bridges[audiosocket_channel_id] = bridge_id

            if not session.provider_session_active:
                await self._start_provider_session_hybrid(caller_channel_id, audiosocket_channel_id)
        except Exception as exc:
            logger.error(
                "🎯 HYBRID ARI - Failed to process AudioSocket channel",
                audiosocket_channel_id=audiosocket_channel_id,
                caller_channel_id=caller_channel_id,
                error=str(exc),
                exc_info=True,
            )
            await self.ari_client.hangup_channel(audiosocket_channel_id)

    async def _handle_caller_stasis_start(self, caller_channel_id: str, channel: dict):
        """Handle caller channel entering Stasis - LEGACY (kept for reference)."""
        caller_info = channel.get('caller', {})
        logger.info("Caller channel entered Stasis", 
                    channel_id=caller_channel_id,
                    caller_name=caller_info.get('name'),
                    caller_number=caller_info.get('number'))
        
        # Check if call is already in progress
        existing_session = await self.session_store.get_by_call_id(caller_channel_id)
        if existing_session:
            logger.warning("Caller already in progress", channel_id=caller_channel_id)
            return
        
        try:
            # Answer the caller
            await self.ari_client.answer_channel(caller_channel_id)
            logger.info("Caller channel answered", channel_id=caller_channel_id)
            
            # Create session in SessionStore
            session = CallSession(
                call_id=caller_channel_id,
                caller_channel_id=caller_channel_id,
                provider_name=self.config.default_provider,
                status="waiting_for_local",
                audio_capture_enabled=False
            )
            await self._save_session(session, new=True)
            
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
            caller_channel_id = await self._find_caller_for_local(local_channel_id)
            if not caller_channel_id:
                logger.error("No caller found for Local channel", local_channel_id=local_channel_id)
                await self.ari_client.hangup_channel(local_channel_id)
                return
            
            # Update session with Local channel ID
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if session:
                session.local_channel_id = local_channel_id
                await self._save_session(session)
                self.local_channels[caller_channel_id] = local_channel_id
            
            # Create bridge and connect channels
            await self._create_bridge_and_connect(caller_channel_id, local_channel_id)
            
        except Exception as e:
            logger.error("Failed to handle Local StasisStart", 
                        local_channel_id=local_channel_id, 
                        error=str(e), exc_info=True)
            # Clean up both channels
            caller_channel_id = await self._find_caller_for_local(local_channel_id)
            if caller_channel_id:
                await self._cleanup_call(caller_channel_id)
            await self.ari_client.hangup_channel(local_channel_id)

    async def _originate_audiosocket_channel_hybrid(self, caller_channel_id: str):
        """Originate an AudioSocket channel using the native channel interface."""
        if not self.config.audiosocket:
            logger.error(
                "🎯 HYBRID ARI - AudioSocket config missing, cannot originate channel",
                caller_channel_id=caller_channel_id,
            )
            raise RuntimeError("AudioSocket configuration missing")

        audio_uuid = str(uuid.uuid4())
        host = self.config.audiosocket.host or "127.0.0.1"
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        port = self.config.audiosocket.port
        endpoint = f"AudioSocket/{host}:{port}/{audio_uuid}/c(slin)"

        orig_params = {
            "endpoint": endpoint,
            "app": self.config.asterisk.app_name,
            "timeout": "30",
            "channelVars": {
                "AUDIOSOCKET_UUID": audio_uuid,
            },
        }

        logger.info(
            "🎯 HYBRID ARI - Originating AudioSocket channel",
            caller_channel_id=caller_channel_id,
            endpoint=endpoint,
            audio_uuid=audio_uuid,
        )

        try:
            response = await self.ari_client.send_command("POST", "channels", params=orig_params)
            if response and response.get("id"):
                audiosocket_channel_id = response["id"]
                self.pending_audiosocket_channels[audiosocket_channel_id] = caller_channel_id
                self.uuidext_to_channel[audio_uuid] = caller_channel_id

                session = await self.session_store.get_by_call_id(caller_channel_id)
                if session:
                    session.audiosocket_uuid = audio_uuid
                    await self._save_session(session)
                else:
                    logger.warning(
                        "🎯 HYBRID ARI - Session not found while recording AudioSocket UUID",
                        caller_channel_id=caller_channel_id,
                    )

                logger.info(
                    "🎯 HYBRID ARI - AudioSocket channel originated",
                    caller_channel_id=caller_channel_id,
                    audiosocket_channel_id=audiosocket_channel_id,
                )
            else:
                raise RuntimeError("Failed to originate AudioSocket channel")
        except Exception as e:
            logger.error(
                "🎯 HYBRID ARI - AudioSocket channel originate failed",
                caller_channel_id=caller_channel_id,
                error=str(e),
                exc_info=True,
            )
            raise

    async def _originate_local_channel_hybrid(self, caller_channel_id: str):
        """Originate single Local channel - Dialplan approach."""
        # Generate UUID for channel binding
        audio_uuid = str(uuid.uuid4())
        # Originate Local channel directly to dialplan context
        local_endpoint = f"Local/{audio_uuid}@ai-agent-media-fork/n"
        
        orig_params = {
            "endpoint": local_endpoint,
            "extension": audio_uuid,  # Use UUID as extension
            "context": "ai-agent-media-fork",  # Specify the dialplan context
            "timeout": "30"
        }
        
        logger.info("🎯 DIALPLAN EXTERNALMEDIA - Originating ExternalMedia Local channel", 
                    endpoint=local_endpoint, 
                    caller_channel_id=caller_channel_id,
                    audio_uuid=audio_uuid)
        
        try:
            response = await self.ari_client.send_command("POST", "channels", params=orig_params)
            if response and response.get("id"):
                local_channel_id = response["id"]
                # Store mapping for ExternalMedia binding
                self.pending_local_channels[local_channel_id] = caller_channel_id
                self.uuidext_to_channel[audio_uuid] = caller_channel_id
                logger.info("🎯 DIALPLAN EXTERNALMEDIA - ExternalMedia Local channel originated", 
                           local_channel_id=local_channel_id, 
                           caller_channel_id=caller_channel_id,
                           audio_uuid=audio_uuid)
                
                # Store Local channel info - will be added to bridge when ExternalMedia connects
                session = await self.session_store.get_by_call_id(caller_channel_id)
                if session:
                    session.external_media_id = local_channel_id
                    await self._save_session(session)
                    logger.info("🎯 DIALPLAN EXTERNALMEDIA - ExternalMedia channel ready for connection", 
                               local_channel_id=local_channel_id,
                               caller_channel_id=caller_channel_id)
                else:
                    logger.error("🎯 DIALPLAN EXTERNALMEDIA - Caller channel not found for ExternalMedia channel", 
                               local_channel_id=local_channel_id,
                               caller_channel_id=caller_channel_id)
                    raise RuntimeError("Caller channel not found")
            else:
                raise RuntimeError("Failed to originate ExternalMedia Local channel")
        except Exception as e:
            logger.error("🎯 DIALPLAN EXTERNALMEDIA - ExternalMedia channel originate failed", 
                        caller_channel_id=caller_channel_id,
                        audio_uuid=audio_uuid,
                        error=str(e), exc_info=True)
            raise

    async def _originate_local_channel(self, caller_channel_id: str):
        """Originate Local channel for ExternalMedia - LEGACY (kept for reference)."""
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
            # Update session with bridge info
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if session:
                session.bridge_id = bridge_id
                session.status = "connected"
                await self._save_session(session)
            
            logger.info("Channels successfully bridged", 
                       bridge_id=bridge_id, 
                       caller_channel_id=caller_channel_id, 
                       local_channel_id=local_channel_id)
            
            # Start provider session and bind ExternalMedia
            await self._start_provider_session(caller_channel_id, local_channel_id)
            
        except Exception as e:
            logger.error("Failed to create bridge and connect channels", 
                        caller_channel_id=caller_channel_id, 
                        local_channel_id=local_channel_id, 
                        error=str(e), exc_info=True)
            await self._cleanup_call(caller_channel_id)

    def _build_default_vad_state(self, ssrc: int) -> Dict[str, Any]:
        """Return baseline VAD state for a call."""
        return {
            "state": "listening",
            "speaking": False,
            "speech_real_start_fired": False,
            "pre_roll_buffer": b"",
            "utterance_buffer": b"",
            "last_voice_ms": 0,
            "speech_start_ms": 0,
            "speech_duration_ms": 0,
            "silence_duration_ms": 0,
            "ssrc": ssrc,
            "frame_count": 0,
            "consecutive_speech_frames": 0,
            "consecutive_silence_frames": 0,
            "redemption_counter": 0,
            "speech_frame_count": 0,
            "noise_db_history": deque(maxlen=100),
            "noise_floor_db": -70.0,
            "tail_frames_remaining": 0,
            "last_utterance_end_ms": 0,
            "utterance_id": 0,
            "tts_playing": False,
            "tts_tokens": set(),
            "tts_active_count": 0,
            "webrtc_speech_frames": 0,
            "webrtc_silence_frames": 0,
            "webrtc_last_decision": False,
            "frame_buffer": b"",
        }

    def _ensure_vad_state_keys(self, session: CallSession, ssrc: int) -> Dict[str, Any]:
        """Ensure VAD state has the required bookkeeping before processing audio."""
        if not isinstance(session.vad_state, dict):
            logger.warning("VAD state replaced with non-dict, resetting", 
                           caller_channel_id=session.call_id,
                           vad_state_type=type(session.vad_state).__name__)
            session.vad_state = self._build_default_vad_state(ssrc)
            return session.vad_state

        required_keys = {
            "frame_buffer",
            "frame_count",
            "pre_roll_buffer",
            "utterance_buffer",
            "state",
            "consecutive_silence_frames",
        }

        missing_keys = [key for key in required_keys if key not in session.vad_state]
        if missing_keys:
            logger.warning("VAD state missing keys, patching defaults", 
                           caller_channel_id=session.call_id,
                           missing_keys=missing_keys,
                           existing_keys=list(session.vad_state.keys()))
            defaults = self._build_default_vad_state(ssrc)
            for key in missing_keys:
                session.vad_state[key] = defaults[key]

        frame_buffer = session.vad_state.get("frame_buffer")
        if not isinstance(frame_buffer, (bytes, bytearray)):
            logger.warning("VAD frame_buffer had unexpected type, resetting", 
                           caller_channel_id=session.call_id,
                           frame_buffer_type=type(frame_buffer).__name__ if frame_buffer is not None else "None")
            session.vad_state["frame_buffer"] = b""

        frame_count = session.vad_state.get("frame_count")
        if not isinstance(frame_count, int):
            logger.warning("VAD frame_count had unexpected type, resetting", 
                           caller_channel_id=session.call_id,
                           frame_count_type=type(frame_count).__name__ if frame_count is not None else "None")
            session.vad_state["frame_count"] = 0

        return session.vad_state

    async def _start_provider_session_hybrid(self, caller_channel_id: str, media_channel_id: str):
        """Start provider session - Hybrid ARI approach."""
        try:
            session = await self.session_store.get_by_call_id(caller_channel_id)
            provider_name = self.config.default_provider
            if session and session.provider_name in self.providers:
                provider_name = session.provider_name

            if session and session.provider_session_active:
                logger.info(
                    "🎯 HYBRID ARI - Provider session already active",
                    caller_channel_id=caller_channel_id,
                    provider=provider_name,
                )
                return

            logger.info(
                       "🎯 HYBRID ARI - Starting provider session",
                       media_channel_id=media_channel_id,
                       caller_channel_id=caller_channel_id,
                       provider=provider_name)

            provider = self.providers.get(provider_name)
            if not provider:
                logger.error("🎯 HYBRID ARI - Provider not found", provider=provider_name)
                return
            
            # Start provider session with canonical call_id (caller_channel_id)
            await provider.start_session(caller_channel_id)
            
            if session:
                # Update session metadata for observability
                session.provider_session_active = True
                session.status = "provider_started"
                await self._save_session(session)
                logger.info(
                    "🎯 HYBRID ARI - Session updated after provider start",
                    caller_channel_id=caller_channel_id,
                    media_channel_id=media_channel_id,
                    provider=provider_name,
                )
            else:
                logger.warning("🎯 HYBRID ARI - No session found for caller", caller_channel_id=caller_channel_id)
            
            logger.info("🎯 HYBRID ARI - ✅ Provider session started", 
                       media_channel_id=media_channel_id, 
                       caller_channel_id=caller_channel_id,
                       provider=provider_name)
            
            # ARCHITECT FIX: Audio capture will be enabled after greeting playback completes
            # via PlaybackFinished event handler, not immediately after setup
            logger.info("🎤 AUDIO CAPTURE - Will be enabled after greeting playback completes",
                       caller_channel_id=caller_channel_id)
            
            # Play initial greeting
            await self._play_initial_greeting_hybrid(caller_channel_id, media_channel_id)
            
        except Exception as e:
            logger.error("🎯 HYBRID ARI - Failed to start provider session", 
                        media_channel_id=media_channel_id, 
                        caller_channel_id=caller_channel_id,
                        error=str(e), exc_info=True)

    async def _play_initial_greeting_hybrid(self, caller_channel_id: str, media_channel_id: str):
        """Play initial greeting - Hybrid ARI approach with ExternalMedia streaming."""
        try:
            logger.info("🎯 HYBRID ARI - Playing initial greeting", 
                       caller_channel_id=caller_channel_id,
                       media_channel_id=media_channel_id)
            
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
                # Generate playback ID for token tracking
                playback_id = f"greeting:{caller_channel_id}:{int(time.time()*1000)}"
                
                # TTS gating is now handled by PlaybackManager through SessionStore
                # No need for manual gating here
                
                # Calculate dynamic fallback timer based on audio duration
                audio_duration_sec = len(audio_data) / 8000.0
                safety_margin_sec = 0.5  # 500ms safety margin
                fallback_delay = audio_duration_sec + safety_margin_sec
                
                # Get call_id from session
                session = await self.session_store.get_by_call_id(caller_channel_id)
                if session:
                    call_id = session.call_id
                    # Use PlaybackManager for greeting playback - it handles all gating logic
                    await self.playback_manager.play_audio(
                        call_id, 
                        audio_data, 
                        playback_type="greeting"
                    )
                else:
                    logger.error("Cannot play greeting - session not found", caller_channel_id=caller_channel_id)
                
                logger.info("🎯 HYBRID ARI - ✅ Initial greeting played via ARI with token gating", 
                           caller_channel_id=caller_channel_id,
                           audio_size=len(audio_data),
                           playback_id=playback_id,
                           fallback_delay=fallback_delay)
            else:
                logger.warning("🎯 HYBRID ARI - No greeting audio generated")
                
        except Exception as e:
            logger.error("🎯 HYBRID ARI - Failed to play initial greeting", 
                        caller_channel_id=caller_channel_id,
                        media_channel_id=media_channel_id,
                        error=str(e), exc_info=True)

    async def _enable_audio_capture_after_delay(self, channel_id: str, delay_seconds: float):
        """Enable audio capture after a delay to allow greeting to finish playing."""
        try:
            logger.info("🎤 AUDIO TIMER - Starting delay timer", 
                       channel_id=channel_id, 
                       delay_seconds=delay_seconds)
            
            # Wait for the specified delay
            await asyncio.sleep(delay_seconds)
            
            # Find the connection for this channel
            conn_id = self.channel_to_conn.get(channel_id)
            if conn_id:
                # Enable audio capture for this connection
                session = await self.session_store.get_by_call_id(channel_id)
                if session:
                    session.audio_capture_enabled = True
                    await self._save_session(session)
                    logger.info("🎤 AUDIO CAPTURE - ✅ Enabled after timer delay",
                               conn_id=conn_id,
                               channel_id=channel_id,
                               delay_seconds=delay_seconds)
                else:
                    logger.warning("🎤 AUDIO CAPTURE - Channel not found in sessions",
                                  conn_id=conn_id,
                                  channel_id=channel_id)
            else:
                logger.warning("🎤 AUDIO CAPTURE - No connection found for channel",
                              channel_id=channel_id)
                
        except Exception as e:
            logger.error("🎤 AUDIO TIMER - Timer failed", 
                        channel_id=channel_id,
                        delay_seconds=delay_seconds,
                        error=str(e), exc_info=True)

    async def _start_provider_session(self, caller_channel_id: str, local_channel_id: str):
        """Start provider session and bind ExternalMedia - LEGACY (kept for reference)."""
        try:
            # Get provider
            provider = self.providers.get(self.config.default_provider)
            if not provider:
                logger.error("Default provider not found", provider=self.config.default_provider)
                return
            
            # Start provider session
            await provider.start_session(local_channel_id)
            
            # Get session from SessionStore and update with Local channel info
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if session:
                session.local_channel_id = local_channel_id
                session.status = "local_channel_created"
                await self._save_session(session)
                logger.info("Session updated with Local channel", 
                           caller_channel_id=caller_channel_id, 
                           local_channel_id=local_channel_id)
            else:
                logger.warning("No session found for caller", caller_channel_id=caller_channel_id)
            
            logger.info("Provider session started", 
                       local_channel_id=local_channel_id, 
                       caller_channel_id=caller_channel_id,
                       provider=self.config.default_provider)
            
            # ExternalMedia will bind automatically via ChannelVarset
            logger.info("Ready for ExternalMedia binding", local_channel_id=local_channel_id)
            
        except Exception as e:
            logger.error("Failed to start provider session", 
                        local_channel_id=local_channel_id, 
                        caller_channel_id=caller_channel_id,
                        error=str(e), exc_info=True)

    async def _bind_connection_to_channel(self, conn_id: str, channel_id: str, provider_name: str):
        """Bind an accepted ExternalMedia connection to a Stasis channel and start provider.

        Plays a one-time test prompt to validate audio path, then proceeds with provider flow.
        """
        try:
            # If a connection is already bound to this channel, reject extras to avoid idle sockets
            existing = self.channel_to_conn.get(channel_id)
            if existing and existing != conn_id:
                logger.info("Rejecting extra ExternalMedia connection for already-bound channel",
                            channel_id=channel_id, existing_conn=existing, new_conn=conn_id)
                return

            self.conn_to_channel[conn_id] = channel_id
            self.channel_to_conn[channel_id] = conn_id
            logger.info("ExternalMedia connection bound to channel", channel_id=channel_id, conn_id=conn_id)
            # Get session from SessionStore
            session = await self.session_store.get_by_call_id(channel_id)
            if session:
                provider = self.providers.get(session.provider_name)
            else:
                provider = self.providers.get(provider_name)
            # Hint upstream audio format for providers: ExternalMedia delivers PCM16@8k by default
            try:
                if provider and hasattr(provider, 'set_input_mode'):
                    provider.set_input_mode('pcm16_8k')
                    logger.info("Set provider upstream input mode", channel_id=channel_id, conn_id=conn_id, mode='pcm16_8k', provider=provider_name)
            except Exception:
                logger.debug("Could not set provider input mode on bind", channel_id=channel_id, conn_id=conn_id, exc_info=True)

            # Start ExternalMedia keepalive task to prevent idle timeouts in Asterisk app
            try:
                if conn_id in self._keepalive_tasks:
                    t = self._keepalive_tasks.pop(conn_id, None)
                    if t and not t.done():
                        t.cancel()
                self._keepalive_tasks[conn_id] = asyncio.create_task(self._externalmedia_keepalive(conn_id))
                logger.debug("Started ExternalMedia keepalive", conn_id=conn_id)
            except Exception:
                logger.debug("Failed to start keepalive task", channel_id=channel_id, conn_id=conn_id, exc_info=True)
            # Remove demo-congrats/test tone; rely on provider greeting to start the dialog
            logger.debug("Skipping demo test playback; provider greeting will start the dialog", channel_id=channel_id)
            # Start provider session and optional greeting
            if provider:
                # Check if provider session already exists for this channel
                if session and session.provider_name:
                    logger.debug("Provider session already exists, skipping", channel_id=channel_id)
                else:
                    logger.debug("Starting provider session", channel_id=channel_id, provider=provider_name)
                    await provider.start_session(channel_id)
                    logger.debug("Provider session started successfully", channel_id=channel_id)
                    
                    # Play initial greeting only when ExternalMedia connects
                    if hasattr(provider, 'play_initial_greeting'):
                        logger.info("🔊 GREETING - Playing initial greeting", channel_id=channel_id)
                        await provider.play_initial_greeting(channel_id)
                        logger.info("🔊 GREETING - Played successfully", channel_id=channel_id)
        except Exception:
            logger.error("Error binding connection to channel", channel_id=channel_id, conn_id=conn_id, exc_info=True)

    async def _handle_channel_varset(self, event_data: dict):
        """Bind any pending ExternalMedia connection when EXTERNALMEDIA_UUID variable is set.

        The dialplan now generates a proper UUID, so we bind the ExternalMedia to the Local channel.
        """
        try:
            variable = event_data.get('variable') or event_data.get('name')
            if variable != 'EXTERNALMEDIA_UUID':
                return
            
            # Get the Local channel ID from the event
            channel = event_data.get('channel', {})
            local_channel_id = channel.get('id')
            if not local_channel_id:
                return
                
            # Find the corresponding caller channel ID using SessionStore
            caller_channel_id = None
            sessions = await self.session_store.get_all_sessions()
            for session in sessions:
                if session.local_channel_id == local_channel_id:
                    caller_channel_id = session.caller_channel_id
                    break
            
            if not caller_channel_id:
                logger.warning("No caller channel found for Local channel", local_channel_id=local_channel_id)
                return
                
            if local_channel_id in self.channel_to_conn:
                return
                
            # No ExternalMedia connection binding needed for externalmedia mode
            logger.info("ChannelVarset bound or queued", variable=variable, target_channel_id=local_channel_id)
        except Exception:
            logger.debug("Error in ChannelVarset handler", exc_info=True)

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
            deepgram_config = self._build_deepgram_config(provider_config_data)
            if not deepgram_config:
                raise ValueError("Deepgram provider configuration invalid")
            return DeepgramProvider(deepgram_config, self.config.llm, self.on_provider_event)
        elif provider_name == "local":
            provider_config = LocalProviderConfig(**provider_config_data)
            return LocalProvider(provider_config, self.on_provider_event)

        raise ValueError(f"Provider '{provider_name}' does not have a creation rule.")

    def _build_deepgram_config(self, raw_config: Any) -> Optional[DeepgramProviderConfig]:
        """Normalize Deepgram configuration and validate required secrets."""
        config_dict = dict(raw_config or {})
        env_api_key = os.getenv("DEEPGRAM_API_KEY")
        if not config_dict.get("api_key") and env_api_key:
            config_dict["api_key"] = env_api_key
        env_encoding = os.getenv("DEEPGRAM_INPUT_ENCODING")
        if env_encoding:
            config_dict["input_encoding"] = env_encoding
        env_sample_rate = os.getenv("DEEPGRAM_INPUT_SAMPLE_RATE_HZ")
        if env_sample_rate:
            try:
                config_dict["input_sample_rate_hz"] = int(env_sample_rate)
            except ValueError:
                logger.error("Invalid DEEPGRAM_INPUT_SAMPLE_RATE_HZ env value", value=env_sample_rate)

        try:
            config = DeepgramProviderConfig(**config_dict)
        except ValidationError as exc:
            logger.error("Deepgram provider configuration invalid", error=str(exc))
            return None

        if not config.api_key:
            logger.error(
                "Deepgram provider requires api_key. Set DEEPGRAM_API_KEY env or providers.deepgram.api_key."
            )
            return None

        return config

    async def _handle_audio_frame(self, audio_data: bytes):
        """Handle raw audio frames from ExternalMedia connections."""
        try:
            # Find the active call using SessionStore
            sessions = await self.session_store.get_all_sessions()
            if not sessions:
                logger.warning("No active call found for audio frame")
                return
                
            # Use the first active session
            session = sessions[0]
            active_channel_id = session.caller_channel_id
                
            provider = self.providers.get(session.provider_name)
            if not provider:
                logger.debug("No provider found for active call", provider_name=session.provider_name)
                return

            # Check conversation state
            conversation_state = getattr(session, 'conversation_state', 'greeting')
            
            if conversation_state == 'greeting':
                # During greeting phase, ignore incoming audio
                logger.debug("Ignoring audio during greeting phase", channel_id=active_channel_id)
                return
            elif conversation_state == 'listening':
                # During listening phase, buffer audio for conversation
                # Get call data from session store
                session = await self.session_store.get_by_call_id(active_channel_id)
                if session:
                    call_data = {
                        'audio_buffer': getattr(session, 'audio_buffer', b''),
                        'last_audio_ts': getattr(session, 'last_audio_ts', 0),
                        'provider_timeout_task': getattr(session, 'provider_timeout_task', None),
                    }
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
            
            # ExternalMedia sends PCM16LE@8kHz directly - no conversion needed
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
            session = await self.session_store.get_by_call_id(channel_id)
            if session:
                provider = self.providers.get(session.provider_name)
                if provider and hasattr(provider, 'handle_dtmf'):
                    await provider.handle_dtmf(digit)
    
    async def _on_rtp_audio(self, ssrc: int, pcm_16k_data: bytes):
        """Route inbound RTP audio to the appropriate provider using SSRC with VAD-based utterance detection."""
        logger.info("🎵 RTP AUDIO - Received audio", ssrc=ssrc, bytes=len(pcm_16k_data))
        
        # AUDIO CAPTURE: Capture ALL RTP audio frames (before any filtering)
        try:
            # Find the caller channel for this SSRC
            caller_channel_id = self.ssrc_to_caller.get(ssrc)
            
            if not caller_channel_id:
                # First packet from this SSRC - try to map it to an active ExternalMedia call
                # We'll map to the most recent ExternalMedia call that doesn't have an SSRC yet
                sessions = await self.session_store.get_all_sessions()
                for session in sessions:
                    if session.external_media_id and not getattr(session, 'ssrc_mapped', False):
                        # This ExternalMedia call doesn't have an SSRC yet, map it
                        caller_channel_id = session.caller_channel_id
                        self.ssrc_to_caller[ssrc] = caller_channel_id
                        session.ssrc_mapped = True
                        session.ssrc = ssrc
                        await self._save_session(session)
                        if getattr(self, 'rtp_server', None):
                            self.rtp_server.map_ssrc_to_call_id(ssrc, caller_channel_id)
                        logger.info("SSRC mapped to caller on first packet", 
                                   ssrc=ssrc, 
                                   caller_channel_id=caller_channel_id,
                                   external_media_id=session.external_media_id)
                        break
            
            # SIMPLIFIED: Always process audio for VAD - we'll implement smart loop prevention later
            # This ensures VAD improvements can actually work
            
            if not caller_channel_id:
                logger.debug("RTP audio received for unknown SSRC", ssrc=ssrc)
                return
            
            # Check if call is still active using SessionStore
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if not session:
                logger.debug("RTP audio received for inactive call", ssrc=ssrc, caller_channel_id=caller_channel_id)
                return
            
            # Check if audio capture is enabled (set by PlaybackFinished event)
            audio_capture_enabled = session.audio_capture_enabled
            tts_playing = session.tts_playing
            
            logger.info("🎤 AUDIO CAPTURE - Check", ssrc=ssrc, caller_channel_id=caller_channel_id, audio_capture_enabled=audio_capture_enabled, tts_playing=tts_playing)
            
            # ARCHITECT FIX: Drop gated frames as early as possible
            if not audio_capture_enabled or tts_playing:
                if tts_playing and self.conversation_coordinator:
                    self.conversation_coordinator.note_audio_during_tts(caller_channel_id)
                logger.debug("RTP audio dropped - capture disabled or TTS playing", 
                           ssrc=ssrc, caller_channel_id=caller_channel_id,
                           audio_capture_enabled=audio_capture_enabled, tts_playing=tts_playing)
                return
            
            # Get provider for this call
            provider = self.providers.get(session.provider_name)
            if not provider:
                logger.warning("No provider found for RTP audio", ssrc=ssrc, caller_channel_id=caller_channel_id)
                return

            continuous_input = bool(getattr(provider, "continuous_input", False))

            if continuous_input:
                logger.info("<<< CONTINUOUS INPUT: Sending audio to provider >>>", provider=session.provider_name, bytes=len(pcm_16k_data))
                try:
                    await provider.send_audio(pcm_16k_data)
                    logger.debug("🎵 STREAMING - Frame forwarded to provider",
                                 provider=session.provider_name,
                                 caller_channel_id=caller_channel_id,
                                 bytes=len(pcm_16k_data))
                except Exception:
                    logger.error("Failed to stream audio chunk to continuous provider",
                                 caller_channel_id=caller_channel_id,
                                 ssrc=ssrc,
                                 exc_info=True)

            # Process audio with VAD-based utterance detection
            await self._process_rtp_audio_with_vad(caller_channel_id, ssrc, pcm_16k_data, provider)

            # FALLBACK: If VAD hasn't detected speech for a while, send audio directly to STT
            # This ensures we capture audio even when VAD fails
            await self._fallback_audio_processing(caller_channel_id, ssrc, pcm_16k_data, provider)
            
        except Exception as e:
            logger.error("Error processing RTP audio", 
                        ssrc=ssrc, 
                        error=str(e), 
                        exc_info=True)

    async def _audiosocket_handle_uuid(self, conn_id: str, audio_uuid: str) -> bool:
        """Bind an AudioSocket connection to the pending caller channel."""
        caller_channel_id = self.uuidext_to_channel.get(audio_uuid)
        if not caller_channel_id:
            logger.warning("AudioSocket UUID not mapped to caller", conn_id=conn_id, uuid=audio_uuid)
            return False

        session = await self.session_store.get_by_call_id(caller_channel_id)
        if not session:
            logger.warning("AudioSocket binding failed - session missing", conn_id=conn_id, caller_channel_id=caller_channel_id)
            return False

        existing_conn = self.channel_to_conn.get(caller_channel_id)
        if existing_conn and existing_conn != conn_id:
            # Keep both connections temporarily; prefer whichever sends audio first
            logger.info(
                "AudioSocket duplicate connection received",
                conn_id=conn_id,
                existing_conn=existing_conn,
                channel_id=caller_channel_id,
            )

        # Track connection mappings
        self.conn_to_channel[conn_id] = caller_channel_id
        self.channel_to_conn[caller_channel_id] = self.channel_to_conn.get(caller_channel_id, conn_id)
        self.conn_to_caller[conn_id] = caller_channel_id
        # Track set of conns for this channel
        conns = self.channel_to_conns.get(caller_channel_id, set())
        conns.add(conn_id)
        self.channel_to_conns[caller_channel_id] = conns
        # Record all connection IDs on the session for observability/broadcast-debug
        try:
            session.audiosocket_conns = list(conns)  # type: ignore[attr-defined]
        except Exception:
            pass
        # Pin outbound to the FIRST bound connection for the lifetime of the call
        session.status = "audiosocket_connected"
        if not getattr(session, "audiosocket_conn_id", None):
            session.audiosocket_conn_id = conn_id
            # Mark as pinned so we never switch on first inbound frame
            try:
                session.audiosocket_outbound_pinned = True  # type: ignore[attr-defined]
            except Exception:
                pass
            logger.info(
                "AudioSocket outbound pinned to first bound connection",
                channel_id=caller_channel_id,
                conn_id=conn_id,
            )
        await self._save_session(session)

        provider = self.providers.get(session.provider_name)
        try:
            if provider and hasattr(provider, "set_input_mode"):
                provider.set_input_mode("pcm16_8k")
        except Exception:
            logger.debug("Failed to set provider input mode for AudioSocket", caller_channel_id=caller_channel_id, exc_info=True)

        # If provider has already produced audio and a queue exists, start streaming now
        try:
            if self.config.downstream_mode == "stream" and hasattr(session, "streaming_audio_queue") and not getattr(session, "streaming_started", False):
                stream_id = await self.streaming_playback_manager.start_streaming_playback(
                    session.call_id, session.streaming_audio_queue, "streaming-response"
                )
                if stream_id:
                    session.current_stream_id = stream_id
                    session.streaming_started = True
                    await self._save_session(session)
                    logger.info(
                        "🎵 STREAMING STARTED - Began on AudioSocket bind",
                        call_id=session.call_id,
                        stream_id=stream_id,
                        conn_id=conn_id,
                    )
        except Exception:
            logger.error("Failed to start streaming on bind", call_id=session.call_id, conn_id=conn_id, exc_info=True)

        logger.info("AudioSocket connection bound to channel", conn_id=conn_id, channel_id=caller_channel_id)

        # Ensure provider session is running when AudioSocket binds
        if not session.provider_session_active:
            provider = self.providers.get(session.provider_name)
            if provider:
                try:
                    logger.info(
                        "AudioSocket provider session starting",
                        conn_id=conn_id,
                        channel_id=caller_channel_id,
                        provider=session.provider_name,
                    )
                    await provider.start_session(caller_channel_id)
                    session.provider_session_active = True
                    session.audio_capture_enabled = True
                    session.status = "provider_started"
                    await self._save_session(session)
                    if self.conversation_coordinator:
                        await self.conversation_coordinator.sync_from_session(session)
                    logger.info(
                        "AudioSocket provider session ready",
                        conn_id=conn_id,
                        channel_id=caller_channel_id,
                        provider=session.provider_name,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Failed to start provider session after AudioSocket bind",
                        conn_id=conn_id,
                        channel_id=caller_channel_id,
                        provider=session.provider_name,
                        error=str(exc),
                        exc_info=True,
                    )
            else:
                logger.error(
                    "No provider configured for AudioSocket session",
                    conn_id=conn_id,
                    channel_id=caller_channel_id,
                )

        return True

    async def _audiosocket_handle_audio(self, conn_id: str, pcm_8k_data: bytes) -> None:
        caller_channel_id = self.conn_to_channel.get(conn_id)
        if not caller_channel_id:
            logger.debug("AudioSocket audio received for unknown connection", conn_id=conn_id)
            return

        session = await self.session_store.get_by_call_id(caller_channel_id)
        if not session:
            logger.debug("AudioSocket audio received for inactive call", conn_id=conn_id, caller_channel_id=caller_channel_id)
            return

        provider = self.providers.get(session.provider_name)
        if not provider:
            logger.warning("AudioSocket audio received but provider missing", conn_id=conn_id, caller_channel_id=caller_channel_id)
            return

        count = self._audio_rx_debug.get(conn_id, 0) + 1
        self._audio_rx_debug[conn_id] = count
        if count == 1:
            logger.info(
                "AudioSocket first frame received",
                conn_id=conn_id,
                channel_id=caller_channel_id,
                bytes=len(pcm_8k_data),
            )
            # Do NOT switch outbound target on first inbound frame; keep pinned to first bound
            logger.debug(
                "AudioSocket first frame observed; outbound remains pinned to first bound",
                channel_id=caller_channel_id,
                pinned_conn=getattr(session, "audiosocket_conn_id", None),
                observed_conn=conn_id,
            )

        # Decode based on dialplan format, then resample to 16kHz for the VAD pipeline
        state = self.audiosocket_resample_state.get(conn_id)
        try:
            # Determine expected inbound format (default to ulaw if unspecified)
            inbound_fmt = None
            try:
                if self.config.audiosocket and hasattr(self.config.audiosocket, 'format'):
                    inbound_fmt = (self.config.audiosocket.format or 'ulaw').lower()
            except Exception:
                inbound_fmt = 'ulaw'

            if inbound_fmt in ("ulaw", "mulaw", "mu-law"):
                # Convert μ-law to 16-bit PCM @8k before resample
                pcm8k_linear = audioop.ulaw2lin(pcm_8k_data, 2)
            else:
                # Already linear PCM16 @8k
                pcm8k_linear = pcm_8k_data

            pcm_16k_data, state = audioop.ratecv(pcm8k_linear, 2, 1, 8000, 16000, state)
            self.audiosocket_resample_state[conn_id] = state
        except Exception as exc:  # noqa: BLE001
            logger.error("AudioSocket decode/resample failed", conn_id=conn_id, error=str(exc), exc_info=True)
            return

        ssrc = self._ensure_audiosocket_ssrc(conn_id, caller_channel_id)
        await self._process_rtp_audio_with_vad(caller_channel_id, ssrc, pcm_16k_data, provider)
        await self._fallback_audio_processing(caller_channel_id, ssrc, pcm_16k_data, provider)

    async def _audiosocket_handle_disconnect(self, conn_id: str) -> None:
        caller_channel_id = self.conn_to_channel.pop(conn_id, None)
        if caller_channel_id:
            self.channel_to_conn.pop(caller_channel_id, None)
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if session:
                # Update tracked conn set on session
                conns = self.channel_to_conns.get(caller_channel_id, set())
                try:
                    session.audiosocket_conns = list(conns)  # type: ignore[attr-defined]
                except Exception:
                    pass
                # If the pinned outbound conn closed, clear it so a future bind can repin
                if session.audiosocket_conn_id == conn_id:
                    session.audiosocket_conn_id = None
                    session.provider_session_active = False
                    try:
                        session.audiosocket_outbound_pinned = False  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    await self._save_session(session)

        # Remove from per-channel conn set
        conns = self.channel_to_conns.get(caller_channel_id or "", set())
        if conn_id in conns:
            conns.discard(conn_id)
            if caller_channel_id:
                self.channel_to_conns[caller_channel_id] = conns
        # If primary was this conn, clear primary so a future conn can take over
        if caller_channel_id and self.audiosocket_primary_conn.get(caller_channel_id) == conn_id:
            self.audiosocket_primary_conn.pop(caller_channel_id, None)

        self.conn_to_caller.pop(conn_id, None)
        self.audiosocket_resample_state.pop(conn_id, None)
        ssrc = self.audiosocket_conn_to_ssrc.pop(conn_id, None)
        if ssrc is not None:
            self.ssrc_to_caller.pop(ssrc, None)
        self._audio_rx_debug.pop(conn_id, None)

        logger.info("AudioSocket connection closed", conn_id=conn_id, channel_id=caller_channel_id)

    async def _audiosocket_handle_dtmf(self, conn_id: str, digit: str) -> None:
        caller_channel_id = self.conn_to_channel.get(conn_id)
        if not caller_channel_id:
            return
        event = {
            "channel": {"id": caller_channel_id},
            "digit": digit,
        }
        await self._handle_dtmf_received(event)

    def _ensure_audiosocket_ssrc(self, conn_id: str, caller_channel_id: str) -> int:
        ssrc = self.audiosocket_conn_to_ssrc.get(conn_id)
        if ssrc is None:
            ssrc = random.getrandbits(32)
            while ssrc in self.ssrc_to_caller and self.ssrc_to_caller[ssrc] != caller_channel_id:
                ssrc = random.getrandbits(32)
            self.audiosocket_conn_to_ssrc[conn_id] = ssrc
        self.ssrc_to_caller[ssrc] = caller_channel_id
        return ssrc
    
    async def _process_rtp_audio_with_vad(self, caller_channel_id: str, ssrc: int, pcm_16k_data: bytes, provider):
        """Process RTP audio with VAD-based utterance detection."""
        logger.info("<<< VAD PROCESSING: processing audio >>>", bytes=len(pcm_16k_data))
        try:
            # AUDIO CAPTURE: Capture raw RTP audio frames
            # ARCHITECT FIX: TTS feedback loop prevention gate
            # Prevent LLM from hearing its own TTS responses
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if not session:
                logger.debug("🎤 AUDIO CAPTURE - No session found for call", caller_channel_id=caller_channel_id)
                return  # Skip VAD processing if no session
            
            if session.tts_playing:
                if self.conversation_coordinator:
                    self.conversation_coordinator.note_audio_during_tts(caller_channel_id)
                logger.debug("🎤 TTS GATING - Skipping VAD processing during TTS playback", 
                           caller_channel_id=caller_channel_id,
                           tts_playing=True)
                return  # Skip VAD processing during TTS playback
            
            # CRITICAL FIX: Check if audio capture is enabled
            if not session.audio_capture_enabled:
                logger.info("🎤 AUDIO CAPTURE - Check", 
                           audio_capture_enabled=session.audio_capture_enabled,
                           caller_channel_id=caller_channel_id,
                           ssrc=ssrc,
                           tts_playing=session.tts_playing)
                return  # Skip VAD processing when audio capture is disabled
            
            logger.info("🎤 AUDIO CAPTURE - ENABLED - Processing audio",
                       audio_capture_enabled=session.audio_capture_enabled,
                       caller_channel_id=caller_channel_id,
                       ssrc=ssrc,
                       tts_playing=session.tts_playing)
            # Get or initialize VAD state for this call
            if not session.vad_state:
                session.vad_state = self._build_default_vad_state(ssrc)

            vad_state = self._ensure_vad_state_keys(session, ssrc)
            vad_state.setdefault("consecutive_silence_frames", 0)
            vad_state.setdefault("consecutive_speech_frames", 0)
            vad_state.setdefault("speech_frame_count", 0)
            
            # ARCHITECT FIX: Use consistent monotonic time base
            if "t0_ms" not in vad_state:
                vad_state["t0_ms"] = int(time.monotonic() * 1000)
            
            # ARCHITECT FIX: Increment frame_count BEFORE calculating current_time_ms
            vad_state["frame_count"] += 1
            current_time_ms = vad_state["t0_ms"] + vad_state["frame_count"] * 20
            
            # WebRTC-only VAD - no energy calculations needed
            vs = vad_state
            
            # WebRTC-only VAD - no noise floor tracking needed
            
            # VAD parameters
            min_speech_ms = 200
            end_silence_ms = 1000
            pre_roll_ms = 400
            post_roll_ms = 200
            max_utterance_ms = 10000
            min_gap_ms = 150
            min_utterance_ms = 600
            
            # Convert durations to frame counts (20ms per frame)
            min_speech_frames = min_speech_ms // 20
            end_silence_frames = end_silence_ms // 20
            pre_roll_frames = pre_roll_ms // 20
            post_roll_frames = post_roll_ms // 20
            max_utterance_frames = max_utterance_ms // 20
            
            # current_time_ms already calculated above with monotonic clock
            
            # ARCHITECT FIX: Frame-accurate WebRTC VAD with buffering
            # Add incoming audio to frame buffer
            vad_state["frame_buffer"] += pcm_16k_data
            
            # Process complete 20ms frames (640 bytes each)
            frames_processed = 0
            while len(vad_state["frame_buffer"]) >= 640:
                # Extract exactly 640 bytes (20ms at 16kHz)
                frame_data = vad_state["frame_buffer"][:640]
                vad_state["frame_buffer"] = vad_state["frame_buffer"][640:]
                frames_processed += 1
                
                # ARCHITECT FIX: Per-frame timebase increment
                vs["frame_count"] += 1
                current_time_ms = vs["t0_ms"] + vs["frame_count"] * 20
                
                # WebRTC VAD decision for this exact 20ms frame
                webrtc_decision = False
                if self.webrtc_vad:
                    try:
                        webrtc_decision = self.webrtc_vad.is_speech(frame_data, 16000)
                        # Debug logging for WebRTC VAD decisions (every 50 frames)
                        if vad_state["frame_count"] % 50 == 0:
                            logger.debug("🎤 WebRTC VAD - Decision", 
                           caller_channel_id=caller_channel_id,
                           frame_count=vad_state["frame_count"],
                                       webrtc_decision=webrtc_decision,
                                       audio_bytes=len(frame_data),
                                       frames_processed=frames_processed)
                    except Exception as e:
                        logger.debug("WebRTC VAD error", error=str(e))
                        webrtc_decision = False
                
                # Update WebRTC frame counters
                if webrtc_decision:
                    vs["webrtc_speech_frames"] += 1
                    vs["webrtc_silence_frames"] = 0
                else:
                    vs["webrtc_speech_frames"] = 0
                    vs["webrtc_silence_frames"] += 1
                
                vs["webrtc_last_decision"] = webrtc_decision
                
                # Update pre-roll buffer with this frame (keep last 400ms)
                vs["pre_roll_buffer"] += frame_data
                if len(vs["pre_roll_buffer"]) > pre_roll_frames * 640:  # 640 bytes per 20ms frame
                    vs["pre_roll_buffer"] = vs["pre_roll_buffer"][-pre_roll_frames * 640:]
                
                # WebRTC-only VAD logic (architect recommended)
                webrtc_start_frames = self.config.vad.webrtc_start_frames
                end_silence_frames = self.config.vad.webrtc_end_silence_frames  # 1000ms / 20ms = 50 frames
                
                # Start: WebRTC only - require consecutive speech frames
                webrtc_speech = vs["webrtc_speech_frames"] >= webrtc_start_frames
                
                # Continue: WebRTC only - direct decision per frame
                webrtc_continue = webrtc_decision
                
                # End: WebRTC silence frames threshold
                webrtc_silence = vs["webrtc_silence_frames"] >= end_silence_frames
                
                # WebRTC-only speech decisions
                is_speech = webrtc_speech or (vs["speaking"] and webrtc_continue)
                is_silence = webrtc_silence
                
                # ARCHITECT FIX: INFO-level VAD heartbeat (every 50 frames)
                if vs["frame_count"] % 50 == 0:
                    logger.info("🎤 VAD HEARTBEAT - WebRTC-only", 
                               caller_channel_id=caller_channel_id,
                               frame_count=vs["frame_count"],
                               webrtc_decision=webrtc_decision,
                               webrtc_speech_frames=vs["webrtc_speech_frames"],
                               webrtc_silence_frames=vs["webrtc_silence_frames"],
                               webrtc_speech=webrtc_speech,
                               webrtc_continue=webrtc_continue,
                               webrtc_silence=webrtc_silence,
                               is_speech=is_speech,
                               speaking=vs.get("speaking", False),
                               utterance_id=vs.get("utterance_id", 0),
                               frame_buffer_len=len(vs["frame_buffer"]),
                               frames_processed=frames_processed)
                
                # Debug logging for VAD analysis (every 10 frames)
                if vs["frame_count"] % 10 == 0:
                    logger.debug("🎤 VAD ANALYSIS - WebRTC-only", 
                               caller_channel_id=caller_channel_id,
                               frame_count=vs["frame_count"],
                               webrtc_decision=webrtc_decision,
                               webrtc_speech_frames=vs["webrtc_speech_frames"],
                               webrtc_silence_frames=vs["webrtc_silence_frames"],
                               webrtc_speech=webrtc_speech,
                               webrtc_continue=webrtc_continue,
                               webrtc_silence=webrtc_silence,
                               is_speech=is_speech,
                               speaking=vs.get("speaking", False),
                               frames_processed=frames_processed)
                
                # AVR-VAD INSPIRED: Speech detection logic (per frame)
                if is_speech and not vs["speaking"]:
                    # Speech start detected
                    vs["speaking"] = True
                    vs["speech_real_start_fired"] = False
                    vs["speech_frame_count"] = 0
                    vs["redemption_counter"] = 0
                    vs["consecutive_speech_frames"] = 0
                    vs["consecutive_silence_frames"] = 0
                    vs["utterance_buffer"] = vs["pre_roll_buffer"]
                    vs["speech_start_ms"] = current_time_ms - pre_roll_ms
                    vs["speech_duration_ms"] = 0
                    vs["silence_duration_ms"] = 0
                    vs["utterance_id"] += 1
                    vs["last_voice_ms"] = current_time_ms  # Update last voice time for fallback
                    logger.info("🎤 VAD - Speech started", 
                               caller_channel_id=caller_channel_id,
                               utterance_id=vs["utterance_id"],
                               webrtc_speech_frames=vs["webrtc_speech_frames"])
                
                # AVR-VAD INSPIRED: During speech recording
                elif vs["speaking"]:
                    vs["utterance_buffer"] += frame_data
                    
                    if is_speech:
                        # Speech continues
                        vs["speech_frame_count"] += 1
                        vs["redemption_counter"] = 0
                        vs["last_voice_ms"] = current_time_ms  # Update last voice time for fallback
                    vs["consecutive_speech_frames"] += 1
                    vs["consecutive_silence_frames"] = 0
                    vs["speech_duration_ms"] += 20
                    
                    # Debug logging for consecutive frames
                    if vs["consecutive_speech_frames"] % 5 == 0:  # Log every 5 frames
                        logger.debug("🎤 VAD - Consecutive speech frames", 
                                   caller_channel_id=caller_channel_id,
                                   utterance_id=vs["utterance_id"],
                                   consecutive_speech=vs["consecutive_speech_frames"],
                                   speech_frames=vs["speech_frame_count"],
                                   webrtc_decision=webrtc_decision)
                    
                    # Fire speech real start after minimum frames
                    if vs["speech_frame_count"] >= min_speech_frames and not vs["speech_real_start_fired"]:
                        vs["speech_real_start_fired"] = True
                        logger.info("🎤 VAD - Speech confirmed", 
                                   caller_channel_id=caller_channel_id,
                                   utterance_id=vs["utterance_id"],
                                   speech_frames=vs["speech_frame_count"])
                else:
                    # Silence detected - track silence frames
                    vs["consecutive_speech_frames"] = 0
                    vs["consecutive_silence_frames"] += 1
                    vs["silence_duration_ms"] += 20

                    # Debug logging for silence detection
                    if vs["consecutive_silence_frames"] % 10 == 0:  # Log every 10 frames
                        logger.debug("🎤 VAD - Silence detected", 
                                   caller_channel_id=caller_channel_id,
                                   utterance_id=vs["utterance_id"],
                                   webrtc_silence_frames=vs["webrtc_silence_frames"],
                                   end_silence_frames=end_silence_frames,
                                   consecutive_silence=vs["consecutive_silence_frames"])
                    
                    # Check if WebRTC silence threshold reached
                    if vs["webrtc_silence_frames"] >= end_silence_frames:
                        # End speech after WebRTC silence threshold
                        vs["speaking"] = False
                        vs["speech_real_start_fired"] = False
                        vs["speech_frame_count"] = 0
                        vs["last_utterance_end_ms"] = current_time_ms
                        
                        # Process the utterance
                        if len(vs["utterance_buffer"]) > 0:
                            # Normalize to target RMS before sending
                            buf = vs["utterance_buffer"]
                            buf = self._normalize_to_dbfs(buf, target_dbfs=-20.0, max_gain=3.0)
                            
                            # ARCHITECT FIX: Discard ultra-short utterances using config
                            # Use min_utterance_ms from config (default 600ms)
                            min_utterance_bytes = (min_utterance_ms // 20) * 640
                            if len(buf) < min_utterance_bytes:
                                logger.debug("🎤 VAD - Discarding short utterance", 
                                           caller_channel_id=caller_channel_id,
                                           utterance_id=vs["utterance_id"],
                                           bytes=len(buf),
                                           min_bytes=min_utterance_bytes)
                                vs["state"] = "listening"
                                vs["utterance_buffer"] = b""
                                continue  # Continue to next frame

                        vs["state"] = "processing"
                        logger.info("🎤 VAD - Speech ended", 
                                   caller_channel_id=caller_channel_id,
                                   utterance_id=vs["utterance_id"],
                                   reason="webrtc_silence",
                                   speech_ms=vs["speech_duration_ms"],
                                   silence_ms=vs["silence_duration_ms"],
                                   bytes=len(buf), 
                                   webrtc_silence_frames=vs["webrtc_silence_frames"])

                        now_ts = time.time()
                        session.last_user_speech_end_ts = now_ts
                        await self._save_session(session)
                        
                        # Send to provider
                        continuous_input = getattr(provider, "continuous_input", False)
                        if continuous_input:
                            logger.debug(
                                "🎤 VAD - Continuous provider, skipping buffered utterance send",
                                caller_channel_id=caller_channel_id,
                                provider=session.provider_name,
                            )
                        else:
                            await provider.send_audio(buf)
                            logger.info(
                                "🎤 VAD - Utterance sent to provider",
                                caller_channel_id=caller_channel_id,
                                utterance_id=vs["utterance_id"],
                                bytes=len(buf),
                            )
                        if self.conversation_coordinator:
                            await self.conversation_coordinator.update_conversation_state(
                                caller_channel_id,
                                "processing",
                            )
                        else:
                            # Empty utterance - misfire (only when speech actually ends)
                            logger.info("🎤 VAD - Speech misfire (empty utterance)", 
                               caller_channel_id=caller_channel_id,
                               utterance_id=vs["utterance_id"])

                        # Reset for next utterance
                        vs["state"] = "listening"
                        vs["utterance_buffer"] = b""
            
            # ARCHITECT FIX: All speech detection logic now handled inside frame processing loop
            # No additional processing needed here
            
        except Exception as e:
            logger.error("Error in VAD processing", 
                        caller_channel_id=caller_channel_id,
                        error=str(e), 
                        exc_info=True)
    
    async def _fallback_audio_processing(self, caller_channel_id: str, ssrc: int, pcm_16k_data: bytes, provider):
        """Fallback audio processing when VAD fails to detect speech."""
        try:
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if not session:
                return
            
            # Initialize fallback state if not present
            if not session.fallback_state:
                session.fallback_state = {
                    "audio_buffer": b"",
                    "last_vad_speech_time": time.time(),
                    "buffer_start_time": None,
                    "frame_count": 0
                }
            
            fallback_state = session.fallback_state
            fallback_state["frame_count"] += 1
            
            # Check if VAD has detected speech recently
            vad_state = session.vad_state or {}
            last_speech_time = vad_state.get("last_voice_ms", 0) / 1000.0  # Convert to seconds
            current_time = time.time()
            time_since_speech = current_time - last_speech_time
            
            # Only start fallback buffering if VAD has been silent for configured interval
            fallback_interval = self.config.vad.fallback_interval_ms / 1000.0
            if time_since_speech < fallback_interval:
                # VAD is still active, reset fallback state
                fallback_state["last_vad_speech_time"] = current_time
                fallback_state["audio_buffer"] = b""
                fallback_state["buffer_start_time"] = None
                return
            
            # Start buffering audio
            if fallback_state["buffer_start_time"] is None:
                fallback_state["buffer_start_time"] = time.time()
                logger.info("🔄 FALLBACK - Starting audio buffering (VAD silent for 2s)", 
                           caller_channel_id=caller_channel_id, ssrc=ssrc)
            
            # Add audio to fallback buffer
            fallback_state["audio_buffer"] += pcm_16k_data
            
            # AUDIO CAPTURE: Capture fallback buffered audio
            # Send buffer to STT every configured interval or when buffer is large enough
            buffer_duration = time.time() - fallback_state["buffer_start_time"]
            buffer_size = len(fallback_state["audio_buffer"])
            fallback_buffer_size = self.config.vad.fallback_buffer_size
            
            if buffer_duration >= fallback_interval or buffer_size >= fallback_buffer_size:
                # ARCHITECT FIX: Check TTS gating before sending fallback audio
                # Prevent AI from processing its own TTS responses
                if session.tts_playing or not session.audio_capture_enabled:
                    if session.tts_playing and self.conversation_coordinator:
                        self.conversation_coordinator.note_audio_during_tts(caller_channel_id)
                    logger.debug("🔄 FALLBACK - Skipping STT during TTS playback", 
                               caller_channel_id=caller_channel_id,
                               tts_playing=session.tts_playing,
                               audio_capture_enabled=session.audio_capture_enabled)
                    # Reset buffer and return to avoid processing TTS audio
                    fallback_state["audio_buffer"] = b""
                    fallback_state["buffer_start_time"] = None
                    return
                
                logger.info("🔄 FALLBACK - Sending buffered audio to STT", 
                           caller_channel_id=caller_channel_id,
                           buffer_size=buffer_size,
                           buffer_duration=f"{buffer_duration:.1f}s")
                
                # AUDIO CAPTURE: Capture complete fallback utterance
                # Send to provider
                if getattr(provider, "continuous_input", False):
                    logger.debug("🔄 FALLBACK - Continuous provider, skipping fallback send",
                                 caller_channel_id=caller_channel_id,
                                 provider=session.provider_name)
                else:
                    await provider.send_audio(fallback_state["audio_buffer"])
                if self.conversation_coordinator:
                    await self.conversation_coordinator.update_conversation_state(
                        caller_channel_id,
                        "processing",
                    )
                
                # Reset buffer
                fallback_state["audio_buffer"] = b""
                fallback_state["buffer_start_time"] = None
                fallback_state["last_vad_speech_time"] = time.time()  # Reset timer
                
        except Exception as e:
            logger.error("Error in fallback audio processing", 
                        caller_channel_id=caller_channel_id,
                        ssrc=ssrc,
                        error=str(e), 
                        exc_info=True)
    
    async def _ensure_audio_capture_enabled(self, caller_channel_id: str, delay: float = 5.0):
        """Fallback method to ensure audio capture is enabled after a delay."""
        if self.conversation_coordinator:
            await self.conversation_coordinator.schedule_capture_fallback(caller_channel_id, delay)
            return
        try:
            await asyncio.sleep(delay)
            
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if session:
                if not session.audio_capture_enabled:
                    session.audio_capture_enabled = True
                    await self._save_session(session)
                    logger.info("🎤 AUDIO CAPTURE - ✅ FALLBACK: Enabled after delay",
                               caller_channel_id=caller_channel_id,
                               delay=delay)
                else:
                    logger.debug("🎤 AUDIO CAPTURE - Already enabled, fallback not needed",
                               caller_channel_id=caller_channel_id)
            else:
                logger.debug("🎤 AUDIO CAPTURE - Call no longer active, skipping fallback",
                           caller_channel_id=caller_channel_id)
        except Exception as e:
            logger.error("Error in audio capture fallback", 
                        caller_channel_id=caller_channel_id,
                        error=str(e), 
                        exc_info=True)
    
    # Legacy TTS fallback methods removed - now handled by PlaybackManager through SessionStore
    
    async def _start_external_media_channel(self, caller_channel_id: str) -> Optional[str]:
        """Create an ExternalMedia channel for RTP communication."""
        try:
            if not self.config.external_media:
                logger.error("ExternalMedia configuration not found")
                return None
            
            # Build external host address - use configured RTP host
            external_host = self.config.external_media.rtp_host
            external_port = self.config.external_media.rtp_port
            codec = self.config.external_media.codec
            direction = self.config.external_media.direction
            
            logger.info("Creating ExternalMedia channel", 
                       caller_channel_id=caller_channel_id,
                       external_host=external_host,
                       external_port=external_port,
                       codec=codec,
                       direction=direction)
            
            # Create ExternalMedia channel
            external_media_id = await self.ari_client.create_external_media(
                external_host=external_host,
                external_port=external_port,
                fmt=codec,
                direction=direction
            )
            
            if not external_media_id:
                logger.error("Failed to create ExternalMedia channel")
                return
            
            if external_media_id:
                logger.info("ExternalMedia channel created successfully", 
                           caller_channel_id=caller_channel_id,
                           external_media_id=external_media_id)
                
                # ExternalMedia channel automatically enters Stasis when created with app parameter
                logger.info("ExternalMedia channel will enter Stasis automatically", 
                           external_media_id=external_media_id)
                return external_media_id
            else:
                logger.error("Failed to create ExternalMedia channel", 
                           caller_channel_id=caller_channel_id)
                return None
                
        except Exception as e:
            logger.error("Error creating ExternalMedia channel", 
                        caller_channel_id=caller_channel_id,
                        error=str(e), 
                        exc_info=True)
            return None
    
    async def _start_provider_session_external_media(self, caller_channel_id: str, external_media_id: str):
        """Start provider session for ExternalMedia channel."""
        try:
            # Get provider
            provider_name = self.config.default_provider
            provider = self.providers.get(provider_name)
            
            if not provider:
                logger.error("Provider not found", provider_name=provider_name)
                return
            
            # Generate call ID for RTP mapping
            call_id = f"call_{external_media_id}_{int(time.time())}"
            
            # Get session from SessionStore
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if not session:
                logger.error("No session found for caller channel", caller_channel_id=caller_channel_id)
                return
            
            # Update session with ExternalMedia info
            session.external_media_id = external_media_id
            session.status = "external_media_created"
            await self._save_session(session)
            logger.info("🔧 MIGRATION - Updated session with ExternalMedia info", 
                       call_id=caller_channel_id, 
                       external_media_id=external_media_id)
            
            # RTP audio routing now handled by SessionStore
            logger.debug("RTP audio routing handled by SessionStore")
            logger.info("ExternalMedia channel mapped to caller", 
                       caller_channel_id=caller_channel_id,
                       external_media_id=external_media_id,
                       call_id=call_id)
            
            # Note: SSRC mapping will be established when first RTP packet is received
            # We'll need to add a method to map SSRC to caller when we see the first packet
            
            # Set provider input mode for RTP (16kHz PCM)
            if hasattr(provider, 'set_input_mode'):
                provider.set_input_mode('pcm16_16k')  # RTP server sends 16kHz PCM directly
                logger.info("Set provider input mode for RTP", 
                           caller_channel_id=caller_channel_id, 
                           mode='pcm16_16k', 
                           provider=provider_name)
            
            # Start provider session
            await provider.start_session(caller_channel_id)
            
            # Play initial greeting
            greeting_text = self.config.llm.initial_greeting
            await self._play_greeting_external_media(caller_channel_id, greeting_text)
            
            logger.info("Provider session started for ExternalMedia", 
                       caller_channel_id=caller_channel_id,
                       external_media_id=external_media_id,
                       provider=provider_name,
                       call_id=call_id)
            
            # ARCHITECT FIX: Audio capture will be enabled after greeting playback completes
            # via PlaybackFinished event handler, not immediately after setup
            logger.info("🎤 AUDIO CAPTURE - Will be enabled after greeting playback completes",
                       caller_channel_id=caller_channel_id)
            
        except Exception as e:
            logger.error("Error starting provider session for ExternalMedia", 
                        caller_channel_id=caller_channel_id,
                        external_media_id=external_media_id,
                        error=str(e), 
                        exc_info=True)
    
    async def _play_greeting_external_media(self, caller_channel_id: str, greeting_text: str):
        """Play greeting audio for ExternalMedia channel using PlaybackManager."""
        try:
            # Get session and provider
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if not session:
                logger.error("No session found for greeting", caller_channel_id=caller_channel_id)
                return
                
            provider = self.providers.get(session.provider_name)
            if not provider:
                logger.error("No provider found for greeting", caller_channel_id=caller_channel_id, provider_name=session.provider_name)
                return

            if not hasattr(provider, "text_to_speech"):
                logger.debug(
                    "Skipping greeting synthesis - provider has no text_to_speech",
                    caller_channel_id=caller_channel_id,
                    provider=session.provider_name,
                )
                return
            
            # Generate TTS audio
            audio_data = await provider.text_to_speech(greeting_text)
            
            if audio_data:
                # Use PlaybackManager for greeting playback - it handles all gating logic
                call_id = caller_channel_id  # Use caller_channel_id as canonical call_id
                playback_id = await self.playback_manager.play_audio(
                    call_id, 
                    audio_data, 
                    playback_type="greeting"
                )
                
                if playback_id:
                    logger.info("🔊 GREETING START - Greeting playback started via PlaybackManager", 
                               caller_channel_id=caller_channel_id,
                               call_id=call_id,
                               playback_id=playback_id,
                               audio_size=len(audio_data))
                else:
                    logger.error("🔊 GREETING FAILED - PlaybackManager failed to start greeting playback", 
                               caller_channel_id=caller_channel_id,
                               call_id=call_id)
            else:
                logger.error("Failed to generate greeting audio", caller_channel_id=caller_channel_id)
                
        except Exception as e:
            logger.error("Error playing greeting for ExternalMedia", 
                        caller_channel_id=caller_channel_id,
                        error=str(e), 
                        exc_info=True)
    
    def _calculate_frame_energy(self, frame: bytes) -> float:
        """Calculate audio energy for a single frame."""
        try:
            import struct
            samples = struct.unpack(f'<{len(frame)//2}h', frame)
            energy = sum(sample * sample for sample in samples) / len(samples)
            return (energy ** 0.5) / 32768.0  # Normalize to 0-1
        except Exception:
            return 0.0

    def _normalize_to_dbfs(self, pcm16le: bytes, target_dbfs: float = -20.0, max_gain: float = 3.0) -> bytes:
        """Normalize audio to target dBFS for better STT accuracy."""
        if not pcm16le:
            return pcm16le
        
        try:
            import numpy as np  # type: ignore
            x = np.frombuffer(pcm16le, dtype=np.int16).astype(np.float32)
            rms = np.sqrt(np.mean(x * x)) + 1e-9
            dbfs = 20.0 * math.log10(rms / 32768.0)
            gain_db = target_dbfs - dbfs
            gain = pow(10.0, gain_db / 20.0)
            gain = min(max_gain, max(0.3, gain))  # clamp
            y = np.clip(x * gain, -32768, 32767).astype(np.int16)
            return y.tobytes()
        except ImportError:
            # Fallback without numpy
            logger.warning("NumPy not available, skipping audio normalization")
            return pcm16le

    def _convert_ulaw_to_pcm16le(self, ulaw_data: bytes) -> bytes:
        """Convert uLaw audio to PCM16LE format."""
        try:
            import struct
            
            # uLaw to linear conversion table (simplified)
            ulaw_table = [
                -32124, -31100, -30076, -29052, -28028, -27004, -25980, -24956,
                -23932, -22908, -21884, -20860, -19836, -18812, -17788, -16764,
                -15996, -15484, -14972, -14460, -13948, -13436, -12924, -12412,
                -11900, -11388, -10876, -10364, -9852, -9340, -8828, -8316,
                -7932, -7676, -7420, -7164, -6908, -6652, -6396, -6140,
                -5884, -5628, -5372, -5116, -4860, -4604, -4348, -4092,
                -3900, -3772, -3644, -3516, -3388, -3260, -3132, -3004,
                -2876, -2748, -2620, -2492, -2364, -2236, -2108, -1980,
                -1884, -1820, -1756, -1692, -1628, -1564, -1500, -1436,
                -1372, -1308, -1244, -1180, -1116, -1052, -988, -924,
                -876, -844, -812, -780, -748, -716, -684, -652,
                -620, -588, -556, -524, -492, -460, -428, -396,
                -372, -356, -340, -324, -308, -292, -276, -260,
                -244, -228, -212, -196, -180, -164, -148, -132,
                -120, -112, -104, -96, -88, -80, -72, -64,
                -56, -48, -40, -32, -24, -16, -8, 0,
                32124, 31100, 30076, 29052, 28028, 27004, 25980, 24956,
                23932, 22908, 21884, 20860, 19836, 18812, 17788, 16764,
                15996, 15484, 14972, 14460, 13948, 13436, 12924, 12412,
                11900, 11388, 10876, 10364, 9852, 9340, 8828, 8316,
                7932, 7676, 7420, 7164, 6908, 6652, 6396, 6140,
                5884, 5628, 5372, 5116, 4860, 4604, 4348, 4092,
                3900, 3772, 3644, 3516, 3388, 3260, 3132, 3004,
                2876, 2748, 2620, 2492, 2364, 2236, 2108, 1980,
                1884, 1820, 1756, 1692, 1628, 1564, 1500, 1436,
                1372, 1308, 1244, 1180, 1116, 1052, 988, 924,
                876, 844, 812, 780, 748, 716, 684, 652,
                620, 588, 556, 524, 492, 460, 428, 396,
                372, 356, 340, 324, 308, 292, 276, 260,
                244, 228, 212, 196, 180, 164, 148, 132,
                120, 112, 104, 96, 88, 80, 72, 64,
                56, 48, 40, 32, 24, 16, 8, 0
            ]
            
            # Convert each uLaw byte to PCM16LE
            pcm_samples = []
            for ulaw_byte in ulaw_data:
                pcm_sample = ulaw_table[ulaw_byte]
                pcm_samples.append(pcm_sample)
            
            # Pack as little-endian 16-bit samples
            return struct.pack(f'<{len(pcm_samples)}h', *pcm_samples)
            
        except Exception as e:
            logger.error("uLaw to PCM16LE conversion failed", error=str(e), exc_info=True)
            # Return original data as fallback
            return ulaw_data
    
    def _resample_8k_to_16k(self, audio_8k: bytes) -> bytes:
        """Resample 8kHz PCM16LE audio to 16kHz for main VAD system."""
        try:
            # Convert bytes to 16-bit samples
            samples_8k = struct.unpack(f'<{len(audio_8k)//2}h', audio_8k)
            
            # Simple upsampling: duplicate each sample (8kHz -> 16kHz)
            samples_16k = []
            for sample in samples_8k:
                samples_16k.append(sample)
                samples_16k.append(sample)  # Duplicate for 2x sample rate
            
            # Convert back to bytes
            return struct.pack(f'<{len(samples_16k)}h', *samples_16k)
            
        except Exception as e:
            logger.error("8kHz to 16kHz resampling failed", error=str(e), exc_info=True)
            # Return original data as fallback
            return audio_8k
    
    def _route_audio_frame(self, conn_id: str, frame: bytes, audio_energy: float):
        """Route a single audio frame to the appropriate provider."""
        try:
            # Route audio to appropriate provider
            channel_id = self.conn_to_channel.get(conn_id)
            if channel_id:
                # This method is not currently used - audio routing is handled elsewhere
                logger.debug("_route_audio_frame called but not used", 
                           conn_id=conn_id, channel_id=channel_id)
                return
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
                # Get RTP server stats if available
                rtp_stats = {}
                if hasattr(self, 'rtp_server') and self.rtp_server:
                    try:
                        rtp_stats = self.rtp_server.get_stats()
                    except Exception:
                        rtp_stats = {"error": "Failed to get RTP stats"}
                audiosocket_info = {
                    "listening": False,
                    "host": None,
                    "port": None,
                    "active_connections": 0,
                }
                if self.audio_socket_server:
                    try:
                        audiosocket_info = {
                            "listening": True,
                            "host": getattr(self.config.audiosocket, 'host', '0.0.0.0'),
                            "port": self.audio_socket_server.port,
                            "active_connections": self.audio_socket_server.get_connection_count(),
                        }
                    except Exception:
                        audiosocket_info["listening"] = True
                session_stats = await self.session_store.get_session_stats()
                conversation_summary = {}
                streaming_summary = {}
                streaming_details = []
                if self.conversation_coordinator:
                    conversation_summary = await self.conversation_coordinator.get_summary()
                    try:
                        streaming_summary = await self.conversation_coordinator.get_streaming_summary()
                    except Exception:
                        streaming_summary = {"error": "streaming summary failed"}
 
                    try:
                        sessions = await self.session_store.get_all_sessions()
                        for s in sessions:
                            streaming_details.append({
                                "call_id": s.call_id,
                                "provider": s.provider_name,
                                "streaming_started": bool(getattr(s, "streaming_started", False) or getattr(s, "current_stream_id", None)),
                                "bytes_sent": int(getattr(s, "streaming_bytes_sent", 0) or 0),
                                "fallbacks": int(getattr(s, "streaming_fallback_count", 0) or 0),
                                "last_error": getattr(s, "last_streaming_error", None),
                            })
                    except Exception:
                        pass
 
                data = {
                    "status": "healthy",
                    "ari_connected": bool(self.ari_client and self.ari_client.running),
                    "rtp_server_running": bool(getattr(self, 'rtp_server', None) and getattr(self.rtp_server, 'running', False)),
                    "audio_transport": self.config.audio_transport,
                    "active_calls": session_stats.get("active_calls", 0),
                    "active_playbacks": session_stats.get("active_playbacks", 0),
                    "providers": providers,
                    "rtp_server": rtp_stats,
                    "audiosocket": audiosocket_info,
                    "audiosocket_listening": audiosocket_info.get("listening", False),
                    "conversation": conversation_summary,
                    "streaming": streaming_summary,
                    "streaming_details": streaming_details,
                }
                return web.json_response(data)
            except Exception:
                return web.json_response({"error": "health handler failed"}, status=500)

        async def handle_metrics(request):
            return web.Response(body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

        app = web.Application()
        app.router.add_get('/health', handle_health)
        app.router.add_get('/metrics', handle_metrics)
        self._health_runner = web.AppRunner(app)
        await self._health_runner.setup()
        site = web.TCPSite(self._health_runner, host=os.getenv('HEALTH_HOST', '0.0.0.0'), port=int(os.getenv('HEALTH_PORT', '15000')))
        await site.start()
        logger.info("Health endpoint started", host=os.getenv('HEALTH_HOST', '0.0.0.0'), port=os.getenv('HEALTH_PORT', '15000'))

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
        
        # Check if channel was active and clean up immediately
        session = await self.session_store.get_by_call_id(channel_id)
        if session:
            logger.debug("Channel was active - cleaning up immediately", channel_id=channel_id)
            await self._cleanup_call(channel_id)
        else:
            logger.debug("Channel was not in active sessions", channel_id=channel_id)

    async def _on_playback_finished(self, event: dict) -> None:
        """Handle playback finished event by delegating to PlaybackManager."""
        playback_id = event.get("playback", {}).get("id")
        if not playback_id:
            logger.warning("🔊 PlaybackFinished event missing playback ID", event=event)
            return
            
        logger.info("🔊 Playback finished - delegating to PlaybackManager", playback_id=playback_id)
        
        # Delegate to PlaybackManager - it handles all gating logic
        success = await self.playback_manager.on_playback_finished(playback_id)
        
        if success:
            logger.info("🔊 PlaybackFinished handled successfully by PlaybackManager", 
                       playback_id=playback_id)
        else:
            logger.warning("🔊 PlaybackFinished failed in PlaybackManager", 
                         playback_id=playback_id)

    # Legacy TTS gating methods removed - now handled by PlaybackManager through SessionStore
        
        # Finalize delayed cleanup after TTS finishes
        channels_to_cleanup = []
        sessions = await self.session_store.get_all_sessions()
        for session in sessions:
            if getattr(session, 'cleanup_after_tts', False):
                channels_to_cleanup.append(session.call_id)
                logger.info("🔧 Finalizing delayed cleanup", channel_id=session.call_id)
        
        # Clean up channels that were marked for delayed cleanup
        for channel_id in channels_to_cleanup:
            logger.info("🔧 Finalizing delayed cleanup", channel_id=channel_id)
            await self._cleanup_call(channel_id)
        
        if channels_to_cleanup:
            logger.info("🔧 Delayed cleanup completed", 
                       channels_cleaned=len(channels_to_cleanup),
                       remaining_calls=len(sessions))

    async def _externalmedia_keepalive(self, conn_id: str):
        """Send periodic keepalive to prevent ExternalMedia idle timeouts."""
        try:
            while True:
                await asyncio.sleep(30)  # Send keepalive every 30 seconds
                
                # Check if connection is still active
                if conn_id not in self._keepalive_tasks:
                    logger.debug("ExternalMedia keepalive stopped - connection closed", conn_id=conn_id)
                    break
                
                # Send lightweight keepalive (no-op control frame)
                # This prevents Asterisk ExternalMedia from timing out during silence
                logger.debug("ExternalMedia keepalive sent", conn_id=conn_id)
                
        except asyncio.CancelledError:
            logger.debug("ExternalMedia keepalive cancelled", conn_id=conn_id)
        except Exception as e:
            logger.error("ExternalMedia keepalive error", conn_id=conn_id, error=str(e))

    async def on_provider_event(self, event: Dict[str, Any]):
        """Handle events from AI providers."""
        try:
            event_type = event.get("type")
            logger.debug("Received provider event", event_type=event_type, event_keys=list(event.keys()))
            
            if event_type == "AgentAudio":
                audio_data = event.get("data")
                call_id = event.get("call_id")
                is_streaming_chunk = event.get("streaming_chunk", False)
                if not audio_data:
                    return

                session = None
                if call_id:
                    session = await self.session_store.get_by_call_id(call_id)

                if not session:
                    sessions = await self.session_store.get_all_sessions()
                    if call_id:
                        for s in sessions:
                            if s.call_id == call_id:
                                session = s
                                break
                    if not session and sessions:
                        session = sessions[0]
                        if not call_id:
                            call_id = session.call_id

                if not session:
                    logger.warning("No active call found for AgentAudio buffering", call_id=call_id)
                    return

                # Handle streaming vs file-based playback
                if is_streaming_chunk and self.config.downstream_mode == "stream":
                    # Streaming mode - send chunk directly to streaming manager
                    await self._handle_streaming_audio_chunk(session, audio_data)
                else:
                    # File-based mode - buffer audio for later playback
                    if not hasattr(session, "agent_audio_buffer"):
                        session.agent_audio_buffer = bytearray()
                        session.last_agent_audio_ts = 0.0

                    session.agent_audio_buffer.extend(audio_data)
                    session.last_agent_audio_ts = time.monotonic()
                    await self._save_session(session)
                    logger.debug("Buffered AgentAudio chunk", call_id=session.call_id, buffer_len=len(session.agent_audio_buffer))

            elif event_type == "AgentAudioDone":
                call_id = event.get("call_id")
                is_streaming_done = event.get("streaming_done", False)
                session = None
                if call_id:
                    session = await self.session_store.get_by_call_id(call_id)

                if not session:
                    sessions = await self.session_store.get_all_sessions()
                    if call_id:
                        for s in sessions:
                            if s.call_id == call_id:
                                session = s
                                break
                    if not session and sessions:
                        session = sessions[0]
                        if not call_id:
                            call_id = session.call_id

                if not session:
                    logger.warning("AgentAudioDone received but session missing", call_id=call_id)
                    return

                # Handle streaming vs file-based playback
                if is_streaming_done and self.config.downstream_mode == "stream":
                    # Streaming mode - stop streaming playback
                    await self._handle_streaming_audio_done(session)
                else:
                    # File-based mode - play buffered audio
                    if not hasattr(session, "agent_audio_buffer"):
                        session.agent_audio_buffer = bytearray()
                        session.last_agent_audio_ts = 0.0

                    if not session.agent_audio_buffer:
                        logger.debug("AgentAudioDone with empty buffer", call_id=session.call_id)
                        return

                    audio_bytes = bytes(session.agent_audio_buffer)
                    session.agent_audio_buffer.clear()
                    now_ts = time.time()
                    turn_latency = None
                    transcription_latency = None
                    if session.last_user_speech_end_ts:
                        turn_latency = max(0.0, now_ts - session.last_user_speech_end_ts)
                        session.last_turn_latency_s = turn_latency
                    if session.last_transcription_ts:
                        transcription_latency = max(0.0, now_ts - session.last_transcription_ts)
                        session.last_transcription_latency_s = transcription_latency
                    session.last_response_start_ts = now_ts
                    await self._save_session(session)

                    playback_id = await self.playback_manager.play_audio(
                        session.call_id,
                        audio_bytes,
                        playback_type="response"
                    )

                    if playback_id:
                        if self.conversation_coordinator:
                            await self.conversation_coordinator.record_latency(
                                session,
                                turn_latency=turn_latency,
                                transcription_latency=transcription_latency,
                            )

                        if turn_latency is not None or transcription_latency is not None:
                            logger.info(
                                "⏱️ Turn latency recorded",
                                call_id=session.call_id,
                                provider=session.provider_name,
                                user_to_playback_s=None if turn_latency is None else round(turn_latency, 3),
                                transcription_to_playback_s=None if transcription_latency is None else round(transcription_latency, 3),
                            )

                        logger.info(
                            "🔊 TTS START - Response playback started via PlaybackManager",
                            channel_id=session.caller_channel_id,
                            call_id=session.call_id,
                            playback_id=playback_id,
                            audio_size=len(audio_bytes),
                        )

                        if session.conversation_state == "greeting":
                            session.conversation_state = "listening"
                            logger.info("Greeting completed, now listening for conversation", channel_id=session.caller_channel_id)
                        elif session.conversation_state == "processing":
                            session.conversation_state = "listening"
                            logger.info("Response played, listening for next user input", channel_id=session.caller_channel_id)

                        provider_timeout_task = getattr(session, "provider_timeout_task", None)
                        if provider_timeout_task and not provider_timeout_task.done():
                            provider_timeout_task.cancel()
                            session.provider_timeout_task = None
                            logger.debug("Cancelled provider timeout task - response received", channel_id=session.caller_channel_id)

                        await self._save_session(session)

                        if self.conversation_coordinator:
                            await self.conversation_coordinator.update_conversation_state(session.call_id, "listening")
                    else:
                        logger.error(
                            "🔊 TTS FAILED - PlaybackManager failed to start response playback",
                            channel_id=session.caller_channel_id,
                            call_id=session.call_id,
                        )
            elif event_type == "Ready":
                # Handle Ready event for streaming
                call_id = event.get("call_id")
                is_streaming_ready = event.get("streaming_ready", False)
                if call_id and is_streaming_ready:
                    await self._handle_streaming_ready(call_id)
                    
            elif event_type == "AgentResponse":
                # Handle AgentResponse event for streaming
                call_id = event.get("call_id")
                is_streaming_response = event.get("streaming_response", False)
                if call_id and is_streaming_response:
                    await self._handle_streaming_response(call_id)
                    
            elif event_type == "Transcription":
                # Handle transcription data
                text = event.get("text", "")
                call_id = event.get("call_id")
                logger.info("Received transcription from provider", text=text, text_length=len(text), call_id=call_id)
                if call_id:
                    session = await self.session_store.get_by_call_id(call_id)
                    if session:
                        session.last_transcript = text
                        session.last_transcription_ts = time.time()
                        session.conversation_state = "processing"
                        await self._save_session(session)
                        if self.conversation_coordinator:
                            await self.conversation_coordinator.update_conversation_state(call_id, "processing")
            elif event_type == "AgentResponse":
                response_text = event.get("text") or event.get("message") or ""
                call_id = event.get("call_id")
                logger.info("Received agent response", text=response_text, call_id=call_id)
                if call_id:
                    session = await self.session_store.get_by_call_id(call_id)
                    if session:
                        session.last_agent_response = response_text
                        session.last_agent_response_ts = time.time()
                        await self._save_session(session)
            elif event_type == "Error":
                # Handle provider errors
                error_msg = event.get("message", "Unknown provider error")
                logger.error("Provider reported error", error=error_msg, event=event)
            else:
                logger.debug("Unhandled provider event", event_type=event_type, event_keys=list(event.keys()))
        except Exception as e:
            logger.error("Error in provider event handler", event_type=event.get("type"), error=str(e), exc_info=True)

    async def _cleanup_call(self, channel_id: str):
        """Cleanup resources associated with a call."""
        logger.debug("Starting call cleanup", channel_id=channel_id)
        
        # Get session from SessionStore
        session = await self.session_store.get_by_call_id(channel_id)
        if session:
            logger.debug("Call found in SessionStore", channel_id=channel_id, call_id=session.call_id)

            # Cancel any pending timeout tasks
            timeout_task = getattr(session, 'timeout_task', None)
            if timeout_task and not timeout_task.done():
                timeout_task.cancel()
                logger.debug("Cancelled timeout task", channel_id=channel_id)

            
            # Cancel provider timeout task
            provider_timeout_task = getattr(session, 'provider_timeout_task', None)
            if provider_timeout_task and not provider_timeout_task.done():
                provider_timeout_task.cancel()
                logger.debug("Cancelled provider timeout task", channel_id=channel_id)
            
            provider = self.providers.get(session.provider_name)
            if provider:
                # CRITICAL FIX: Don't stop provider if TTS is still playing
                if session.tts_playing:
                    logger.info("🔇 CLEANUP DELAYED - TTS still playing, delaying provider cleanup", 
                              channel_id=channel_id)
                    # Mark for cleanup after TTS finishes
                    session.cleanup_after_tts = True
                else:
                    logger.debug("Stopping provider session", channel_id=channel_id)
                    await provider.stop_session()
                    session.provider_session_active = False

            # Hang up AudioSocket channel if present
            if session.audiosocket_channel_id:
                aso_channel_id = session.audiosocket_channel_id
                try:
                    await self.ari_client.hangup_channel(aso_channel_id)
                except Exception:
                    logger.debug(
                        "AudioSocket channel hangup encountered issue",
                        audiosocket_channel_id=aso_channel_id,
                        exc_info=True,
                    )
                self.audiosocket_channels.pop(session.call_id, None)
                self.bridges.pop(aso_channel_id, None)
                self.pending_audiosocket_channels.pop(aso_channel_id, None)
                session.audiosocket_channel_id = None

            if session.audiosocket_conn_id:
                conn_id = session.audiosocket_conn_id
                if self.audio_socket_server:
                    await self.audio_socket_server.disconnect(conn_id)
                self.conn_to_channel.pop(conn_id, None)
                self.conn_to_caller.pop(conn_id, None)
                self.channel_to_conn.pop(channel_id, None)
                ssrc = self.audiosocket_conn_to_ssrc.pop(conn_id, None)
                if ssrc is not None:
                    self.ssrc_to_caller.pop(ssrc, None)
                self.audiosocket_resample_state.pop(conn_id, None)
                session.audiosocket_conn_id = None

            # Cleanup UUID mapping for AudioSocket
            if session.audiosocket_uuid:
                self.uuidext_to_channel.pop(session.audiosocket_uuid, None)
                session.audiosocket_uuid = None

            # Remove bridge mapping for caller
            self.bridges.pop(session.call_id, None)

            # Clean up SSRC mapping
            ssrc_to_remove = []
            for ssrc, mapped_channel in self.ssrc_to_caller.items():
                if mapped_channel == channel_id:
                    ssrc_to_remove.append(ssrc)
            
            for ssrc in ssrc_to_remove:
                del self.ssrc_to_caller[ssrc]
                logger.debug("SSRC mapping cleaned up", ssrc=ssrc, channel_id=channel_id)

            # Remove from SessionStore
            await self.session_store.remove_call(session.call_id)
            if self.conversation_coordinator:
                await self.conversation_coordinator.unregister_call(session.call_id)
            logger.info("Call resources cleaned up successfully", channel_id=channel_id)
        else:
            logger.debug("Channel not found in SessionStore", channel_id=channel_id)

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

    # ExternalMedia TTS streaming removed - using ARI file playback instead
    # ExternalMedia is only for inbound audio (STT), not outbound (TTS)

    # Audio conversion methods removed - using ARI file playback instead

    async def _play_audio_via_bridge(self, channel_id: str, audio_data: bytes, playback_id: str = None, call_id: str = None):
        """Play audio via bridge to avoid interrupting ExternalMedia capture."""
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

            # Use provided playback_id or generate one
            if not playback_id:
                playback_id = f"tts:{channel_id}:{int(time.time()*1000)}"
            
            # Use provided call_id or fallback to channel_id
            canonical_call_id = call_id if call_id else channel_id
            
            # Play on bridge with client-specified playbackId for deterministic tracking
            response = await self.ari_client.send_command("POST", f"bridges/{bridge_id}/play?playbackId={playback_id}", 
                                             data={"media": asterisk_media_uri})
            
            logger.info("🔊 TTS PLAYBACK - Bridge playback started with deterministic ID", 
                       playback_id=playback_id, 
                       bridge_id=bridge_id, 
                       channel_id=channel_id,
                       canonical_call_id=canonical_call_id)
            
            # Legacy method - playback tracking now handled by PlaybackManager
            logger.debug("Legacy _play_ai_audio method - playback tracking handled by PlaybackManager")
            logger.info("🔊 TTS TRACKING - Playback mapped for TTS gating", 
                       playback_id=playback_id, 
                       channel_id=channel_id)
            
            logger.info("Audio played on bridge successfully", 
                       bridge_id=bridge_id, 
                       media_uri=asterisk_media_uri,
                       playback_id=playback_id)
            
        except Exception as e:
            logger.error("Failed to play audio via bridge, falling back to direct playback",
                        channel_id=channel_id, 
                        bridge_id=bridge_id,
                        error=str(e), exc_info=True)
            # Fallback to direct channel playback
            await self.ari_client.play_audio_response(channel_id, audio_data)

    async def _handle_streaming_audio_chunk(self, session: CallSession, audio_data: bytes) -> None:
        """Handle streaming audio chunk for real-time playback."""
        try:
            call_id = session.call_id

            # Initialize streaming if not already started
            if not hasattr(session, "streaming_audio_queue"):
                session.streaming_audio_queue = asyncio.Queue()
                session.streaming_started = False
                await self._save_session(session)

            # Add chunk to queue
            await session.streaming_audio_queue.put(audio_data)

            # Start streaming if not already started
            if not session.streaming_started:
                # If using AudioSocket but connection not yet bound, delay streaming start
                if self.config.audio_transport == "audiosocket" and not getattr(session, "audiosocket_conn_id", None):
                    logger.info(
                        "Streaming delayed - waiting for AudioSocket bind",
                        call_id=call_id,
                    )
                    return

                session.streaming_started = True
                stream_id = await self.streaming_playback_manager.start_streaming_playback(
                    call_id, session.streaming_audio_queue, "streaming-response"
                )

                if stream_id:
                    session.current_stream_id = stream_id
                    await self._save_session(session)
                    logger.info(
                        "🎵 STREAMING STARTED - Real-time audio streaming initiated",
                        call_id=call_id,
                        stream_id=stream_id,
                    )
                else:
                    logger.error("Failed to start streaming playback", call_id=call_id)
                    session.streaming_started = False
                    await self._save_session(session)
            
        except Exception as e:
            logger.error("Error handling streaming audio chunk",
                        call_id=session.call_id,
                        error=str(e),
                        exc_info=True)
    
    async def _handle_streaming_audio_done(self, session: CallSession) -> None:
        """Handle end of streaming audio."""
        try:
            call_id = session.call_id
            
            # Signal end of stream
            if hasattr(session, "streaming_audio_queue"):
                await session.streaming_audio_queue.put(None)  # End of stream signal
            
            # Stop streaming playback
            if hasattr(session, "current_stream_id"):
                await self.streaming_playback_manager.stop_streaming_playback(call_id)
                session.current_stream_id = None
                session.streaming_started = False
                await self._save_session(session)
                
                logger.info("🎵 STREAMING DONE - Real-time audio streaming completed",
                           call_id=call_id)
            
            # Update conversation state
            if session.conversation_state == "greeting":
                session.conversation_state = "listening"
                logger.info("Greeting completed, now listening for conversation", call_id=call_id)
            elif session.conversation_state == "processing":
                session.conversation_state = "listening"
                logger.info("Response streamed, listening for next user input", call_id=call_id)
            
            await self._save_session(session)
            
            if self.conversation_coordinator:
                await self.conversation_coordinator.update_conversation_state(call_id, "listening")
                
        except Exception as e:
            logger.error("Error handling streaming audio done",
                        call_id=session.call_id,
                        error=str(e),
                        exc_info=True)
    
    async def _handle_streaming_ready(self, call_id: str) -> None:
        """Handle streaming ready event."""
        try:
            session = await self.session_store.get_by_call_id(call_id)
            if session:
                session.streaming_ready = True
                await self._save_session(session)
                logger.info("🎵 STREAMING READY - Agent ready for streaming",
                           call_id=call_id)
        except Exception as e:
            logger.error("Error handling streaming ready",
                        call_id=call_id,
                        error=str(e))
    
    async def _handle_streaming_response(self, call_id: str) -> None:
        """Handle streaming response event."""
        try:
            session = await self.session_store.get_by_call_id(call_id)
            if session:
                session.streaming_response = True
                await self._save_session(session)
                logger.info("🎵 STREAMING RESPONSE - Agent generating streaming response",
                           call_id=call_id)
        except Exception as e:
            logger.error("Error handling streaming response",
                        call_id=call_id,
                        error=str(e))


async def main():
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
