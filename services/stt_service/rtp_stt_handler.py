"""
RTP-Adapted Speech-to-Text Handler

This module adapts the existing OpenAI Whisper integration for RTP stream processing.
It handles audio format conversion and streaming audio buffer management.
"""

import asyncio
import base64
import logging
import time
import io
import wave
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from stt_handler import STTConfig, TranscriptResult, STTState
from realtime_client import RealtimeClient, RealtimeConfig, VoiceType
from vad_handler import SpeechSegment
from audio_buffer import AudioBufferManager, BufferConfig, AudioFormatConverter

logger = logging.getLogger(__name__)


@dataclass
class RTPSTTConfig(STTConfig):
    """Configuration for RTP-adapted STT handler."""
    # RTP-specific settings
    rtp_sample_rate: int = 8000  # RTP typically uses 8kHz
    rtp_channels: int = 1
    rtp_bit_depth: int = 16
    
    # Audio format conversion
    target_sample_rate: int = 24000  # Whisper prefers 24kHz
    enable_audio_resampling: bool = True
    enable_audio_enhancement: bool = True
    
    # Buffer management
    max_rtp_buffer_size: int = 50  # Maximum RTP packets to buffer
    audio_chunk_size_ms: int = 20  # 20ms chunks for real-time processing
    
    # Callback settings
    on_transcript: Optional[Callable[[str, bool, Dict[str, Any]], None]] = None  # text, is_final, metadata
    on_speech_segment: Optional[Callable[[SpeechSegment], None]] = None
    on_error: Optional[Callable[[str, Exception], None]] = None


