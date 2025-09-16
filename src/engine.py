import asyncio
import os
import random
import signal
import struct
import uuid
import audioop
import base64
from typing import Dict, Any, Optional

from .ari_client import ARIClient
from aiohttp import web
from .config import AppConfig, load_config, DeepgramProviderConfig, LocalProviderConfig
from .logging_config import get_logger, configure_logging
from .providers.base import AIProviderInterface
from .audiosocket_server import AudioSocketServer
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
        self.conn_to_channel: Dict[str, str] = {}
        self.channel_to_conn: Dict[str, str] = {}
        self.pending_channel_for_bind: Optional[str] = None
        # Audio buffering for better playback quality
        self.audio_buffers: Dict[str, bytes] = {}
        self.buffer_size = 1600  # 200ms of audio at 8kHz (1600 bytes of ulaw)
        self.audiosocket_server: Any = None
        # Headless sessions for AudioSocket-only mode (no ARI channel)
        self.headless_sessions: Dict[str, Dict[str, Any]] = {}
        # Bridge and Local channel tracking for Local Channel Bridge pattern
        self.bridges: Dict[str, str] = {}  # channel_id -> bridge_id
        self.local_channels: Dict[str, str] = {}  # channel_id -> local_channel_id
        # Map our synthesized UUID extension to the real ARI caller channel id
        self.uuidext_to_channel: Dict[str, str] = {}
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

    async def _handle_stasis_start(self, event: dict):
        """Handle a new call entering Stasis using Local Channel Bridge pattern."""
        logger.debug("StasisStart event received", event_data=event)
        channel = event.get('channel', {})
        channel_id = channel.get('id')
        caller_info = channel.get('caller', {})
        logger.info("New call received", channel_id=channel_id,
                    caller={"name": caller_info.get("name"), "number": caller_info.get("number")})

        provider = self.providers.get(self.config.default_provider)
        if not provider:
            logger.error("Default provider not found", provider=self.config.default_provider)
            await self.ari_client.hangup_channel(channel_id)
            return

        try:
            # Answer the channel
            await self.ari_client.answer_channel(channel_id)
            logger.info("Channel answered", channel_id=channel_id)

            # Create a new mixing bridge
            bridge_id = await self.ari_client.create_bridge(bridge_type="mixing")
            if not bridge_id:
                raise RuntimeError("Failed to create mixing bridge")
            logger.info("Created bridge", bridge_id=bridge_id, channel_id=channel_id)

            # Originate Local channel to run our media fork dialplan
            # Pass the original channel_id as a variable for AudioSocket to use
            # Use Local pattern with UUID in the extension so dialplan can read it via ${EXTEN}
            uuid_ext = (channel_id or "").replace('.', '-')
            # Map synthesized UUID to the real caller channel for later binder lookup
            try:
                if uuid_ext:
                    self.uuidext_to_channel[uuid_ext] = channel_id
            except Exception:
                logger.debug("Could not map uuid_ext to channel id", uuid_ext=uuid_ext, channel_id=channel_id, exc_info=True)
            local_endpoint = f"Local/{uuid_ext}@ai-agent-media-fork/n"
            # ARI requires extension/context/priority; keep them even though Local has them embedded
            # No need to pass variables; dialplan derives AUDIOSOCKET_UUID from ${EXTEN}
            orig_params = [
                ("endpoint", local_endpoint),
                ("extension", "s"),
                ("context", "ai-agent-media-fork"),
                ("priority", "1"),
                ("timeout", "30"),
            ]
            logger.info("Originating Local channel for AudioSocket", endpoint=local_endpoint, bridged_channel=channel_id)

            local_channel_id = None
            attempts = 0
            max_attempts = 1  # Enforce single Local originate per call
            last_response: Any = None
            while attempts < max_attempts and not local_channel_id:
                attempts += 1
                try:
                    last_response = await self.ari_client.send_command("POST", "channels", params=orig_params)
                    # Not all Asterisk builds return the created channel id here; prefer discovery loop below
                    logger.debug("Local channel originate response", attempt=attempts, response=last_response)
                except Exception:
                    logger.error("Local channel originate failed", attempt=attempts, exc_info=True)
                if not local_channel_id:
                    await asyncio.sleep(0.2)

            if not local_channel_id:
                logger.error("Failed to originate Local channel after retries", response=last_response)
                raise RuntimeError("Failed to originate Local channel")

            logger.info("Originated Local channel for AudioSocket", 
                       local_channel_id=local_channel_id, 
                       channel_id=channel_id)

            # Discover Local leg by name since id may not be returned by originate
            discovered = False
            for i in range(20):  # up to ~2s total
                chan_list = await self.ari_client.send_command("GET", "channels")
                try:
                    candidates = []
                    if isinstance(chan_list, list):
                        for c in chan_list:
                            name = (c or {}).get('name', '')
                            if name.startswith(f"Local/{uuid_ext}@ai-agent-media-fork"):
                                candidates.append(c)
                    if candidates:
                        # Prefer the ;1 leg
                        chosen = None
                        for c in candidates:
                            if c.get('name', '').endswith(';1'):
                                chosen = c
                                break
                        if not chosen:
                            chosen = candidates[0]
                        local_channel_id = chosen.get('id')
                        discovered = True
                        logger.info("Discovered Local channel", uuid_ext=uuid_ext, local_channel_id=local_channel_id, local_name=chosen.get('name'))
                        break
                except Exception:
                    logger.debug("Error scanning channels for Local leg", exc_info=True)
                logger.debug("Waiting for Local channel presence", attempt=i+1, uuid_ext=uuid_ext, found=discovered)
                await asyncio.sleep(0.1)
            if not discovered or not local_channel_id:
                logger.error("Local channel did not appear in time", uuid_ext=uuid_ext)
                raise RuntimeError("Local channel not present for bridging")

            # Add both the original caller and the new local channel to the bridge with retries and diagnostics
            async def _bridge_add_with_retries(b_id: str, ch_id: str, label: str) -> bool:
                for j in range(5):  # up to ~1.25s with backoff
                    ok = await self.ari_client.add_channel_to_bridge(b_id, ch_id)
                    logger.debug("Bridge add attempt", bridge_id=b_id, channel_id=ch_id, label=label, attempt=j+1, success=ok)
                    if ok:
                        return True
                    await asyncio.sleep(0.25)
                return False

            # Ensure caller is on the bridge (idempotent)
            ok_caller = await _bridge_add_with_retries(bridge_id, channel_id, "caller")
            ok_local = await _bridge_add_with_retries(bridge_id, local_channel_id, "local")

            # Snapshot bridge state for debugging
            bridge_info = await self.ari_client.send_command("GET", f"bridges/{bridge_id}")
            bridge_channels = []
            try:
                if isinstance(bridge_info, dict):
                    bridge_channels = bridge_info.get('channels', []) or []
            except Exception:
                pass
            logger.info("Bridge state after add attempts", bridge_id=bridge_id, ok_caller=ok_caller, ok_local=ok_local, channels=bridge_channels)

            if not (ok_caller and ok_local):
                logger.error("Failed to add one or more channels to bridge", bridge_id=bridge_id, channel_id=channel_id, local_channel_id=local_channel_id)
                raise RuntimeError("Bridge add failed for Local pattern")

            # Store the bridge and local channel IDs for later use and cleanup
            self.bridges[channel_id] = bridge_id
            self.local_channels[channel_id] = local_channel_id

            # Initialize the provider pipeline
            self.active_calls[channel_id] = {
                "provider": provider,
                "conversation_state": "greeting",
                "bridge_id": bridge_id,
                "local_channel_id": local_channel_id
            }

            # Start provider session
            await provider.start_session(channel_id)
            logger.info("Provider session started", channel_id=channel_id, provider=self.config.default_provider)

            # Play initial greeting
            if hasattr(provider, 'play_initial_greeting'):
                logger.debug("Playing initial greeting", channel_id=channel_id)
                await provider.play_initial_greeting(channel_id)
                logger.debug("Initial greeting played", channel_id=channel_id)
            else:
                logger.debug("Provider does not have play_initial_greeting method", channel_id=channel_id)

        except Exception as e:
            logger.error("Failed Local Channel Bridge setup", channel_id=channel_id, error=str(e), exc_info=True)
            await self._cleanup_call(channel_id)

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
                logger.debug("Starting provider session", channel_id=channel_id, provider=provider_name)
                await provider.start_session(channel_id)
                logger.debug("Provider session started successfully", channel_id=channel_id)
                if hasattr(provider, 'play_initial_greeting'):
                    logger.debug("Playing initial greeting", channel_id=channel_id)
                    await provider.play_initial_greeting(channel_id)
                    logger.debug("Initial greeting played", channel_id=channel_id)
        except Exception:
            logger.error("Error binding connection to channel", channel_id=channel_id, conn_id=conn_id, exc_info=True)

    async def _handle_channel_varset(self, event_data: dict):
        """Bind any pending AudioSocket connection when AUDIOSOCKET_UUID variable is set.

        In the Local media-fork pattern, the var is set on the Local channel, but its value
        contains the original caller channel_id. We must bind the AudioSocket to that original channel.
        """
        try:
            variable = event_data.get('variable') or event_data.get('name')
            if variable != 'AUDIOSOCKET_UUID':
                return
            # Extract synthesized UUID or target (original) channel id from the variable value
            raw_val = event_data.get('value') or event_data.get('newvalue')
            target_channel_id = raw_val
            # If value is a synthesized uuid_ext (contains '-' from our mapping), resolve to real channel id
            try:
                if raw_val and raw_val in getattr(self, 'uuidext_to_channel', {}):
                    target_channel_id = self.uuidext_to_channel.get(raw_val)
                    logger.debug("Resolved uuid_ext to channel id", uuid_ext=raw_val, channel_id=target_channel_id)
            except Exception:
                logger.debug("Could not resolve uuid_ext mapping", uuid_ext=raw_val, exc_info=True)
            if not target_channel_id:
                # Fallback to using the event channel id, but log it for diagnostics
                channel = event_data.get('channel', {})
                fallback_id = channel.get('id')
                logger.warning("AUDIOSOCKET_UUID varset missing value; falling back to event channel id",
                               event_channel_id=fallback_id)
                target_channel_id = fallback_id
            if not target_channel_id:
                return
            if target_channel_id in self.channel_to_conn:
                return
            # Bind any already-accepted connection
            if hasattr(self, 'audiosocket_server') and self.audiosocket_server:
                conn_id = None
                try:
                    conn_id = self.audiosocket_server.try_get_connection_nowait()
                except Exception:
                    conn_id = None
                if conn_id:
                    await self._bind_connection_to_channel(conn_id, target_channel_id, self.config.default_provider)
                else:
                    # Remember channel; will bind on next accept
                    self.pending_channel_for_bind = target_channel_id
            logger.info("ChannelVarset bound or queued", variable=variable, target_channel_id=target_channel_id)
        except Exception:
            logger.debug("Error in ChannelVarset handler", exc_info=True)

    def _on_audiosocket_accept(self, conn_id: str):
        """Bind to pending ARI channel or start a headless session on accept."""
        try:
            logger.info("on_accept invoked", conn_id=conn_id, pending_channel=self.pending_channel_for_bind)
            channel_id = self.pending_channel_for_bind
            if not channel_id:
                # Start headless provider session (AudioSocket-only)
                provider_name = self.config.default_provider
                provider = self.providers.get(provider_name)
                if not provider:
                    logger.error("Default provider not found for headless session", provider=provider_name)
                    return
                logger.info("No pending ARI channel; starting headless session", conn_id=conn_id)
                # Hint input mode for local provider (PCM16 8k from AudioSocket)
                try:
                    if hasattr(provider, 'set_input_mode'):
                        provider.set_input_mode('pcm16_8k')
                except Exception:
                    logger.debug("Could not set provider input mode", exc_info=True)
                asyncio.get_event_loop().create_task(self._start_headless_session(conn_id, provider))
                # Send a short test tone over socket to confirm downstream path
                try:
                    asyncio.get_event_loop().create_task(self._send_test_tone_over_socket(conn_id, ms=1200))
                except Exception:
                    logger.debug("Could not schedule test tone", conn_id=conn_id, exc_info=True)
                return
            if channel_id in self.channel_to_conn:
                self.pending_channel_for_bind = None
                return
            # Fire-and-forget binding task
            asyncio.get_event_loop().create_task(
                self._bind_connection_to_channel(conn_id, channel_id, self.config.default_provider)
            )
            self.pending_channel_for_bind = None
        except Exception:
            logger.debug("Error in on_accept binder", exc_info=True)

    async def _start_headless_session(self, conn_id: str, provider: AIProviderInterface):
        """Start provider session without ARI channel; stream via AudioSocket."""
        try:
            logger.info("Starting headless session", conn_id=conn_id)
            await provider.start_session(conn_id)
            self.headless_sessions[conn_id] = {"provider": provider, "conversation_state": "greeting"}
            # Optional initial greeting
            if hasattr(provider, 'play_initial_greeting'):
                try:
                    await provider.play_initial_greeting(conn_id)
                    logger.debug("Headless initial greeting requested", conn_id=conn_id)
                except Exception:
                    logger.debug("Headless initial greeting failed", conn_id=conn_id, exc_info=True)
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
            import audioop
            
            # Convert ulaw to linear for energy calculation
            linear_data = audioop.ulaw2lin(audio_data, 2)
            
            # Calculate RMS (Root Mean Square) energy
            rms = audioop.rms(linear_data, 2)
            
            # Lower threshold for better sensitivity to phone audio
            # Phone audio typically has lower energy levels than studio recordings
            voice_threshold = 200  # Reduced from 500 based on testing
            
            has_voice = rms > voice_threshold
            if has_voice:
                logger.debug("Voice activity detected", rms=rms, threshold=voice_threshold)
            
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
            if channel_id in self.active_calls:
                call_data = self.active_calls.get(channel_id)
                if call_data:
                    provider = call_data.get('provider')
                    if provider and hasattr(provider, 'handle_dtmf'):
                        await provider.handle_dtmf(digit)

    def _on_audiosocket_audio(self, conn_id: str, audio_data: bytes):
        """Route inbound AudioSocket audio to the mapped provider for that connection."""
        try:
            # Enhanced debugging: log audio capture details
            try:
                count = self._audio_rx_debug.get(conn_id, 0) + 1
                if count <= 20:  # Increased from 8 to 20 for more debugging
                    preview = audio_data[:8]
                    # Calculate audio energy for VAD detection
                    audio_energy = 0
                    if len(audio_data) >= 2:
                        # Convert ulaw to PCM16 first, then calculate energy
                        import struct
                        try:
                            # Convert ulaw audio to PCM16 for energy calculation
                            pcm_data = audioop.ulaw2lin(audio_data, 2)
                            samples = struct.unpack(f'<{len(pcm_data)//2}h', pcm_data)
                            audio_energy = sum(sample * sample for sample in samples) / len(samples)
                            audio_energy = (audio_energy ** 0.5) / 32768.0  # Normalize to 0-1
                        except Exception as e:
                            logger.debug("Error calculating audio energy", error=str(e))
                            audio_energy = 0
                    
                    logger.info("🎤 AudioSocket inbound chunk",
                                 conn_id=conn_id,
                                 bytes=len(audio_data),
                                 first8=preview.hex(" "),
                                 multiple_of_2=(len(audio_data) % 2 == 0),
                                 audio_energy=f"{audio_energy:.4f}",
                                 chunk_number=count)
                elif count % 50 == 0:  # Log every 50th chunk after initial 20
                    logger.debug("🎤 AudioSocket continuing",
                                 conn_id=conn_id,
                                 bytes=len(audio_data),
                                 chunk_number=count)
                self._audio_rx_debug[conn_id] = count
            except Exception as e:
                logger.debug("Error in audio debug logging", exc_info=True)
            
            # Route audio to appropriate provider
            channel_id = self.conn_to_channel.get(conn_id)
            if channel_id:
                call_data = self.active_calls.get(channel_id)
                if not call_data:
                    logger.warning("🚨 Audio received but no active call data found", 
                                   conn_id=conn_id, channel_id=channel_id)
                    return
                provider = call_data.get('provider')
                if provider:
                    logger.debug("🎯 Routing audio to provider", 
                                 conn_id=conn_id, channel_id=channel_id, 
                                 provider=type(provider).__name__)
                    # Convert ulaw to PCM16 before sending to provider
                    try:
                        pcm_data = audioop.ulaw2lin(audio_data, 2)
                        asyncio.create_task(provider.send_audio(pcm_data))
                    except Exception as e:
                        logger.error("Failed to convert audio for provider", error=str(e))
                        # Fallback: send original data
                        asyncio.create_task(provider.send_audio(audio_data))
                else:
                    logger.warning("🚨 Audio received but no provider found", 
                                   conn_id=conn_id, channel_id=channel_id)
            else:
                # Headless mapping by conn_id
                session = self.headless_sessions.get(conn_id)
                if not session:
                    logger.warning("🚨 Audio received but no headless session found", 
                                   conn_id=conn_id)
                    return
                provider = session.get('provider')
                if provider:
                    logger.debug("🎯 Routing audio to headless provider", 
                                 conn_id=conn_id, provider=type(provider).__name__)
                    # Convert ulaw to PCM16 before sending to provider
                    try:
                        pcm_data = audioop.ulaw2lin(audio_data, 2)
                        asyncio.create_task(provider.send_audio(pcm_data))
                    except Exception as e:
                        logger.error("Failed to convert audio for headless provider", error=str(e))
                        # Fallback: send original data
                        asyncio.create_task(provider.send_audio(audio_data))
                else:
                    logger.warning("🚨 Audio received but no headless provider found", 
                                   conn_id=conn_id)
        except Exception as e:
            logger.error("🚨 Error routing AudioSocket audio", 
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
                            # Convert provider ulaw TTS to PCM16LE@8k for AudioSocket
                            out_bytes = audioop.ulaw2lin(audio_data, 2)
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
                                    out_bytes = audio_data
                                    if fmt.startswith('slin'):
                                        out_bytes = audioop.ulaw2lin(audio_data, 2)
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
                            logger.debug(f"Sent {len(audio_data)} bytes of audio to call channel {channel_id}")
                            
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
            
            provider = call_data.get("provider")
            if provider:
                logger.debug("Stopping provider session", channel_id=channel_id)
                await provider.stop_session()
                
            # Close bound AudioSocket connection if any
            conn_id = self.channel_to_conn.pop(channel_id, None)
            if conn_id:
                logger.debug("Closing AudioSocket connection", channel_id=channel_id, conn_id=conn_id)
                self.conn_to_channel.pop(conn_id, None)
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
            
            # Remove from active calls (with safety check for race conditions)
            if channel_id in self.active_calls:
                del self.active_calls[channel_id]
                logger.info("Call resources cleaned up successfully", channel_id=channel_id)
            else:
                logger.debug("Channel already removed from active calls", channel_id=channel_id)
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
