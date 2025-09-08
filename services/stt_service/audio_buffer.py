"""
Audio Buffer Management System

This module provides audio buffer management with configurable chunk sizes
for optimal transcription. It implements circular buffers for continuous
audio stream handling with VAD-triggered flushing.
"""

import asyncio
import logging
import time
import audioop
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, List, Tuple, Any, Dict
from threading import Lock

logger = logging.getLogger(__name__)


class BufferState(Enum):
    """Audio buffer state enumeration."""
    EMPTY = "empty"
    FILLING = "filling"
    READY = "ready"
    OVERFLOW = "overflow"
    FLUSHING = "flushing"


@dataclass
class AudioChunk:
    """Audio chunk with metadata."""
    data: bytes
    timestamp: float
    duration: float
    sample_rate: int
    channels: int
    bit_depth: int
    chunk_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BufferConfig:
    """Configuration for audio buffer."""
    max_duration_seconds: float = 3.0  # Maximum buffer duration
    min_duration_seconds: float = 0.5  # Minimum duration before processing
    chunk_duration_seconds: float = 1.0  # Target chunk duration
    sample_rate: int = 8000
    channels: int = 1
    bit_depth: int = 16
    overflow_threshold: float = 0.9  # 90% full triggers overflow handling
    silence_threshold_seconds: float = 2.0  # Silence duration before auto-flush
    enable_auto_flush: bool = True
    enable_overflow_protection: bool = True
    max_memory_mb: int = 50  # Maximum memory usage in MB


