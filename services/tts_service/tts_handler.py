"""
OpenAI Realtime API Text-to-Speech (TTS) Handler

This module provides specialized functionality for streaming TTS operations
using the OpenAI Realtime API.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from .realtime_client import RealtimeClient, RealtimeConfig, VoiceType

logger = logging.getLogger(__name__)


class TTSState(Enum):
    """TTS processing states."""
    IDLE = "idle"
    PROCESSING = "processing"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ERROR = "error"


class AudioFormat(Enum):
    """Audio output formats."""
    PCM_16KHZ = "pcm_16khz"
    PCM_24KHZ = "pcm_24khz"
    MP3_64K = "mp3_64k"
    MP3_128K = "mp3_128k"
    OPUS_64K = "opus_64k"
    OPUS_128K = "opus_128k"


@dataclass
class TTSConfig:
    """Configuration for TTS handler."""
    # Voice settings
    voice: VoiceType = VoiceType.ALLOY
    speed: float = 1.0  # 0.25 to 4.0
    pitch: float = 1.0  # 0.25 to 4.0
    volume: float = 1.0  # 0.0 to 1.0
    
    # Audio settings
    audio_format: AudioFormat = AudioFormat.PCM_24KHZ
    sample_rate: int = 24000
    channels: int = 1  # Mono
    bit_depth: int = 16
    
    # Streaming settings
    chunk_size: int = 1024  # Audio chunk size in bytes
    buffer_size: int = 8192  # Buffer size for audio data
    enable_streaming: bool = True
    enable_realtime: bool = True
    
    # Quality settings
    enable_ssml: bool = False
    enable_emotion: bool = False
    enable_pronunciation: bool = False
    
    # Callback settings
    on_audio_chunk: Optional[Callable[[bytes], None]] = None
    on_speech_start: Optional[Callable[[], None]] = None
    on_speech_end: Optional[Callable[[], None]] = None
    on_synthesis_complete: Optional[Callable[[Dict[str, Any]], None]] = None
    on_error: Optional[Callable[[str, Exception], None]] = None
    
    # Logging
    enable_logging: bool = True
    log_level: str = "INFO"


@dataclass
class TTSResponse:
    """TTS response structure."""
    audio_data: bytes = b""
    text: str = ""
    is_complete: bool = False
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 0
    audio_length: int = 0
    sample_rate: int = 24000
    channels: int = 1
    bit_depth: int = 16
    metadata: Dict[str, Any] = field(default_factory=dict)


class TTSHandler:
    """
    Text-to-Speech handler using OpenAI Realtime API.
    
    This handler manages the streaming TTS process, including text processing,
    audio generation, and streaming audio output.
    """
    
    def __init__(self, config: TTSConfig, realtime_client: RealtimeClient):
        """Initialize the TTS handler."""
        self.config = config
        self.client = realtime_client
        self.state = TTSState.IDLE
        
        # Audio management
        self.current_response = TTSResponse()
        self.audio_buffer = b""
        self._is_speaking = False
        
        # Statistics
        self.stats = {
            'texts_processed': 0,
            'syntheses_completed': 0,
            'audio_chunks_received': 0,
            'total_audio_bytes': 0,
            'average_synthesis_time_ms': 0,
            'errors': 0,
            'speech_events': 0
        }
        
        # Processing tracking
        self.synthesis_start_time = 0
        self.last_activity_time = 0
        
        # Setup client callbacks
        self._setup_client_callbacks()
    
    def _setup_client_callbacks(self):
        """Setup callbacks for the Realtime client."""
        self.client.on_audio = self._handle_audio_chunk
        self.client.on_response_done = self._handle_synthesis_complete
        self.client.on_error = self._handle_error
    
    async def synthesize_text(self, text: str, voice: VoiceType = None) -> bool:
        """Synthesize text to speech."""
        try:
            if self.state == TTSState.ERROR:
                logger.error("TTS handler is in ERROR state")
                return False
            
            if not self.client.is_connected:
                logger.error("Realtime client is not connected")
                return False
            
            if not text.strip():
                logger.warning("Empty text provided for synthesis")
                return False
            
            # Use provided voice or default
            voice_to_use = voice or self.config.voice
            
            # Initialize session if not already done
            if not self.client.session_id:
                session_initialized = await self.client.initialize_session()
                if not session_initialized:
                    logger.error("Failed to initialize session")
                    return False
            
            # Update state
            self.state = TTSState.PROCESSING
            self.synthesis_start_time = time.time()
            
            # Reset response
            self.current_response = TTSResponse()
            self.current_response.text = text
            self.current_response.sample_rate = self.config.sample_rate
            self.current_response.channels = self.config.channels
            self.current_response.bit_depth = self.config.bit_depth
            self.audio_buffer = b""
            
            # Send text message to Realtime API
            success = await self.client.send_text_message(text)
            if not success:
                logger.error("Failed to send text message to Realtime API")
                self.state = TTSState.ERROR
                return False
            
            # Create response with audio modality
            success = await self.client.create_response(["audio"])
            if not success:
                logger.error("Failed to create audio response")
                self.state = TTSState.ERROR
                return False
            
            # Update statistics
            self.stats['texts_processed'] += 1
            self.last_activity_time = time.time()
            
            if self.config.enable_logging:
                logger.info(f"TTS synthesis started: {text[:50]}...")
            
            return True
            
        except Exception as e:
            self.stats['errors'] += 1
            self.state = TTSState.ERROR
            
            if self.config.enable_logging:
                logger.error(f"Error synthesizing text: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"TTS synthesis error: {e}", e)
                else:
                    self.config.on_error(f"TTS synthesis error: {e}", e)
            
            return False
    
    async def synthesize_ssml(self, ssml: str, voice: VoiceType = None) -> bool:
        """Synthesize SSML to speech."""
        try:
            if not self.config.enable_ssml:
                logger.warning("SSML synthesis not enabled in config")
                return False
            
            # For now, treat SSML as regular text
            # In a full implementation, you would parse SSML and apply voice settings
            return await self.synthesize_text(ssml, voice)
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error synthesizing SSML: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"SSML synthesis error: {e}", e)
                else:
                    self.config.on_error(f"SSML synthesis error: {e}", e)
            
            return False
    
    async def stop_synthesis(self) -> bool:
        """Stop the current synthesis."""
        try:
            if not self.is_synthesizing():
                logger.warning("No synthesis in progress")
                return False
            
            # Cancel response via client
            success = await self.client.cancel_response()
            if not success:
                logger.error("Failed to cancel response")
                return False
            
            # Update state
            self.state = TTSState.IDLE
            self._is_speaking = False
            
            if self.config.enable_logging:
                logger.info("TTS synthesis stopped")
            
            return True
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error stopping synthesis: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Synthesis stop error: {e}", e)
                else:
                    self.config.on_error(f"Synthesis stop error: {e}", e)
            
            return False
    
    async def _handle_audio_chunk(self, audio_data: bytes):
        """Handle audio chunk from Realtime API."""
        try:
            if not audio_data:
                return
            
            # Update audio buffer
            self.audio_buffer += audio_data
            self.current_response.audio_data = self.audio_buffer
            self.current_response.audio_length = len(self.audio_buffer)
            
            # Update statistics
            self.stats['audio_chunks_received'] += 1
            self.stats['total_audio_bytes'] += len(audio_data)
            self.last_activity_time = time.time()
            
            # Update state to streaming
            if self.state == TTSState.PROCESSING:
                self.state = TTSState.STREAMING
            
            # Handle speech events
            if not self._is_speaking:
                self._is_speaking = True
                self.stats['speech_events'] += 1
                
                # Call speech start callback
                if self.config.on_speech_start:
                    if asyncio.iscoroutinefunction(self.config.on_speech_start):
                        await self.config.on_speech_start()
                    else:
                        self.config.on_speech_start()
            
            # Call audio chunk callback
            if self.config.on_audio_chunk:
                if asyncio.iscoroutinefunction(self.config.on_audio_chunk):
                    await self.config.on_audio_chunk(audio_data)
                else:
                    self.config.on_audio_chunk(audio_data)
            
            if self.config.enable_logging:
                logger.debug(f"Audio chunk received: {len(audio_data)} bytes")
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error handling audio chunk: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Audio chunk handling error: {e}", e)
                else:
                    self.config.on_error(f"Audio chunk handling error: {e}", e)
    
    async def _handle_synthesis_complete(self, response_data: Dict[str, Any]):
        """Handle synthesis completion from Realtime API."""
        try:
            # Update response
            self.current_response.is_complete = True
            self.current_response.duration_ms = int((time.time() - self.synthesis_start_time) * 1000)
            self.current_response.metadata = response_data
            
            # Update statistics
            self.stats['syntheses_completed'] += 1
            
            # Calculate average synthesis time
            if self.stats['syntheses_completed'] > 0:
                total_time = self.current_response.duration_ms
                self.stats['average_synthesis_time_ms'] = total_time / self.stats['syntheses_completed']
            
            # Handle speech end
            if self._is_speaking:
                self._is_speaking = False
                
                # Call speech end callback
                if self.config.on_speech_end:
                    if asyncio.iscoroutinefunction(self.config.on_speech_end):
                        await self.config.on_speech_end()
                    else:
                        self.config.on_speech_end()
            
            # Update state
            self.state = TTSState.COMPLETED
            
            # Call synthesis complete callback
            if self.config.on_synthesis_complete:
                if asyncio.iscoroutinefunction(self.config.on_synthesis_complete):
                    await self.config.on_synthesis_complete(response_data)
                else:
                    self.config.on_synthesis_complete(response_data)
            
            if self.config.enable_logging:
                logger.info(f"TTS synthesis completed: {len(self.current_response.audio_data)} bytes, {self.current_response.duration_ms}ms")
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error handling synthesis completion: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Synthesis completion error: {e}", e)
                else:
                    self.config.on_error(f"Synthesis completion error: {e}", e)
    
    async def _handle_error(self, error_message: str, error: Exception):
        """Handle errors from the Realtime client."""
        self.stats['errors'] += 1
        self.state = TTSState.ERROR
        self._is_speaking = False
        
        if self.config.enable_logging:
            logger.error(f"TTS error: {error_message}")
        
        if self.config.on_error:
            if asyncio.iscoroutinefunction(self.config.on_error):
                await self.config.on_error(error_message, error)
            else:
                self.config.on_error(error_message, error)
    
    def get_current_response(self) -> TTSResponse:
        """Get the current TTS response."""
        return self.current_response
    
    def get_audio_data(self) -> bytes:
        """Get the complete audio data."""
        return self.current_response.audio_data
    
    def is_synthesizing(self) -> bool:
        """Check if the handler is currently synthesizing."""
        return self.state in [TTSState.PROCESSING, TTSState.STREAMING]
    
    def is_speaking(self) -> bool:
        """Check if the handler is currently speaking."""
        return self._is_speaking
    
    def get_stats(self) -> Dict[str, Any]:
        """Get TTS handler statistics."""
        stats = self.stats.copy()
        stats['state'] = self.state.value
        stats['is_synthesizing'] = self.is_synthesizing()
        stats['is_speaking'] = self.is_speaking()
        stats['current_audio_length'] = len(self.current_response.audio_data)
        stats['current_text_length'] = len(self.current_response.text)
        
        return stats
    
    async def reset(self):
        """Reset the TTS handler to initial state."""
        try:
            # Stop any ongoing synthesis
            if self.is_synthesizing():
                await self.stop_synthesis()
            
            # Clear all data
            self.current_response = TTSResponse()
            self.audio_buffer = b""
            
            # Reset state
            self.state = TTSState.IDLE
            self._is_speaking = False
            self.synthesis_start_time = 0
            self.last_activity_time = 0
            
            if self.config.enable_logging:
                logger.info("TTS handler reset")
            
        except Exception as e:
            if self.config.enable_logging:
                logger.error(f"Error resetting TTS handler: {e}")


class TTSManager:
    """
    Manager for multiple TTS handlers.
    
    This class manages multiple TTS handlers for different voices or sessions.
    """
    
    def __init__(self):
        """Initialize the TTS manager."""
        self.handlers: Dict[str, TTSHandler] = {}
        self.default_config = TTSConfig()
    
    def create_handler(self, handler_id: str, config: TTSConfig = None, 
                      realtime_client: RealtimeClient = None) -> TTSHandler:
        """Create a new TTS handler."""
        if handler_id in self.handlers:
            raise ValueError(f"Handler {handler_id} already exists")
        
        if config is None:
            config = self.default_config
        
        if realtime_client is None:
            raise ValueError("RealtimeClient is required")
        
        handler = TTSHandler(config, realtime_client)
        self.handlers[handler_id] = handler
        
        return handler
    
    def get_handler(self, handler_id: str) -> Optional[TTSHandler]:
        """Get a TTS handler by ID."""
        return self.handlers.get(handler_id)
    
    def remove_handler(self, handler_id: str) -> bool:
        """Remove a TTS handler."""
        if handler_id in self.handlers:
            del self.handlers[handler_id]
            return True
        return False
    
    def get_all_handlers(self) -> Dict[str, TTSHandler]:
        """Get all TTS handlers."""
        return self.handlers.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all handlers."""
        stats = {
            'total_handlers': len(self.handlers),
            'active_handlers': sum(1 for h in self.handlers.values() if h.is_synthesizing()),
            'speaking_handlers': sum(1 for h in self.handlers.values() if h.is_speaking()),
            'handlers': {}
        }
        
        for handler_id, handler in self.handlers.items():
            stats['handlers'][handler_id] = handler.get_stats()
        
        return stats
