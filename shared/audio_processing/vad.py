"""
Voice Activity Detection (VAD) module for real-time audio processing.

This module provides VAD functionality using WebRTC's VAD algorithm
for detecting speech activity in audio streams.
"""

import logging
import webrtcvad
import numpy as np
from typing import Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VADMode(Enum):
    """VAD sensitivity modes."""
    QUALITY = 0  # Most conservative
    LOW_BITRATE = 1
    AGGRESSIVE = 2  # Most aggressive
    VERY_AGGRESSIVE = 3


@dataclass
class VADConfig:
    """Configuration for Voice Activity Detection."""
    mode: VADMode = VADMode.AGGRESSIVE
    sample_rate: int = 16000  # WebRTC VAD requires 8kHz, 16kHz, 32kHz, or 48kHz
    frame_duration_ms: int = 30  # Frame duration in milliseconds
    min_speech_frames: int = 3  # Minimum consecutive frames for speech
    min_silence_frames: int = 3  # Minimum consecutive frames for silence
    enable_logging: bool = True


class VoiceActivityDetector:
    """
    Voice Activity Detector using WebRTC VAD.
    
    This class provides real-time voice activity detection for audio streams,
    with configurable sensitivity and frame processing.
    """
    
    def __init__(self, config: Optional[VADConfig] = None):
        """
        Initialize the Voice Activity Detector.
        
        Args:
            config: VAD configuration. If None, uses default config.
        """
        self.config = config or VADConfig()
        self.vad = webrtcvad.Vad(self.config.mode.value)
        
        # Calculate frame size based on sample rate and duration
        self.frame_size = int(self.config.sample_rate * self.config.frame_duration_ms / 1000)
        
        # State tracking
        self.speech_frames = 0
        self.silence_frames = 0
        self.is_speaking = False
        self.frame_count = 0
        
        if self.config.enable_logging:
            logger.info(f"VAD initialized: mode={self.config.mode.name}, "
                       f"sample_rate={self.config.sample_rate}Hz, "
                       f"frame_duration={self.config.frame_duration_ms}ms")
    
    def process_frame(self, audio_frame: bytes) -> bool:
        """
        Process a single audio frame for voice activity detection.
        
        Args:
            audio_frame: Raw audio frame bytes (16-bit PCM, mono)
            
        Returns:
            bool: True if speech is detected, False otherwise
            
        Raises:
            ValueError: If audio frame size is incorrect
        """
        if len(audio_frame) != self.frame_size * 2:  # 2 bytes per sample (16-bit)
            raise ValueError(f"Invalid frame size: expected {self.frame_size * 2} bytes, "
                           f"got {len(audio_frame)} bytes")
        
        try:
            # WebRTC VAD expects 16-bit PCM audio
            is_speech = self.vad.is_speech(audio_frame, self.config.sample_rate)
            self.frame_count += 1
            
            # Update state tracking
            if is_speech:
                self.speech_frames += 1
                self.silence_frames = 0
            else:
                self.silence_frames += 1
                self.speech_frames = 0
            
            # Determine if we're currently speaking based on consecutive frames
            was_speaking = self.is_speaking
            
            if is_speech and self.speech_frames >= self.config.min_speech_frames:
                self.is_speaking = True
            elif not is_speech and self.silence_frames >= self.config.min_silence_frames:
                self.is_speaking = False
            
            # Log state changes
            if self.config.enable_logging and was_speaking != self.is_speaking:
                state = "SPEECH" if self.is_speaking else "SILENCE"
                logger.debug(f"VAD state changed to {state} at frame {self.frame_count}")
            
            return is_speech
            
        except Exception as e:
            logger.error(f"VAD processing error: {e}")
            return False
    
    def process_audio_chunk(self, audio_chunk: bytes) -> List[bool]:
        """
        Process a larger audio chunk by splitting it into frames.
        
        Args:
            audio_chunk: Raw audio chunk bytes (16-bit PCM, mono)
            
        Returns:
            List[bool]: List of VAD results for each frame
        """
        results = []
        frame_size_bytes = self.frame_size * 2
        
        for i in range(0, len(audio_chunk), frame_size_bytes):
            frame = audio_chunk[i:i + frame_size_bytes]
            if len(frame) == frame_size_bytes:
                result = self.process_frame(frame)
                results.append(result)
        
        return results
    
    def get_speech_segments(self, audio_data: bytes, 
                          min_segment_duration_ms: int = 100) -> List[Tuple[int, int]]:
        """
        Extract speech segments from audio data.
        
        Args:
            audio_data: Complete audio data (16-bit PCM, mono)
            min_segment_duration_ms: Minimum segment duration in milliseconds
            
        Returns:
            List[Tuple[int, int]]: List of (start_frame, end_frame) tuples
        """
        segments = []
        frame_size_bytes = self.frame_size * 2
        min_segment_frames = int(min_segment_duration_ms / self.config.frame_duration_ms)
        
        in_speech = False
        speech_start = 0
        
        for i in range(0, len(audio_data), frame_size_bytes):
            frame = audio_data[i:i + frame_size_bytes]
            if len(frame) == frame_size_bytes:
                frame_idx = i // frame_size_bytes
                is_speech = self.process_frame(frame)
                
                if is_speech and not in_speech:
                    # Start of speech segment
                    in_speech = True
                    speech_start = frame_idx
                elif not is_speech and in_speech:
                    # End of speech segment
                    in_speech = False
                    segment_length = frame_idx - speech_start
                    if segment_length >= min_segment_frames:
                        segments.append((speech_start, frame_idx))
        
        # Handle case where audio ends during speech
        if in_speech:
            frame_idx = len(audio_data) // frame_size_bytes
            segment_length = frame_idx - speech_start
            if segment_length >= min_segment_frames:
                segments.append((speech_start, frame_idx))
        
        return segments
    
    def reset(self):
        """Reset VAD state."""
        self.speech_frames = 0
        self.silence_frames = 0
        self.is_speaking = False
        self.frame_count = 0
        logger.debug("VAD state reset")
    
    def get_stats(self) -> dict:
        """Get current VAD statistics."""
        return {
            "is_speaking": self.is_speaking,
            "speech_frames": self.speech_frames,
            "silence_frames": self.silence_frames,
            "total_frames": self.frame_count,
            "speech_ratio": self.speech_frames / max(self.frame_count, 1)
        }


