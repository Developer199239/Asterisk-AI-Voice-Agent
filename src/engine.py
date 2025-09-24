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
        # 1) Load providers first (low risk)
        await self._load_providers()

        # 2) Start health server EARLY so diagnostics are available even if transport/ARI fail
        try:
            asyncio.create_task(self._start_health_server())
        except Exception:
            logger.debug("Health server failed to start", exc_info=True)

        # 3) Log transport and downstream modes
        logger.info("Runtime modes", audio_transport=self.config.audio_transport, downstream_mode=self.config.downstream_mode)

        # 4) Prepare AudioSocket transport (guarded)
        if self.config.audio_transport == "audiosocket":
            try:
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
                logger.info("AudioSocket server listening", host=host, port=port)
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
            except Exception as exc:
                logger.error("Failed to start AudioSocket transport", error=str(exc), exc_info=True)
                self.audio_socket_server = None

        # 5) Prepare RTP server for ExternalMedia transport (guarded)
        if self.config.audio_transport == "externalmedia":
            try:
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
            except Exception as exc:
                logger.error("Failed to start ExternalMedia RTP transport", error=str(exc), exc_info=True)
                self.rtp_server = None

        # 6) Connect to ARI regardless to keep readiness visible and allow Stasis handling
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
            if isinstance(provider_config_data, dict) and not provider_config_data.get("enabled", True):
                logger.info("Provider '%s' disabled in configuration; skipping initialization.", name)
                continue
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
                    
                    # Start the provider session now that media path is connected
                    await self._start_provider_session(caller_channel_id)
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
                
                
                # Start provider session now that media path is connected
                await self._start_provider_session(caller_channel_id)
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
                await self._start_provider_session(caller_channel_id)
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

    async def _handle_stasis_end(self, event: dict):
        """Handle StasisEnd event and clean up call resources."""
        try:
            channel = event.get("channel", {}) or {}
            channel_id = channel.get("id")
            if not channel_id:
                return
            logger.info("Stasis ended", channel_id=channel_id)
            await self._cleanup_call(channel_id)
        except Exception as exc:
            logger.error("Error handling StasisEnd", error=str(exc), exc_info=True)

    async def _handle_channel_destroyed(self, event: dict):
        """Clean up when a channel is destroyed."""
        try:
            channel = event.get("channel", {}) or {}
            channel_id = channel.get("id")
            if not channel_id:
                return
            logger.info("Channel destroyed", channel_id=channel_id)
            await self._cleanup_call(channel_id)
        except Exception as exc:
            logger.error("Error handling ChannelDestroyed", error=str(exc), exc_info=True)

    async def _handle_dtmf_received(self, event: dict):
        """Handle ChannelDtmfReceived events (informational logging for now)."""
        try:
            channel = event.get("channel", {}) or {}
            digit = event.get("digit")
            channel_id = channel.get("id")
            logger.info(
                "Channel DTMF received",
                channel_id=channel_id,
                digit=digit,
            )
        except Exception as exc:
            logger.error("Error handling ChannelDtmfReceived", error=str(exc), exc_info=True)

    async def _handle_channel_varset(self, event: dict):
        """Monitor ChannelVarset events for debugging configuration state."""
        try:
            channel = event.get("channel", {}) or {}
            variable = event.get("variable")
            value = event.get("value")
            channel_id = channel.get("id")
            logger.debug(
                "Channel variable set",
                channel_id=channel_id,
                variable=variable,
                value=value,
            )
        except Exception as exc:
            logger.error("Error handling ChannelVarset", error=str(exc), exc_info=True)

    async def _cleanup_call(self, channel_or_call_id: str) -> None:
        """Shared cleanup for StasisEnd/ChannelDestroyed paths."""
        try:
            # Resolve session by call_id first, then fallback to channel lookup.
            session = await self.session_store.get_by_call_id(channel_or_call_id)
            if not session:
                session = await self.session_store.get_by_channel_id(channel_or_call_id)
            if not session:
                logger.debug("No session found during cleanup", identifier=channel_or_call_id)
                return

            call_id = session.call_id
            logger.info("Cleaning up call", call_id=call_id)

            # Stop any active streaming playback.
            try:
                await self.streaming_playback_manager.stop_streaming_playback(call_id)
            except Exception:
                logger.debug("Streaming playback stop failed during cleanup", call_id=call_id, exc_info=True)

            # Stop the active provider session if one exists.
            try:
                provider_name = session.provider_name
                provider = self.providers.get(provider_name)
                if provider and hasattr(provider, "stop_session"):
                    await provider.stop_session()
            except Exception:
                logger.debug("Provider stop_session failed during cleanup", call_id=call_id, exc_info=True)

            # Tear down bridge.
            bridge_id = session.bridge_id
            if bridge_id:
                try:
                    await self.ari_client.destroy_bridge(bridge_id)
                    logger.info("Bridge destroyed", call_id=call_id, bridge_id=bridge_id)
                except Exception:
                    logger.debug("Bridge destroy failed", call_id=call_id, bridge_id=bridge_id, exc_info=True)

            # Hang up associated channels.
            for channel_id in filter(None, [session.caller_channel_id, session.local_channel_id, session.external_media_id, session.audiosocket_channel_id]):
                try:
                    await self.ari_client.hangup_channel(channel_id)
                except Exception:
                    logger.debug("Hangup failed during cleanup", call_id=call_id, channel_id=channel_id, exc_info=True)

            # Remove residual mappings so new calls don’t inherit.
            self.bridges.pop(session.caller_channel_id, None)
            if session.local_channel_id:
                self.pending_local_channels.pop(session.local_channel_id, None)
                self.local_channels.pop(session.caller_channel_id, None)
            if session.audiosocket_channel_id:
                self.pending_audiosocket_channels.pop(session.audiosocket_channel_id, None)
                self.audiosocket_channels.pop(session.caller_channel_id, None)
            if session.audiosocket_uuid:
                self.uuidext_to_channel.pop(session.audiosocket_uuid, None)

            # Finally remove the session.
            await self.session_store.remove_call(call_id)

            if self.conversation_coordinator:
                await self.conversation_coordinator.unregister_call(call_id)

            logger.info("Call cleanup completed", call_id=call_id)
        except Exception as exc:
            logger.error("Error cleaning up call", identifier=channel_or_call_id, error=str(exc), exc_info=True)

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
            call_id = session.call_id
            
            # Signal end of stream
            queue = getattr(session, "streaming_audio_queue", None)
            if queue:
                await queue.put(None)  # End of stream signal
            
            # Stop streaming playback
            if hasattr(session, "current_stream_id"):
                await self.streaming_playback_manager.stop_streaming_playback(call_id)
                session.current_stream_id = None
                session.streaming_started = False
            
            # Reset queue for the next response
            session.streaming_audio_queue = asyncio.Queue()
            await self._save_session(session)
            await self._reset_vad_after_playback(session)

            logger.info(
                "🎵 STREAMING DONE - Real-time audio streaming completed",
                call_id=call_id,
            )
            
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

    async def _audiosocket_handle_uuid(self, conn_id: str, uuid_str: str) -> bool:
        """Bind inbound AudioSocket connection to the caller channel via UUID."""
        try:
            caller_channel_id = self.uuidext_to_channel.get(uuid_str)
            if not caller_channel_id:
                logger.warning("AudioSocket UUID not recognized", conn_id=conn_id, uuid=uuid_str)
                return False

            # Track mappings
            self.conn_to_channel[conn_id] = caller_channel_id
            self.channel_to_conn[caller_channel_id] = conn_id
            self.channel_to_conns.setdefault(caller_channel_id, set()).add(conn_id)
            if caller_channel_id not in self.audiosocket_primary_conn:
                self.audiosocket_primary_conn[caller_channel_id] = conn_id

            # Update session
            session = await self.session_store.get_by_call_id(caller_channel_id)
            if session:
                session.audiosocket_uuid = uuid_str
                session.status = "audiosocket_bound"
                await self._save_session(session)

            logger.info(
                "AudioSocket connection bound to caller",
                conn_id=conn_id,
                uuid=uuid_str,
                caller_channel_id=caller_channel_id,
            )
            return True
        except Exception as exc:
            logger.error("Error binding AudioSocket UUID", conn_id=conn_id, uuid=uuid_str, error=str(exc), exc_info=True)
            return False

    async def _audiosocket_handle_audio(self, conn_id: str, audio_bytes: bytes) -> None:
        """Forward inbound AudioSocket audio to the active provider for the bound call."""
        try:
            caller_channel_id = self.conn_to_channel.get(conn_id)
            if not caller_channel_id and self.audio_socket_server:
                # Fallback: resolve via server's UUID registry
                try:
                    uuid_str = self.audio_socket_server.get_uuid_for_conn(conn_id)
                    if uuid_str:
                        caller_channel_id = self.uuidext_to_channel.get(uuid_str)
                        if caller_channel_id:
                            self.conn_to_channel[conn_id] = caller_channel_id
                except Exception:
                    pass

            if not caller_channel_id:
                logger.debug("AudioSocket audio received for unknown connection", conn_id=conn_id, bytes=len(audio_bytes))
                return

            session = await self.session_store.get_by_call_id(caller_channel_id)
            if not session:
                logger.debug("No session for caller; dropping AudioSocket audio", conn_id=conn_id, caller_channel_id=caller_channel_id)
                return

            # Post-TTS end protection: drop inbound briefly after gating clears to avoid agent echo re-capture
            try:
                cfg = getattr(self.config, 'barge_in', None)
                post_guard_ms = int(getattr(cfg, 'post_tts_end_protection_ms', 0)) if cfg else 0
            except Exception:
                post_guard_ms = 0
            if post_guard_ms and getattr(session, 'tts_ended_ts', 0.0) and session.audio_capture_enabled:
                try:
                    elapsed_ms = int((time.time() - float(session.tts_ended_ts)) * 1000)
                except Exception:
                    elapsed_ms = post_guard_ms
                if elapsed_ms < post_guard_ms:
                    logger.debug(
                        "Dropping inbound during post-TTS protection window",
                        call_id=caller_channel_id,
                        elapsed_ms=elapsed_ms,
                        protect_ms=post_guard_ms,
                    )
                    return

            # Self-echo mitigation and barge-in detection
            # If TTS is playing (capture disabled), decide whether to drop or trigger barge-in
            if hasattr(session, 'audio_capture_enabled') and not session.audio_capture_enabled:
                cfg = getattr(self.config, 'barge_in', None)
                if not cfg or not getattr(cfg, 'enabled', True):
                    logger.debug("Dropping inbound AudioSocket audio during TTS playback (barge-in disabled)",
                                 conn_id=conn_id, caller_channel_id=caller_channel_id, bytes=len(audio_bytes))
                    return

                # Protection window from TTS start to avoid initial self-echo
                now = time.time()
                tts_elapsed_ms = 0
                try:
                    if getattr(session, 'tts_started_ts', 0.0) > 0:
                        tts_elapsed_ms = int((now - session.tts_started_ts) * 1000)
                except Exception:
                    tts_elapsed_ms = 0

                initial_protect = int(getattr(cfg, 'initial_protection_ms', 200))
                if tts_elapsed_ms < initial_protect:
                    logger.debug("Dropping inbound during initial TTS protection window",
                                 conn_id=conn_id, caller_channel_id=caller_channel_id,
                                 tts_elapsed_ms=tts_elapsed_ms, protect_ms=initial_protect)
                    return

                # Barge-in detection: accumulate candidate window based on energy
                try:
                    energy = audioop.rms(audio_bytes, 2)
                except Exception:
                    energy = 0

                threshold = int(getattr(cfg, 'energy_threshold', 1000))
                frame_ms = 20  # AudioSocket frames are 20 ms
                if energy >= threshold:
                    session.barge_in_candidate_ms = int(getattr(session, 'barge_in_candidate_ms', 0)) + frame_ms
                else:
                    session.barge_in_candidate_ms = 0

                # Cooldown check to avoid flapping
                cooldown_ms = int(getattr(cfg, 'cooldown_ms', 500))
                last_barge_in_ts = float(getattr(session, 'last_barge_in_ts', 0.0) or 0.0)
                in_cooldown = (now - last_barge_in_ts) * 1000 < cooldown_ms if last_barge_in_ts else False

                min_ms = int(getattr(cfg, 'min_ms', 250))
                if not in_cooldown and session.barge_in_candidate_ms >= min_ms:
                    # Trigger barge-in: stop active playback(s), clear gating, and continue forwarding audio
                    try:
                        playback_ids = await self.session_store.list_playbacks_for_call(caller_channel_id)
                        for pid in playback_ids:
                            try:
                                await self.ari_client.stop_playback(pid)
                            except Exception:
                                logger.debug("Playback stop error during barge-in", playback_id=pid, exc_info=True)

                        # Clear all active gating tokens
                        tokens = list(getattr(session, 'tts_tokens', set()) or [])
                        for token in tokens:
                            try:
                                if self.conversation_coordinator:
                                    await self.conversation_coordinator.on_tts_end(caller_channel_id, token, reason="barge-in")
                            except Exception:
                                logger.debug("Failed to clear gating token during barge-in", token=token, exc_info=True)

                        session.barge_in_candidate_ms = 0
                        session.last_barge_in_ts = now
                        await self._save_session(session)
                        logger.info("🎧 BARGE-IN triggered", call_id=caller_channel_id)
                    except Exception:
                        logger.error("Error triggering barge-in", call_id=caller_channel_id, exc_info=True)
                    # After barge-in, fall through to forward this frame to provider
                else:
                    # Not yet triggered; drop inbound frame while TTS is active
                    if energy > 0:
                        if self.conversation_coordinator:
                            try:
                                self.conversation_coordinator.note_audio_during_tts(caller_channel_id)
                            except Exception:
                                pass
                    logger.debug("Dropping inbound during TTS (candidate_ms=%d, energy=%d)",
                                 session.barge_in_candidate_ms, energy)
                    return

            provider_name = session.provider_name or self.config.default_provider
            provider = self.providers.get(provider_name)
            if not provider or not hasattr(provider, 'send_audio'):
                logger.debug("Provider unavailable for audio", provider=provider_name)
                return

            await provider.send_audio(audio_bytes)
        except Exception as exc:
            logger.error("Error handling AudioSocket audio", conn_id=conn_id, error=str(exc), exc_info=True)

    async def _audiosocket_handle_disconnect(self, conn_id: str) -> None:
        """Cleanup mappings when an AudioSocket connection disconnects."""
        try:
            caller_channel_id = self.conn_to_channel.pop(conn_id, None)
            if caller_channel_id:
                conns = self.channel_to_conns.get(caller_channel_id, set())
                conns.discard(conn_id)
                if not conns:
                    self.channel_to_conns.pop(caller_channel_id, None)
                # Reset primary if needed
                if self.audiosocket_primary_conn.get(caller_channel_id) == conn_id:
                    self.audiosocket_primary_conn.pop(caller_channel_id, None)
                    if conns:
                        self.audiosocket_primary_conn[caller_channel_id] = next(iter(conns))
            logger.info("AudioSocket connection disconnected", conn_id=conn_id, caller_channel_id=caller_channel_id)
        except Exception as exc:
            logger.error("Error during AudioSocket disconnect cleanup", conn_id=conn_id, error=str(exc), exc_info=True)

    async def _audiosocket_handle_dtmf(self, conn_id: str, digit: str) -> None:
        """Handle DTMF received over AudioSocket (informational)."""
        try:
            caller_channel_id = self.conn_to_channel.get(conn_id)
            logger.info("AudioSocket DTMF received", conn_id=conn_id, caller_channel_id=caller_channel_id, digit=digit)
        except Exception as exc:
            logger.error("Error handling AudioSocket DTMF", conn_id=conn_id, error=str(exc), exc_info=True)

    def _build_deepgram_config(self, provider_cfg: Dict[str, Any]) -> Optional[DeepgramProviderConfig]:
        """Construct a DeepgramProviderConfig from raw provider settings with validation."""
        try:
            cfg = DeepgramProviderConfig(**provider_cfg)
            if not cfg.api_key:
                logger.error("Deepgram provider API key missing (DEEPGRAM_API_KEY)")
                return None
            return cfg
        except Exception as exc:
            logger.error("Failed to build DeepgramProviderConfig", error=str(exc), exc_info=True)
            return None

    async def on_provider_event(self, event: Dict[str, Any]):
        """Handle async events from the active provider (Deepgram/OpenAI/local).

        For file-based downstream (current default), buffer AgentAudio bytes until
        AgentAudioDone, then play the accumulated audio via PlaybackManager.
        """
        try:
            etype = event.get("type")
            call_id = event.get("call_id")
            if not call_id:
                return

            session = await self.session_store.get_by_call_id(call_id)
            if not session:
                logger.warning("Provider event for unknown call", event_type=etype, call_id=call_id)
                return

            # Downstream strategy: default to file playback; streaming path to be enabled later
            if etype == "AgentAudio":
                chunk: bytes = event.get("data") or b""
                if chunk:
                    session.agent_audio_buffer.extend(chunk)
                    session.last_agent_audio_ts = time.time()
                    await self._save_session(session)
            elif etype == "AgentAudioDone":
                if session.agent_audio_buffer:
                    audio = bytes(session.agent_audio_buffer)
                    session.agent_audio_buffer = bytearray()
                    await self._save_session(session)
                    # Play the accumulated response
                    playback_id = await self.playback_manager.play_audio(call_id, audio, "streaming-response")
                    if not playback_id:
                        logger.error("Failed to play provider audio", call_id=call_id, size=len(audio))
                else:
                    logger.debug("AgentAudioDone with empty buffer", call_id=call_id)
            else:
                # Log control/JSON events at debug for now
                logger.debug("Provider control event", event=event)

        except Exception as exc:
            logger.error("Error handling provider event", error=str(exc), exc_info=True)

    async def _start_provider_session(self, call_id: str) -> None:
        """Start the provider session for a call when media path is ready."""
        try:
            session = await self.session_store.get_by_call_id(call_id)
            if not session:
                logger.error("Start provider session called for unknown call", call_id=call_id)
                return

            provider_name = session.provider_name or self.config.default_provider
            provider = self.providers.get(provider_name)
            if not provider:
                logger.error("No provider found to start session", call_id=call_id, provider=provider_name)
                return

            await provider.start_session(call_id)
            session.provider_session_active = True
            await self._save_session(session)
            logger.info("Provider session started", call_id=call_id, provider=provider_name)
        except Exception as exc:
            logger.error("Failed to start provider session", call_id=call_id, error=str(exc), exc_info=True)

    async def _on_playback_finished(self, event: Dict[str, Any]):
        """Delegate ARI PlaybackFinished to PlaybackManager for gating and cleanup."""
        try:
            playback_id = None
            playback = event.get("playback", {}) or {}
            playback_id = playback.get("id") or event.get("playbackId")
            if not playback_id:
                logger.debug("PlaybackFinished without playback id", event=event)
                return
            await self.playback_manager.on_playback_finished(playback_id)
        except Exception as exc:
            logger.error("Error in PlaybackFinished handler", error=str(exc), exc_info=True)

    async def _start_health_server(self):
        """Start aiohttp health/metrics server on 0.0.0.0:15000."""
        try:
            app = web.Application()
            app.router.add_get('/live', self._live_handler)
            app.router.add_get('/ready', self._ready_handler)
            app.router.add_get('/health', self._health_handler)
            app.router.add_get('/metrics', self._metrics_handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', 15000)
            await site.start()
            self._health_runner = runner
            logger.info("Health endpoint started", host="0.0.0.0", port=15000)
        except Exception as exc:
            logger.error("Failed to start health endpoint", error=str(exc), exc_info=True)

    async def _health_handler(self, request):
        """Return JSON with engine/provider status."""
        try:
            providers = {}
            for name, prov in (self.providers or {}).items():
                ready = True
                try:
                    if hasattr(prov, 'is_ready'):
                        ready = bool(prov.is_ready())
                except Exception:
                    ready = True
                providers[name] = {"ready": ready}

            # Compute readiness
            default_ready = False
            if self.config and getattr(self.config, 'default_provider', None) in (self.providers or {}):
                prov = self.providers[self.config.default_provider]
                try:
                    default_ready = bool(prov.is_ready()) if hasattr(prov, 'is_ready') else True
                except Exception:
                    default_ready = True
            ari_connected = bool(self.ari_client and self.ari_client.running)
            audiosocket_listening = self.audio_socket_server is not None if self.config.audio_transport == 'audiosocket' else True
            is_ready = ari_connected and audiosocket_listening and default_ready

            payload = {
                "status": "healthy" if is_ready else "degraded",
                "ari_connected": ari_connected,
                "rtp_server_running": bool(getattr(self, 'rtp_server', None)),
                "audio_transport": self.config.audio_transport,
                "active_calls": len(await self.session_store.get_all_sessions()),
                "active_playbacks": 0,
                "providers": providers,
                "rtp_server": {},
                "audiosocket": {
                    "listening": audiosocket_listening,
                    "host": getattr(self.config.audiosocket, 'host', None) if self.config.audiosocket else None,
                    "port": getattr(self.config.audiosocket, 'port', None) if self.config.audiosocket else None,
                    "active_connections": (self.audio_socket_server.get_connection_count() if self.audio_socket_server else 0),
                },
                "audiosocket_listening": audiosocket_listening,
                "conversation": {
                    "gating_active": 0,
                    "capture_disabled": 0,
                    "barge_in_total": 0,
                },
                "streaming": {},
                "streaming_details": [],
            }
            return web.json_response(payload)
        except Exception as exc:
            return web.json_response({"status": "error", "error": str(exc)}, status=500)

    async def _live_handler(self, request):
        """Liveness probe: returns 200 if process is up."""
        return web.Response(text="ok", status=200)

    async def _ready_handler(self, request):
        """Readiness probe: 200 only if ARI, transport, and default provider are ready."""
        try:
            ari_connected = bool(self.ari_client and self.ari_client.running)
            transport_ok = True
            if self.config.audio_transport == 'audiosocket':
                transport_ok = self.audio_socket_server is not None
            elif self.config.audio_transport == 'externalmedia':
                transport_ok = self.rtp_server is not None
            provider_ok = False
            if self.config and getattr(self.config, 'default_provider', None) in (self.providers or {}):
                prov = self.providers[self.config.default_provider]
                try:
                    provider_ok = bool(prov.is_ready()) if hasattr(prov, 'is_ready') else True
                except Exception:
                    provider_ok = True

            is_ready = ari_connected and transport_ok and provider_ok
            status = 200 if is_ready else 503
            return web.json_response({
                "ari_connected": ari_connected,
                "transport_ok": transport_ok,
                "provider_ok": provider_ok,
                "ready": is_ready,
            }, status=status)
        except Exception as exc:
            return web.json_response({"ready": False, "error": str(exc)}, status=500)

    async def _metrics_handler(self, request):
        """Expose Prometheus metrics."""
        try:
            data = generate_latest()
            return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)
        except Exception as exc:
            return web.Response(text=str(exc), status=500)


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
