"""
OpenAI Realtime API Speech-to-Text (STT) Handler

This module provides specialized functionality for streaming speech-to-text
operations using the OpenAI Realtime API.
"""

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from realtime_client import RealtimeClient, RealtimeConfig, VoiceType

logger = logging.getLogger(__name__)


class STTState(Enum):
    """STT processing states."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class STTConfig:
    """Configuration for STT handler."""
    # Audio format settings
    sample_rate: int = 24000
    channels: int = 1
    bit_depth: int = 16
    chunk_duration_ms: int = 20  # 20ms chunks for real-time processing
    
    # VAD settings
    vad_threshold: float = 0.5
    silence_duration_ms: int = 200
    prefix_padding_ms: int = 300
    
    # Processing settings
    enable_partial_transcripts: bool = True
    enable_final_transcripts: bool = True
    max_audio_buffer_size: int = 100  # Maximum number of chunks to buffer
    
    # Callback settings
    on_transcript: Optional[Callable[[str, bool], None]] = None  # text, is_final
    on_speech_start: Optional[Callable[[], None]] = None
    on_speech_end: Optional[Callable[[], None]] = None
    on_error: Optional[Callable[[str, Exception], None]] = None
    
    # Logging
    enable_logging: bool = True
    log_level: str = "INFO"


@dataclass
class TranscriptResult:
    """Transcript result from STT processing."""
    text: str
    is_final: bool
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 0
    language: str = "en"


class STTHandler:
    """
    Speech-to-Text handler using OpenAI Realtime API.
    
    This handler manages the streaming STT process, including audio buffering,
    VAD detection, and transcript processing.
    """
    
    def __init__(self, config: STTConfig, realtime_client: RealtimeClient):
        """Initialize the STT handler."""
        self.config = config
        self.client = realtime_client
        self.state = STTState.IDLE
        
        # Audio processing
        self.audio_buffer: List[bytes] = []
        self.current_transcript = ""
        self.partial_transcript = ""
        
        # Statistics
        self.stats = {
            'audio_chunks_processed': 0,
            'transcripts_received': 0,
            'partial_transcripts': 0,
            'final_transcripts': 0,
            'speech_sessions': 0,
            'errors': 0,
            'total_audio_duration_ms': 0,
            'processing_time_ms': 0
        }
        
        # Speech detection
        self.is_speaking = False
        self.speech_start_time = 0
        self.last_audio_time = 0
        
        # Setup client callbacks
        self._setup_client_callbacks()
    
    def _setup_client_callbacks(self):
        """Setup callbacks for the Realtime client."""
        self.client.on_transcript = self._handle_transcript
        self.client.on_error = self._handle_error
    
    async def start_listening(self) -> bool:
        """Start the STT listening process."""
        try:
            if self.state != STTState.IDLE:
                logger.warning("STT handler is not in IDLE state")
                return False
            
            if not self.client.is_connected:
                logger.error("Realtime client is not connected")
                return False
            
            # Initialize session if not already done
            if not self.client.session_id:
                session_initialized = await self.client.initialize_session()
                if not session_initialized:
                    logger.error("Failed to initialize session")
                    return False
            
            self.state = STTState.LISTENING
            self.audio_buffer.clear()
            self.current_transcript = ""
            self.partial_transcript = ""
            self.is_speaking = False
            
            if self.config.enable_logging:
                logger.info("STT listening started")
            
            return True
            
        except Exception as e:
            self.state = STTState.ERROR
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Failed to start STT listening: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Failed to start listening: {e}", e)
                else:
                    self.config.on_error(f"Failed to start listening: {e}", e)
            
            return False
    
    async def stop_listening(self) -> bool:
        """Stop the STT listening process."""
        try:
            if self.state != STTState.LISTENING:
                logger.warning("STT handler is not in LISTENING state")
                return False
            
            # Commit any remaining audio buffer
            if self.audio_buffer:
                await self._commit_audio_buffer()
            
            self.state = STTState.IDLE
            
            if self.config.enable_logging:
                logger.info("STT listening stopped")
            
            return True
            
        except Exception as e:
            self.state = STTState.ERROR
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Failed to stop STT listening: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Failed to stop listening: {e}", e)
                else:
                    self.config.on_error(f"Failed to stop listening: {e}", e)
            
            return False
    
    async def process_audio_chunk(self, audio_data: bytes) -> bool:
        """Process an audio chunk for STT."""
        try:
            if self.state != STTState.LISTENING:
                logger.warning("STT handler is not in LISTENING state")
                return False
            
            # Validate audio data
            if not audio_data or len(audio_data) == 0:
                logger.warning("Empty audio data received")
                return False
            
            # Add to buffer
            self.audio_buffer.append(audio_data)
            self.last_audio_time = time.time()
            
            # Check buffer size
            if len(self.audio_buffer) > self.config.max_audio_buffer_size:
                # Remove oldest chunks
                excess = len(self.audio_buffer) - self.config.max_audio_buffer_size
                self.audio_buffer = self.audio_buffer[excess:]
            
            # Send audio chunk to Realtime API
            success = await self.client.send_audio_chunk(audio_data)
            if not success:
                logger.error("Failed to send audio chunk to Realtime API")
                return False
            
            # Update statistics
            self.stats['audio_chunks_processed'] += 1
            self.stats['total_audio_duration_ms'] += self.config.chunk_duration_ms
            
            # Detect speech start
            if not self.is_speaking:
                self.is_speaking = True
                self.speech_start_time = time.time()
                self.stats['speech_sessions'] += 1
                
                if self.config.on_speech_start:
                    if asyncio.iscoroutinefunction(self.config.on_speech_start):
                        await self.config.on_speech_start()
                    else:
                        self.config.on_speech_start()
                
                if self.config.enable_logging:
                    logger.debug("Speech started")
            
            return True
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error processing audio chunk: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Audio processing error: {e}", e)
                else:
                    self.config.on_error(f"Audio processing error: {e}", e)
            
            return False
    
    async def commit_audio(self) -> bool:
        """Commit the current audio buffer for processing."""
        try:
            if not self.audio_buffer:
                logger.warning("No audio data to commit")
                return False
            
            # Send commit message to Realtime API
            success = await self.client.commit_audio_buffer()
            if not success:
                logger.error("Failed to commit audio buffer")
                return False
            
            # Clear buffer
            self.audio_buffer.clear()
            
            if self.config.enable_logging:
                logger.debug("Audio buffer committed")
            
            return True
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error committing audio: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Audio commit error: {e}", e)
                else:
                    self.config.on_error(f"Audio commit error: {e}", e)
            
            return False
    
    async def _commit_audio_buffer(self):
        """Internal method to commit audio buffer."""
        await self.commit_audio()
    
    async def _handle_transcript(self, text: str):
        """Handle transcript from Realtime API."""
        try:
            if not text:
                return
            
            # Update current transcript
            self.current_transcript = text
            self.partial_transcript = text
            
            # Update statistics
            self.stats['transcripts_received'] += 1
            self.stats['partial_transcripts'] += 1
            
            # Create transcript result
            result = TranscriptResult(
                text=text,
                is_final=False,  # Realtime API provides partial transcripts
                timestamp=time.time(),
                duration_ms=int((time.time() - self.speech_start_time) * 1000) if self.is_speaking else 0
            )
            
            # Call transcript callback
            if self.config.on_transcript:
                if asyncio.iscoroutinefunction(self.config.on_transcript):
                    await self.config.on_transcript(text, False)
                else:
                    self.config.on_transcript(text, False)
            
            if self.config.enable_logging:
                logger.debug(f"Partial transcript: {text}")
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error handling transcript: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Transcript handling error: {e}", e)
                else:
                    self.config.on_error(f"Transcript handling error: {e}", e)
    
    async def _handle_error(self, error_message: str, error: Exception):
        """Handle errors from the Realtime client."""
        self.stats['errors'] += 1
        self.state = STTState.ERROR
        
        if self.config.enable_logging:
            logger.error(f"STT error: {error_message}")
        
        if self.config.on_error:
            if asyncio.iscoroutinefunction(self.config.on_error):
                await self.config.on_error(error_message, error)
            else:
                self.config.on_error(error_message, error)
    
    def get_current_transcript(self) -> str:
        """Get the current transcript text."""
        return self.current_transcript
    
    def get_partial_transcript(self) -> str:
        """Get the current partial transcript text."""
        return self.partial_transcript
    
    def clear_transcript(self):
        """Clear the current transcript."""
        self.current_transcript = ""
        self.partial_transcript = ""
    
    def is_listening(self) -> bool:
        """Check if the handler is currently listening."""
        return self.state == STTState.LISTENING
    
    def is_speaking_detected(self) -> bool:
        """Check if speech is currently being detected."""
        return self.is_speaking
    
    def get_stats(self) -> Dict[str, Any]:
        """Get STT handler statistics."""
        stats = self.stats.copy()
        stats['state'] = self.state.value
        stats['is_listening'] = self.is_listening()
        stats['is_speaking'] = self.is_speaking_detected()
        stats['current_transcript'] = self.current_transcript
        stats['partial_transcript'] = self.partial_transcript
        stats['audio_buffer_size'] = len(self.audio_buffer)
        
        return stats
    
    async def reset(self):
        """Reset the STT handler to initial state."""
        try:
            # Stop listening if active
            if self.state == STTState.LISTENING:
                await self.stop_listening()
            
            # Clear all data
            self.audio_buffer.clear()
            self.current_transcript = ""
            self.partial_transcript = ""
            self.is_speaking = False
            self.speech_start_time = 0
            self.last_audio_time = 0
            
            # Reset state
            self.state = STTState.IDLE
            
            if self.config.enable_logging:
                logger.info("STT handler reset")
            
        except Exception as e:
            if self.config.enable_logging:
                logger.error(f"Error resetting STT handler: {e}")


class STTManager:
    """
    Manager for multiple STT handlers.
    
    This class manages multiple STT handlers for different sessions or channels.
    """
    
    def __init__(self):
        """Initialize the STT manager."""
        self.handlers: Dict[str, STTHandler] = {}
        self.default_config = STTConfig()
    
    def create_handler(self, handler_id: str, config: STTConfig = None, 
                      realtime_client: RealtimeClient = None) -> STTHandler:
        """Create a new STT handler."""
        if handler_id in self.handlers:
            raise ValueError(f"Handler {handler_id} already exists")
        
        if config is None:
            config = self.default_config
        
        if realtime_client is None:
            raise ValueError("RealtimeClient is required")
        
        handler = STTHandler(config, realtime_client)
        self.handlers[handler_id] = handler
        
        return handler
    
    def get_handler(self, handler_id: str) -> Optional[STTHandler]:
        """Get an STT handler by ID."""
        return self.handlers.get(handler_id)
    
    def remove_handler(self, handler_id: str) -> bool:
        """Remove an STT handler."""
        if handler_id in self.handlers:
            del self.handlers[handler_id]
            return True
        return False
    
    def get_all_handlers(self) -> Dict[str, STTHandler]:
        """Get all STT handlers."""
        return self.handlers.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all handlers."""
        stats = {
            'total_handlers': len(self.handlers),
            'active_handlers': sum(1 for h in self.handlers.values() if h.is_listening()),
            'handlers': {}
        }
        
        for handler_id, handler in self.handlers.items():
            stats['handlers'][handler_id] = handler.get_stats()
        
        return stats