class CircularAudioBuffer:
    """Circular buffer for continuous audio stream handling."""
    
    def __init__(self, config: BufferConfig):
        """Initialize the circular audio buffer."""
        self.config = config
        self.buffer = deque()
        self.total_duration = 0.0
        self.state = BufferState.EMPTY
        self.lock = Lock()
        
        # Calculate buffer size in samples
        self.sample_size = self.config.bit_depth // 8
        self.samples_per_second = self.config.sample_rate * self.config.channels
        self.bytes_per_second = self.samples_per_second * self.sample_size
        
        # Calculate buffer limits
        self.max_bytes = int(self.config.max_duration_seconds * self.bytes_per_second)
        self.min_bytes = int(self.config.min_duration_seconds * self.bytes_per_second)
        self.chunk_bytes = int(self.config.chunk_duration_seconds * self.bytes_per_second)
        
        # Overflow protection
        self.max_memory_bytes = self.config.max_memory_mb * 1024 * 1024
        self.current_memory_bytes = 0
        
        # Silence detection
        self.last_audio_time = 0.0
        self.silence_start_time = 0.0
        self.in_silence = False
        
        # Callbacks
        self.on_chunk_ready: Optional[Callable[[AudioChunk], None]] = None
        self.on_overflow: Optional[Callable[[], None]] = None
        self.on_silence_detected: Optional[Callable[[], None]] = None
        
        logger.info(f"CircularAudioBuffer initialized: max_duration={self.config.max_duration_seconds}s, "
                   f"chunk_duration={self.config.chunk_duration_seconds}s, sample_rate={self.config.sample_rate}")
    
    def add_audio(self, audio_data: bytes, timestamp: Optional[float] = None) -> bool:
        """Add audio data to the buffer."""
        if not audio_data:
            return False
        
        if timestamp is None:
            timestamp = time.time()
        
        with self.lock:
            try:
                # Add audio data to buffer
                self.buffer.append((audio_data, timestamp))
                self.total_duration += len(audio_data) / self.bytes_per_second
                self.current_memory_bytes += len(audio_data)
                self.last_audio_time = timestamp
                
                # Update state
                if self.state == BufferState.EMPTY:
                    self.state = BufferState.FILLING
                
                # Check for overflow
                if self._check_overflow():
                    self._handle_overflow()
                    return False
                
                # Check if buffer is ready for processing
                if self._is_ready_for_processing():
                    self._process_chunk()
                
                # Check for silence
                if self.config.enable_auto_flush:
                    self._check_silence(timestamp)
                
                return True
                
            except Exception as e:
                logger.error(f"Error adding audio to buffer: {e}")
                return False
    
    def flush(self, force: bool = False) -> List[AudioChunk]:
        """Flush the buffer and return audio chunks."""
        with self.lock:
            if not self.buffer and not force:
                return []
            
            chunks = []
            if self.buffer:
                # Create chunks from buffer data
                chunks = self._create_chunks()
                
                # Clear buffer
                self.buffer.clear()
                self.total_duration = 0.0
                self.current_memory_bytes = 0
                self.state = BufferState.EMPTY
                
                logger.info(f"Flushed buffer: {len(chunks)} chunks, {self.total_duration:.2f}s total")
            
            return chunks
    
    def clear(self):
        """Clear the buffer without processing."""
        with self.lock:
            self.buffer.clear()
            self.total_duration = 0.0
            self.current_memory_bytes = 0
            self.state = BufferState.EMPTY
            self.in_silence = False
            logger.info("Buffer cleared")
    
    def get_status(self) -> Dict[str, Any]:
        """Get buffer status information."""
        with self.lock:
            return {
                'state': self.state.value,
                'total_duration': self.total_duration,
                'buffer_size': len(self.buffer),
                'memory_usage_bytes': self.current_memory_bytes,
                'memory_usage_mb': self.current_memory_bytes / (1024 * 1024),
                'is_ready': self._is_ready_for_processing(),
                'in_silence': self.in_silence,
                'last_audio_time': self.last_audio_time
            }
    
    def _check_overflow(self) -> bool:
        """Check if buffer is in overflow state."""
        if not self.config.enable_overflow_protection:
            return False
        
        # Check duration overflow
        if self.total_duration > self.config.max_duration_seconds:
            return True
        
        # Check memory overflow
        if self.current_memory_bytes > self.max_memory_bytes:
            return True
        
        # Check buffer size overflow (90% threshold)
        if len(self.buffer) > 0:
            current_bytes = sum(len(data) for data, _ in self.buffer)
            if current_bytes > self.max_bytes * self.config.overflow_threshold:
                return True
        
        return False
    
    def _handle_overflow(self):
        """Handle buffer overflow."""
        logger.warning("Buffer overflow detected, forcing flush")
        self.state = BufferState.OVERFLOW
        
        # Force flush to prevent memory issues
        chunks = self.flush(force=True)
        
        # Notify overflow callback
        if self.on_overflow:
            try:
                self.on_overflow()
            except Exception as e:
                logger.error(f"Error in overflow callback: {e}")
    
    def _is_ready_for_processing(self) -> bool:
        """Check if buffer is ready for processing."""
        if self.state in [BufferState.OVERFLOW, BufferState.FLUSHING]:
            return False
        
        # Check minimum duration
        if self.total_duration < self.config.min_duration_seconds:
            return False
        
        # Check chunk duration
        if self.total_duration >= self.config.chunk_duration_seconds:
            return True
        
        return False
    
    def _process_chunk(self):
        """Process a chunk from the buffer."""
        if not self.buffer:
            return
        
        self.state = BufferState.FLUSHING
        
        try:
            # Create chunk
            chunks = self._create_chunks()
            
            # Process each chunk
            for chunk in chunks:
                if self.on_chunk_ready:
                    try:
                        self.on_chunk_ready(chunk)
                    except Exception as e:
                        logger.error(f"Error in chunk ready callback: {e}")
            
            # Clear processed data
            self.buffer.clear()
            self.total_duration = 0.0
            self.current_memory_bytes = 0
            self.state = BufferState.EMPTY
            
        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
            self.state = BufferState.EMPTY
    
    def _create_chunks(self) -> List[AudioChunk]:
        """Create audio chunks from buffer data."""
        if not self.buffer:
            return []
        
        chunks = []
        current_chunk_data = bytearray()
        current_chunk_start_time = None
        current_chunk_duration = 0.0
        
        for audio_data, timestamp in self.buffer:
            if current_chunk_start_time is None:
                current_chunk_start_time = timestamp
            
            current_chunk_data.extend(audio_data)
            current_chunk_duration += len(audio_data) / self.bytes_per_second
            
            # Create chunk if we have enough data or reach end
            if (current_chunk_duration >= self.config.chunk_duration_seconds or 
                len(current_chunk_data) >= self.chunk_bytes):
                
                chunk = AudioChunk(
                    data=bytes(current_chunk_data),
                    timestamp=current_chunk_start_time,
                    duration=current_chunk_duration,
                    sample_rate=self.config.sample_rate,
                    channels=self.config.channels,
                    bit_depth=self.config.bit_depth,
                    chunk_id=f"chunk_{int(timestamp * 1000)}",
                    metadata={
                        'buffer_size': len(current_chunk_data),
                        'samples': len(current_chunk_data) // self.sample_size
                    }
                )
                chunks.append(chunk)
                
                # Reset for next chunk
                current_chunk_data = bytearray()
                current_chunk_start_time = None
                current_chunk_duration = 0.0
        
        return chunks
    
    def _check_silence(self, current_time: float):
        """Check for silence and trigger auto-flush if needed."""
        if not self.config.enable_auto_flush:
            return
        
        silence_duration = current_time - self.last_audio_time
        
        if silence_duration > self.config.silence_threshold_seconds:
            if not self.in_silence:
                self.in_silence = True
                self.silence_start_time = current_time
                logger.debug(f"Silence detected: {silence_duration:.2f}s")
                
                # Trigger silence callback
                if self.on_silence_detected:
                    try:
                        self.on_silence_detected()
                    except Exception as e:
                        logger.error(f"Error in silence callback: {e}")
                
                # Auto-flush if we have data
                if self.buffer and self.total_duration > self.config.min_duration_seconds:
                    logger.info("Auto-flushing buffer due to silence")
                    self._process_chunk()
        else:
            if self.in_silence:
                self.in_silence = False
                logger.debug("Silence ended")