class RTPSTTHandler:
    """
    RTP-adapted Speech-to-Text handler using OpenAI Realtime API.
    
    This handler processes RTP audio streams and converts them for Whisper processing.
    """
    
    def __init__(self, config: RTPSTTConfig, realtime_client: RealtimeClient):
        """Initialize the RTP STT handler."""
        self.config = config
        self.client = realtime_client
        self.state = STTState.IDLE
        
        # Audio processing
        self.rtp_audio_buffer: List[bytes] = []
        self.processed_audio_buffer: List[bytes] = []
        self.current_transcript = ""
        self.partial_transcript = ""
        
        # RTP stream tracking
        self.active_streams: Dict[int, Dict[str, Any]] = {}  # SSRC -> stream info
        
        # Initialize audio buffer manager
        buffer_config = BufferConfig(
            max_duration_seconds=3.0,
            min_duration_seconds=0.5,
            chunk_duration_seconds=1.0,
            sample_rate=self.config.rtp_sample_rate,
            channels=self.config.channels,
            bit_depth=self.config.bit_depth,
            enable_auto_flush=True,
            enable_overflow_protection=True
        )
        self.buffer_manager = AudioBufferManager(buffer_config)
        self.current_stream_id: Optional[int] = None
        
        # Statistics
        self.stats = {
            'rtp_packets_processed': 0,
            'audio_chunks_processed': 0,
            'transcripts_received': 0,
            'partial_transcripts': 0,
            'final_transcripts': 0,
            'speech_sessions': 0,
            'errors': 0,
            'total_audio_duration_ms': 0,
            'processing_time_ms': 0,
            'resampling_operations': 0
        }
        
        # State tracking
        self.is_speaking = False
        self.speech_start_time = 0.0
        self.last_audio_time = 0.0
        
        logger.info("RTP STT Handler initialized")
    
    async def start(self) -> bool:
        """Start the STT handler."""
        try:
            if self.state != STTState.IDLE:
                logger.warning("STT handler is not in IDLE state")
                return False
            
            # Start the Realtime API client
            success = await self.client.connect()
            if not success:
                logger.error("Failed to connect to Realtime API")
                return False
            
            self.state = STTState.LISTENING
            logger.info("RTP STT Handler started")
            return True
            
        except Exception as e:
            logger.error(f"Error starting RTP STT handler: {e}")
            self.state = STTState.ERROR
            return False
    
    async def stop(self) -> bool:
        """Stop the STT handler."""
        try:
            if self.state == STTState.IDLE:
                return True
            
            # Stop the Realtime API client
            await self.client.disconnect()
            
            self.state = STTState.IDLE
            logger.info("RTP STT Handler stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping RTP STT handler: {e}")
            return False
    
    async def process_rtp_audio(self, audio_data: bytes, stream_info: Dict[str, Any]) -> bool:
        """Process RTP audio data for STT."""
        try:
            if self.state != STTState.LISTENING:
                logger.warning("STT handler is not in LISTENING state")
                return False
            
            # Validate audio data
            if not audio_data or len(audio_data) == 0:
                logger.warning("Empty RTP audio data received")
                return False
            
            # Track stream
            ssrc = stream_info.get('ssrc')
            if ssrc:
                self.active_streams[ssrc] = stream_info
                self.current_stream_id = ssrc
                
                # Get or create buffer for this stream
                buffer_id = f"stream_{ssrc}"
                buffer = self.buffer_manager.get_buffer(buffer_id)
                if not buffer:
                    buffer = self.buffer_manager.create_buffer(buffer_id)
                    # Set up buffer callbacks
                    buffer.on_chunk_ready = lambda chunk: asyncio.create_task(self._process_audio_chunk(chunk, stream_info))
                    buffer.on_overflow = lambda: logger.warning(f"Buffer overflow for stream {ssrc}")
                    buffer.on_silence_detected = lambda: logger.debug(f"Silence detected for stream {ssrc}")
            
            # Add audio to buffer
            if buffer:
                success = buffer.add_audio(audio_data, time.time())
                if not success:
                    logger.warning(f"Failed to add audio to buffer for stream {ssrc}")
                    return False
            
            # Update statistics
            self.stats['rtp_packets_processed'] += 1
            self.last_audio_time = time.time()
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing RTP audio: {e}")
            self.stats['errors'] += 1
            return False
    
    async def _process_audio_chunk(self, chunk, stream_info: Dict[str, Any]):
        """Process an audio chunk from the buffer manager."""
        try:
            # Convert audio format for Whisper
            converted_audio, sample_rate = AudioFormatConverter.convert_to_whisper_format(
                chunk.data,
                source_sample_rate=chunk.sample_rate,
                target_sample_rate=self.config.target_sample_rate,
                source_channels=chunk.channels,
                target_channels=1,
                source_bit_depth=chunk.bit_depth,
                target_bit_depth=16
            )
            
            # Send to Realtime API
            ssrc = stream_info.get('ssrc')
            if ssrc in self.active_streams:
                client_stream = self.active_streams[ssrc].get('client_stream')
                if client_stream:
                    success = await self.client.send_audio_chunk(converted_audio, client_stream)
                    if not success:
                        logger.warning(f"Failed to send audio chunk to Realtime API for SSRC {ssrc}")
                else:
                    logger.warning(f"No client stream found for SSRC {ssrc}")
            else:
                logger.warning(f"No active stream found for SSRC {ssrc}")
                
        except Exception as e:
            logger.error(f"Error processing audio chunk: {e}")
            self.stats['errors'] += 1
    
    async def process_speech_segment(self, segment: SpeechSegment, stream_info: Dict[str, Any]) -> bool:
        """Process a complete speech segment for STT."""
        try:
            if self.state != STTState.LISTENING:
                logger.warning("STT handler is not in LISTENING state")
                return False
            
            logger.info(f"Processing speech segment: {segment.duration:.2f}s, {len(segment.audio_data)} bytes")
            
            # Convert audio format if needed
            processed_audio = await self._convert_audio_format(segment.audio_data, stream_info)
            if not processed_audio:
                logger.error("Failed to convert audio format")
                return False
            
            # Process the complete segment
            success = await self._process_audio_segment(processed_audio, segment, stream_info)
            
            if success and self.config.on_speech_segment:
                try:
                    if asyncio.iscoroutinefunction(self.config.on_speech_segment):
                        await self.config.on_speech_segment(segment)
                    else:
                        self.config.on_speech_segment(segment)
                except Exception as e:
                    logger.error(f"Error in speech segment callback: {e}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error processing speech segment: {e}")
            self.stats['errors'] += 1
            return False
    
    async def _process_audio_buffer(self):
        """Process the accumulated RTP audio buffer."""
        try:
            if not self.rtp_audio_buffer:
                return
            
            # Calculate target chunk size
            chunk_size_bytes = (self.config.rtp_sample_rate * self.config.audio_chunk_size_ms * 2) // 1000  # 2 bytes per sample
            
            # Process chunks
            while len(self.rtp_audio_buffer) >= chunk_size_bytes:
                # Extract chunk
                chunk_data = b''.join(self.rtp_audio_buffer[:chunk_size_bytes])
                self.rtp_audio_buffer = self.rtp_audio_buffer[chunk_size_bytes:]
                
                # Convert audio format
                processed_chunk = await self._convert_audio_format(chunk_data, self.active_streams.get(self.current_stream_id, {}))
                if processed_chunk:
                    # Send to Realtime API
                    success = await self.client.send_audio_chunk(processed_chunk)
                    if success:
                        self.stats['audio_chunks_processed'] += 1
                        self.stats['total_audio_duration_ms'] += self.config.audio_chunk_size_ms
                        
                        # Detect speech start
                        if not self.is_speaking:
                            self.is_speaking = True
                            self.speech_start_time = time.time()
                            self.stats['speech_sessions'] += 1
                            logger.debug("Speech started from RTP stream")
                    else:
                        logger.error("Failed to send audio chunk to Realtime API")
            
        except Exception as e:
            logger.error(f"Error processing audio buffer: {e}")
            self.stats['errors'] += 1
    
    async def _process_audio_segment(self, audio_data: bytes, segment: SpeechSegment, stream_info: Dict[str, Any]) -> bool:
        """Process a complete audio segment."""
        try:
            # Send audio data to Realtime API
            success = await self.client.send_audio_chunk(audio_data)
            if not success:
                logger.error("Failed to send audio segment to Realtime API")
                return False
            
            # Update statistics
            self.stats['audio_chunks_processed'] += 1
            self.stats['total_audio_duration_ms'] += int(segment.duration * 1000)
            
            # Detect speech start
            if not self.is_speaking:
                self.is_speaking = True
                self.speech_start_time = time.time()
                self.stats['speech_sessions'] += 1
                logger.debug("Speech started from segment")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing audio segment: {e}")
            self.stats['errors'] += 1
            return False
    
    async def _convert_audio_format(self, audio_data: bytes, stream_info: Dict[str, Any]) -> Optional[bytes]:
        """Convert RTP audio format to Whisper-compatible format."""
        try:
            # For now, assume audio is already in the correct format
            # In a full implementation, you would:
            # 1. Resample from 8kHz to 24kHz if needed
            # 2. Convert from 16-bit to the required format
            # 3. Apply any necessary audio enhancements
            
            if self.config.enable_audio_resampling and self.config.rtp_sample_rate != self.config.target_sample_rate:
                # TODO: Implement audio resampling
                logger.debug("Audio resampling not implemented yet")
                self.stats['resampling_operations'] += 1
            
            return audio_data
            
        except Exception as e:
            logger.error(f"Error converting audio format: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        return self.stats.copy()
    
    def get_state(self) -> STTState:
        """Get current handler state."""
        return self.state
    
    def reset_stats(self):
        """Reset processing statistics."""
        self.stats = {
            'rtp_packets_processed': 0,
            'audio_chunks_processed': 0,
            'transcripts_received': 0,
            'partial_transcripts': 0,
            'final_transcripts': 0,
            'speech_sessions': 0,
            'errors': 0,
            'total_audio_duration_ms': 0,
            'processing_time_ms': 0,
            'resampling_operations': 0
        }
