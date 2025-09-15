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
            self.audiosocket_server = AudioSocketServer(host=host, port=port, on_audio=self._on_audiosocket_audio, on_accept=self._on_audiosocket_accept)
            asyncio.create_task(self.audiosocket_server.start())
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
        
            
        caller_info = event["channel"]["caller"]
        logger.info(
            "New call received",
            channel_id=channel_id,
            caller={"name": caller_info["name"], "number": caller_info["number"]},
        )
        
        args = event.get('args', [])
        # If args[0] looks like a UUID (contains hyphens), it's the AudioSocket UUID
        # Otherwise, it's the provider name (legacy behavior)
        if args and len(args[0]) > 30 and '-' in args[0]:
            audiosocket_uuid = args[0]
            provider_name = args[1] if len(args) > 1 else self.config.default_provider
        else:
            audiosocket_uuid = None
            provider_name = args[0] if args else self.config.default_provider
        
        provider = self.providers.get(provider_name)

        if not provider:
            logger.error(f"Provider '{provider_name}' not found for channel {channel_id}.")
            await self.ari_client.hangup_channel(channel_id)
            return

        self.active_calls[channel_id] = {"provider": provider}
        
        try:
            await self.ari_client.answer_channel(channel_id)

            if self.config.audio_transport == "audiosocket":
                if audiosocket_uuid:
                    logger.info("Creating AudioSocket connection via ARI", channel_id=channel_id, audiosocket_uuid=audiosocket_uuid)
                    
                    # Create AudioSocket connection via ARI
                    success = await self.ari_client.create_audiosocket_connection(
                        channel_id=channel_id,
                        audiosocket_uuid=audiosocket_uuid,
                        host="127.0.0.1",
                        port=8090
                    )
                    
                    if success:
                        logger.info("AudioSocket connection created successfully", channel_id=channel_id)
                        
                        # Wait a moment for AudioSocket connection to establish
                        await asyncio.sleep(1.0)
                        
                        # Try to bind the connection
                        conn_id = None
                        if hasattr(self, 'audiosocket_server') and self.audiosocket_server:
                            try:
                                conn_id = self.audiosocket_server.try_get_connection_nowait()
                            except Exception:
                                conn_id = None
                        
                        if conn_id:
                            await self._bind_connection_to_channel(conn_id, channel_id, provider_name)
                            return
                        else:
                            logger.warning("AudioSocket created but no connection available yet", channel_id=channel_id)
                    else:
                        logger.error("Failed to create AudioSocket connection via ARI", channel_id=channel_id)
                        await self._cleanup_call(channel_id)
                        return
                else:
                    logger.error("No AudioSocket UUID provided", channel_id=channel_id)
                    await self._cleanup_call(channel_id)
                    return

            # Start the provider's session, which sets up audio handlers
            logger.debug("Starting provider session", channel_id=channel_id, provider=provider_name)
            await provider.start_session(channel_id)
            logger.debug("Provider session started successfully", channel_id=channel_id)
            
            # Initialize conversation state
            self.active_calls[channel_id]['conversation_state'] = 'greeting'
            
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

    async def _bind_connection_to_channel(self, conn_id: str, channel_id: str, provider_name: str):
        """Bind an accepted AudioSocket connection to a Stasis channel and start provider.

        Plays a one-time test prompt to validate audio path, then proceeds with provider flow.
        """
        try:
            self.conn_to_channel[conn_id] = channel_id
            self.channel_to_conn[channel_id] = conn_id
            logger.info("AudioSocket connection bound to channel", channel_id=channel_id, conn_id=conn_id)
            provider = self.active_calls.get(channel_id, {}).get('provider')
            if not provider:
                provider = self.providers.get(provider_name)
                if provider:
                    self.active_calls[channel_id] = {"provider": provider}
            # One-time test playback to confirm audio path
            try:
                # Only send over AudioSocket in streaming mode; otherwise use ARI demo tone
                if self.config.audio_transport == 'audiosocket' and self.config.downstream_mode == 'stream':
                    await self._send_test_tone_over_socket(conn_id)
                else:
                    await self.ari_client.play_media(channel_id, "sound:demo-congrats")
            except Exception:
                logger.debug("Test playback failed or unavailable", channel_id=channel_id, exc_info=True)
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
        """Bind any pending AudioSocket connection when AUDIOSOCKET_UUID variable is set."""
        try:
            variable = event_data.get('variable') or event_data.get('name')
            if variable != 'AUDIOSOCKET_UUID':
                return
            channel = event_data.get('channel', {})
            channel_id = channel.get('id')
            if not channel_id:
                return
            if channel_id in self.channel_to_conn:
                return
            # Bind any already-accepted connection
            if hasattr(self, 'audiosocket_server') and self.audiosocket_server:
                conn_id = None
                try:
                    conn_id = self.audiosocket_server.try_get_connection_nowait()
                except Exception:
                    conn_id = None
                if conn_id:
                    await self._bind_connection_to_channel(conn_id, channel_id, self.config.default_provider)
                else:
                    # Remember channel; will bind on next accept
                    self.pending_channel_for_bind = channel_id
        except Exception:
            logger.debug("Error in ChannelVarset handler", exc_info=True)

    def _on_audiosocket_accept(self, conn_id: str):
        """Attempt immediate bind on accept if a channel is pending."""
        try:
            channel_id = self.pending_channel_for_bind
            if not channel_id:
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
            channel_id = self.conn_to_channel.get(conn_id)
            if not channel_id:
                return
            call_data = self.active_calls.get(channel_id)
            if not call_data:
                return
            provider = call_data.get('provider')
            if provider:
                asyncio.create_task(provider.send_audio(audio_data))
        except Exception:
            logger.debug("Error routing AudioSocket audio", exc_info=True)

    async def on_provider_event(self, event: Dict[str, Any]):
        """Callback for providers to send events back to the engine."""
        try:
            event_type = event.get("type")
            logger.debug("Received provider event", event_type=event_type, event_keys=list(event.keys()))
            
            if event_type == "AgentAudio":
                # Handle audio data from the provider - now we need to play it back
                audio_data = event.get("data")
                if audio_data:
                    # Prefer streaming over AudioSocket only when explicitly enabled
                    if self.config.audio_transport == 'audiosocket' and self.config.downstream_mode == 'stream':
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
                                    # Convert ulaw->linear16
                                    out_bytes = audioop.ulaw2lin(audio_data, 2)
                                # Send downstream over socket
                                await self.audiosocket_server.send_audio(conn_id, out_bytes)
                                logger.debug("Streamed provider audio over AudioSocket", channel_id=channel_id, bytes=len(out_bytes), fmt=fmt, rate=rate)
                            except Exception:
                                logger.debug("Error streaming audio over AudioSocket; falling back to ARI", exc_info=True)
                                await self.ari_client.play_audio_response(channel_id, audio_data)
                    else:
                        # File-based playback via ARI (default path)
                        for channel_id, call_data in self.active_calls.items():
                            await self.ari_client.play_audio_response(channel_id, audio_data)
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
                if hasattr(self, 'audiosocket_server') and self.audiosocket_server:
                    try:
                        await self.audiosocket_server.close_connection(conn_id)
                        logger.debug("AudioSocket connection closed", conn_id=conn_id)
                    except Exception:
                        logger.debug("Error closing AudioSocket connection", conn_id=conn_id, exc_info=True)
            
            
            # Clean up bridge if it exists
            bridge_id = call_data.get("bridge_id")
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
        """Send a short test tone over AudioSocket to verify downstream audio path."""
        try:
            # Determine negotiated format if available
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
            duration_sec = ms / 1000.0
            freq = 440.0
            import math
            if fmt.startswith('slin'):
                samples = int(rate * duration_sec)
                pcm = bytearray()
                for n in range(samples):
                    val = int(0.2 * 32767 * math.sin(2 * math.pi * freq * (n / rate)))
                    pcm.extend(val.to_bytes(2, 'little', signed=True))
                await self.audiosocket_server.send_audio(conn_id, bytes(pcm))
            else:
                true_rate = rate if rate else 8000
                samples = int(true_rate * duration_sec)
                pcm = bytearray()
                for n in range(samples):
                    val = int(0.2 * 32767 * math.sin(2 * math.pi * freq * (n / true_rate)))
                    pcm.extend(val.to_bytes(2, 'little', signed=True))
                ulaw_bytes = audioop.lin2ulaw(bytes(pcm), 2)
                await self.audiosocket_server.send_audio(conn_id, ulaw_bytes)
            logger.info("Sent test tone over AudioSocket", conn_id=conn_id, fmt=fmt, rate=rate, ms=ms)
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