class AudioFormatConverter:
    """Audio format conversion utilities for Whisper compatibility."""
    
    @staticmethod
    def convert_to_whisper_format(
        audio_data: bytes,
        source_sample_rate: int,
        target_sample_rate: int = 24000,
        source_channels: int = 1,
        target_channels: int = 1,
        source_bit_depth: int = 16,
        target_bit_depth: int = 16
    ) -> Tuple[bytes, int]:
        """Convert audio to Whisper-compatible format."""
        try:
            # Convert bit depth if needed
            if source_bit_depth != target_bit_depth:
                if source_bit_depth == 8 and target_bit_depth == 16:
                    # Convert 8-bit to 16-bit
                    audio_data = audioop.bias(audioop.mul(audio_data, 1, 2), 1, 128)
                elif source_bit_depth == 16 and target_bit_depth == 8:
                    # Convert 16-bit to 8-bit
                    audio_data = audioop.bias(audioop.mul(audio_data, 1, 0.5), 1, 128)
            
            # Convert sample rate if needed
            if source_sample_rate != target_sample_rate:
                audio_data, _ = audioop.ratecv(
                    audio_data,
                    source_bit_depth // 8,
                    source_channels,
                    source_sample_rate,
                    target_sample_rate,
                    None
                )
            
            # Convert channels if needed
            if source_channels != target_channels:
                if source_channels == 2 and target_channels == 1:
                    # Convert stereo to mono
                    audio_data = audioop.tomono(audio_data, source_bit_depth // 8, 1, 1)
                elif source_channels == 1 and target_channels == 2:
                    # Convert mono to stereo
                    audio_data = audioop.tostereo(audio_data, source_bit_depth // 8, 1, 1)
            
            return audio_data, target_sample_rate
            
        except Exception as e:
            logger.error(f"Error converting audio format: {e}")
            return audio_data, source_sample_rate
    
    @staticmethod
    def validate_audio_format(
        audio_data: bytes,
        sample_rate: int,
        channels: int,
        bit_depth: int
    ) -> bool:
        """Validate audio format parameters."""
        try:
            expected_bytes = len(audio_data)
            actual_bytes = (sample_rate * channels * bit_depth // 8) * (len(audio_data) // (channels * bit_depth // 8))
            
            # Allow some tolerance for partial frames
            tolerance = channels * bit_depth // 8
            return abs(expected_bytes - actual_bytes) <= tolerance
            
        except Exception as e:
            logger.error(f"Error validating audio format: {e}")
            return False


class AudioBufferManager:
    """High-level audio buffer manager with multiple buffer support."""
    
    def __init__(self, default_config: Optional[BufferConfig] = None):
        """Initialize the audio buffer manager."""
        self.default_config = default_config or BufferConfig()
        self.buffers: Dict[str, CircularAudioBuffer] = {}
        self.lock = Lock()
        
        logger.info("AudioBufferManager initialized")
    
    def create_buffer(self, buffer_id: str, config: Optional[BufferConfig] = None) -> CircularAudioBuffer:
        """Create a new audio buffer."""
        with self.lock:
            if buffer_id in self.buffers:
                logger.warning(f"Buffer {buffer_id} already exists")
                return self.buffers[buffer_id]
            
            buffer_config = config or self.default_config
            buffer = CircularAudioBuffer(buffer_config)
            self.buffers[buffer_id] = buffer
            
            logger.info(f"Created audio buffer: {buffer_id}")
            return buffer
    
    def get_buffer(self, buffer_id: str) -> Optional[CircularAudioBuffer]:
        """Get an existing audio buffer."""
        with self.lock:
            return self.buffers.get(buffer_id)
    
    def remove_buffer(self, buffer_id: str) -> bool:
        """Remove an audio buffer."""
        with self.lock:
            if buffer_id in self.buffers:
                buffer = self.buffers.pop(buffer_id)
                buffer.clear()
                logger.info(f"Removed audio buffer: {buffer_id}")
                return True
            return False
    
    def get_all_buffers(self) -> Dict[str, CircularAudioBuffer]:
        """Get all audio buffers."""
        with self.lock:
            return self.buffers.copy()
    
    def get_manager_status(self) -> Dict[str, Any]:
        """Get manager status information."""
        with self.lock:
            buffer_statuses = {}
            total_memory = 0
            
            for buffer_id, buffer in self.buffers.items():
                status = buffer.get_status()
                buffer_statuses[buffer_id] = status
                total_memory += status['memory_usage_bytes']
            
            return {
                'total_buffers': len(self.buffers),
                'total_memory_bytes': total_memory,
                'total_memory_mb': total_memory / (1024 * 1024),
                'buffers': buffer_statuses
            }
