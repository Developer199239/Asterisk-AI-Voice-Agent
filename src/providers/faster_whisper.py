"""
Faster-Whisper STT Provider for Local AI Server
Optimized for telephony audio with better accuracy than Vosk
"""

import asyncio
import json
import logging
import base64
import time
from typing import Optional, Dict, Any
import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

class FasterWhisperProvider:
    """Faster-Whisper STT provider optimized for telephony audio"""
    
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        """
        Initialize Faster-Whisper provider
        
        Args:
            model_size: Model size (tiny, base, small, medium, large)
            device: Device to run on (cpu, cuda)
            compute_type: Compute type (int8, int16, float16, float32)
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self.model_loaded = False
        self.load_time = 0
        
        # Telephony-optimized settings
        self.sample_rate = 16000
        self.chunk_length = 30  # seconds
        self.vad_filter = True  # Enable VAD filtering
        self.vad_threshold = 0.35  # VAD threshold for telephony
        
        logger.info(f"🎤 Faster-Whisper Provider initialized: {model_size} on {device}")
    
    async def load_model(self):
        """Load the Faster-Whisper model"""
        if self.model_loaded:
            return
        
        try:
            start_time = time.time()
            logger.info(f"🔄 Loading Faster-Whisper model: {self.model_size}")
            
            # Load model with telephony optimizations
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root="/app/models/stt/faster_whisper"
            )
            
            self.load_time = time.time() - start_time
            self.model_loaded = True
            
            logger.info(f"✅ Faster-Whisper model loaded in {self.load_time:.2f}s")
            logger.info(f"📊 Model info: {self.model_size}, {self.device}, {self.compute_type}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load Faster-Whisper model: {e}")
            raise
    
    async def process_stt(self, audio_data: bytes, input_rate: int = 16000) -> str:
        """
        Process STT with Faster-Whisper
        
        Args:
            audio_data: Raw audio bytes (PCM16LE)
            input_rate: Sample rate of input audio
            
        Returns:
            Transcribed text
        """
        try:
            if not self.model_loaded:
                await self.load_model()
            
            # Convert audio bytes to numpy array
            audio_array = self._bytes_to_numpy(audio_data, input_rate)
            
            if len(audio_array) == 0:
                logger.warning("Empty audio data received")
                return ""
            
            # Log audio characteristics
            duration = len(audio_array) / self.sample_rate
            logger.info(f"🎵 STT INPUT - Processing audio: {len(audio_data)} bytes, {duration:.2f}s, {input_rate}Hz")
            
            # Transcribe with telephony optimizations
            start_time = time.time()
            
            segments, info = self.model.transcribe(
                audio_array,
                language="en",  # English for telephony
                task="transcribe",
                vad_filter=self.vad_filter,
                vad_threshold=self.vad_threshold,
                word_timestamps=True,  # Useful for telephony
                condition_on_previous_text=False,  # Better for short utterances
                initial_prompt="This is a phone conversation. The speaker is saying hello and asking how someone is doing today."
            )
            
            # Collect all segments
            transcript_parts = []
            for segment in segments:
                transcript_parts.append(segment.text.strip())
            
            transcript = " ".join(transcript_parts).strip()
            
            processing_time = time.time() - start_time
            
            # Log results
            if transcript:
                logger.info(f"📝 STT RESULT - Transcript: '{transcript}' (length: {len(transcript)})")
                logger.info(f"⏱️ STT TIMING - Processed in {processing_time:.2f}s")
            else:
                logger.warning("📝 STT RESULT - No speech detected")
            
            return transcript
            
        except Exception as e:
            logger.error(f"❌ STT processing error: {e}", exc_info=True)
            return ""
    
    def _bytes_to_numpy(self, audio_data: bytes, sample_rate: int) -> np.ndarray:
        """Convert audio bytes to numpy array for Faster-Whisper"""
        try:
            # Convert bytes to 16-bit signed integers
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Normalize to float32 range [-1.0, 1.0]
            audio_array = audio_array.astype(np.float32) / 32768.0
            
            # Resample if needed (Faster-Whisper expects 16kHz)
            if sample_rate != self.sample_rate:
                audio_array = self._resample_audio(audio_array, sample_rate, self.sample_rate)
            
            return audio_array
            
        except Exception as e:
            logger.error(f"Error converting audio bytes to numpy: {e}")
            return np.array([])
    
    def _resample_audio(self, audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Simple resampling using numpy (for basic cases)"""
        try:
            # Simple linear interpolation resampling
            ratio = target_sr / orig_sr
            new_length = int(len(audio) * ratio)
            
            # Create new indices
            old_indices = np.arange(len(audio))
            new_indices = np.linspace(0, len(audio) - 1, new_length)
            
            # Interpolate
            resampled = np.interp(new_indices, old_indices, audio)
            
            return resampled.astype(np.float32)
            
        except Exception as e:
            logger.error(f"Error resampling audio: {e}")
            return audio
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information"""
        return {
            "provider": "faster_whisper",
            "model_size": self.model_size,
            "device": self.device,
            "compute_type": self.compute_type,
            "sample_rate": self.sample_rate,
            "loaded": self.model_loaded,
            "load_time": self.load_time,
            "vad_enabled": self.vad_filter,
            "vad_threshold": self.vad_threshold
        }
    
    async def health_check(self) -> bool:
        """Check if the provider is healthy"""
        try:
            if not self.model_loaded:
                await self.load_model()
            return self.model is not None
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
