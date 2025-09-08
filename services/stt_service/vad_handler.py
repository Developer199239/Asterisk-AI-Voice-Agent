"""
Voice Activity Detection Handler for STT Service

This module provides voice activity detection using WebRTC VAD
to identify speech segments in audio streams.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Callable, List, Tuple
from enum import Enum

try:
    import webrtcvad
except ImportError:
    webrtcvad = None
    logging.warning("webrtcvad not available - VAD functionality will be limited")

logger = logging.getLogger(__name__)


class VADSensitivity(Enum):
    """VAD sensitivity levels."""
    VERY_AGGRESSIVE = 0  # Most aggressive, least sensitive
    AGGRESSIVE = 1
    MODERATE = 2
    LESS_AGGRESSIVE = 3  # Least aggressive, most sensitive


@dataclass
class VADState:
    """Voice activity detection state."""
    is_speaking: bool
    confidence: float
    timestamp: float
    frame_count: int
    speech_frames: int
    silence_frames: int


@dataclass
class SpeechSegment:
    """A detected speech segment."""
    start_time: float
    end_time: float
    duration: float
    audio_data: bytes
    confidence: float
    frame_count: int


class VADHandler:
    """Voice Activity Detection handler using WebRTC VAD."""
    
    def __init__(
        self,
        sample_rate: int = 8000,
        frame_duration_ms: int = 20,
        sensitivity: VADSensitivity = VADSensitivity.MODERATE,
        silence_threshold_frames: int = 10,  # Frames of silence to end speech
        min_speech_frames: int = 3,  # Minimum frames to start speech
        on_speech_start: Optional[Callable[[], None]] = None,
        on_speech_end: Optional[Callable[[SpeechSegment], None]] = None
    ):
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.sensitivity = sensitivity
        self.silence_threshold_frames = silence_threshold_frames
        self.min_speech_frames = min_speech_frames
        
        # Callbacks
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        
        # VAD instance
        self.vad = None
        if webrtcvad:
            try:
                self.vad = webrtcvad.Vad(int(sensitivity.value))
                logger.info(f"VAD initialized with sensitivity {sensitivity.name}")
            except Exception as e:
                logger.error(f"Failed to initialize VAD: {e}")
                self.vad = None
        else:
            logger.warning("WebRTC VAD not available - using fallback VAD")
        
        # Frame size calculation
        self.frame_size = (sample_rate * frame_duration_ms) // 1000
        self.frame_size_bytes = self.frame_size * 2  # 16-bit samples
        
        # State tracking
        self.current_state = VADState(
            is_speaking=False,
            confidence=0.0,
            timestamp=0.0,
            frame_count=0,
            speech_frames=0,
            silence_frames=0
        )
        
        # Speech segment tracking
        self.speech_buffer = bytearray()
        self.speech_start_time = 0.0
        self.speech_frames = 0
        self.silence_frames = 0
        
        # Audio buffer for frame alignment
        self.audio_buffer = bytearray()
        
    def process_audio(self, audio_data: bytes) -> List[SpeechSegment]:
        """Process audio data and return detected speech segments."""
        segments = []
        
        # Add to buffer
        self.audio_buffer.extend(audio_data)
        
        # Process complete frames
        while len(self.audio_buffer) >= self.frame_size_bytes:
            # Extract frame
            frame = bytes(self.audio_buffer[:self.frame_size_bytes])
            self.audio_buffer = self.audio_buffer[self.frame_size_bytes:]
            
            # Process frame
            segment = self._process_frame(frame)
            if segment:
                segments.append(segment)
        
        return segments
    
    def _process_frame(self, frame: bytes) -> Optional[SpeechSegment]:
        """Process a single audio frame."""
        current_time = time.time()
        self.current_state.frame_count += 1
        self.current_state.timestamp = current_time
        
        # Detect voice activity
        is_speech = self._detect_speech(frame)
        
        if is_speech:
            self.current_state.speech_frames += 1
            self.silence_frames = 0
            
            if not self.current_state.is_speaking:
                # Speech started
                self._start_speech(current_time)
            else:
                # Continue speech
                self.speech_frames += 1
                self.speech_buffer.extend(frame)
        else:
            self.current_state.silence_frames += 1
            self.silence_frames += 1
            
            if self.current_state.is_speaking:
                # Check if speech should end
                if self.silence_frames >= self.silence_threshold_frames:
                    # Speech ended
                    return self._end_speech(current_time)
                else:
                    # Continue speech (temporary silence)
                    self.speech_frames += 1
                    self.speech_buffer.extend(frame)
        
        return None
    
    def _detect_speech(self, frame: bytes) -> bool:
        """Detect if frame contains speech using VAD."""
        if self.vad:
            try:
                # WebRTC VAD requires 16-bit PCM, 8kHz, 10/20/30ms frames
                return self.vad.is_speech(frame, self.sample_rate)
            except Exception as e:
                logger.error(f"VAD error: {e}")
                return False
        else:
            # Fallback: simple energy-based detection
            return self._fallback_vad(frame)
    
    def _fallback_vad(self, frame: bytes) -> bool:
        """Fallback VAD using energy detection."""
        if len(frame) < 2:
            return False
        
        # Calculate RMS energy
        import struct
        samples = struct.unpack(f'{len(frame)//2}h', frame)
        energy = sum(sample * sample for sample in samples) / len(samples)
        
        # Simple threshold-based detection
        threshold = 1000  # Adjust based on testing
        return energy > threshold
    
    def _start_speech(self, timestamp: float):
        """Handle speech start."""
        self.current_state.is_speaking = True
        self.speech_start_time = timestamp
        self.speech_frames = 0
        self.silence_frames = 0
        self.speech_buffer.clear()
        
        logger.debug("Speech started")
        
        if self.on_speech_start:
            try:
                self.on_speech_start()
            except Exception as e:
                logger.error(f"Error in speech start callback: {e}")
    
    def _end_speech(self, timestamp: float) -> SpeechSegment:
        """Handle speech end and return speech segment."""
        duration = timestamp - self.speech_start_time
        
        # Only create segment if we have enough speech frames
        if self.speech_frames >= self.min_speech_frames:
            segment = SpeechSegment(
                start_time=self.speech_start_time,
                end_time=timestamp,
                duration=duration,
                audio_data=bytes(self.speech_buffer),
                confidence=self.current_state.confidence,
                frame_count=self.speech_frames
            )
            
            logger.debug(f"Speech ended: {duration:.2f}s, {self.speech_frames} frames")
            
            if self.on_speech_end:
                try:
                    self.on_speech_end(segment)
                except Exception as e:
                    logger.error(f"Error in speech end callback: {e}")
            
            return segment
        
        # Reset state
        self.current_state.is_speaking = False
        self.speech_buffer.clear()
        self.speech_frames = 0
        self.silence_frames = 0
        
        return None
    
    def get_current_state(self) -> VADState:
        """Get current VAD state."""
        return self.current_state
    
    def reset(self):
        """Reset VAD state."""
        self.current_state = VADState(
            is_speaking=False,
            confidence=0.0,
            timestamp=0.0,
            frame_count=0,
            speech_frames=0,
            silence_frames=0
        )
        self.speech_buffer.clear()
        self.audio_buffer.clear()
        self.speech_start_time = 0.0
        self.speech_frames = 0
        self.silence_frames = 0