class VADProcessor:
    """
    High-level VAD processor for real-time audio streams.
    
    This class provides a more convenient interface for processing
    continuous audio streams with VAD.
    """
    
    def __init__(self, config: Optional[VADConfig] = None):
        """Initialize the VAD processor."""
        self.config = config or VADConfig()
        self.vad = VoiceActivityDetector(self.config)
        self.audio_buffer = bytearray()
        self.frame_size_bytes = self.vad.frame_size * 2
        
    def process_audio(self, audio_data: bytes) -> List[bool]:
        """
        Process incoming audio data and return VAD results.
        
        Args:
            audio_data: Raw audio data (16-bit PCM, mono)
            
        Returns:
            List[bool]: VAD results for processed frames
        """
        # Add new audio to buffer
        self.audio_buffer.extend(audio_data)
        
        results = []
        # Process complete frames from buffer
        while len(self.audio_buffer) >= self.frame_size_bytes:
            frame = bytes(self.audio_buffer[:self.frame_size_bytes])
            result = self.vad.process_frame(frame)
            results.append(result)
            
            # Remove processed frame from buffer
            self.audio_buffer = self.audio_buffer[self.frame_size_bytes:]
        
        return results
    
    def is_currently_speaking(self) -> bool:
        """Check if currently detecting speech."""
        return self.vad.is_speaking
    
    def get_stats(self) -> dict:
        """Get VAD statistics."""
        return self.vad.get_stats()
    
    def reset(self):
        """Reset processor state."""
        self.vad.reset()
        self.audio_buffer.clear()