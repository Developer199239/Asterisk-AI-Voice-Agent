"""
OpenAI TTS Client for TTS Service

This module provides a client wrapper around OpenAI's TTS API for the TTS service,
supporting audio synthesis with the 'alloy' voice model and error handling.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, field
from enum import Enum

import openai
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class VoiceType(Enum):
    """Supported OpenAI TTS voices."""
    ALLOY = "alloy"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    NOVA = "nova"
    SHIMMER = "shimmer"


class AudioFormat(Enum):
    """Supported audio output formats."""
    MP3 = "mp3"
    OPUS = "opus"
    AAC = "aac"
    FLAC = "flac"


@dataclass
class TTSConfig:
    """Configuration for TTS client."""
    # API settings
    api_key: str
    base_url: Optional[str] = None
    
    # Voice settings
    voice: VoiceType = VoiceType.ALLOY
    model: str = "tts-1"  # tts-1 or tts-1-hd
    
    # Audio settings
    audio_format: AudioFormat = AudioFormat.MP3
    speed: float = 1.0  # 0.25 to 4.0
    
    # Response settings
    timeout: int = 30
    
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0
    backoff_factor: float = 2.0


@dataclass
class TTSResponse:
    """TTS response structure."""
    audio_data: bytes
    text: str
    voice_used: str
    model_used: str
    audio_format: str
    duration_ms: int
    file_size: int
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSError:
    """TTS error structure."""
    error_type: str
    error_message: str
    voice_attempted: str
    retry_count: int
    timestamp: float = field(default_factory=time.time)


class OpenAITTSClient:
    """
    OpenAI TTS client wrapper with error handling and retry logic.
    
    Provides a unified interface for OpenAI's TTS API with automatic retry
    and fallback mechanisms.
    """
    
    def __init__(self, config: TTSConfig):
        """Initialize the OpenAI TTS client."""
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout
        )
        
        # Statistics
        self.stats = {
            'requests_total': 0,
            'requests_successful': 0,
            'requests_failed': 0,
            'tokens_processed': 0,
            'total_audio_bytes': 0,
            'average_response_time_ms': 0,
            'errors_by_type': {},
            'voice_usage': {}
        }
        
        # Response tracking
        self._response_times: list[float] = []
    
    async def synthesize_text(self, text: str, voice: Optional[VoiceType] = None) -> TTSResponse:
        """Synthesize text to speech."""
        try:
            self.stats['requests_total'] += 1
            
            # Use provided voice or default
            voice_to_use = voice or self.config.voice
            
            # Generate audio with retry logic
            audio_data = await self._synthesize_with_retry(text, voice_to_use)
            
            # Calculate response metrics
            response_time_ms = int((time.time() - time.time()) * 1000)  # Will be updated in _synthesize_with_retry
            file_size = len(audio_data)
            
            # Update statistics
            self.stats['requests_successful'] += 1
            self.stats['total_audio_bytes'] += file_size
            self.stats['tokens_processed'] += len(text.split())  # Rough token estimation
            self.stats['voice_usage'][voice_to_use.value] = \
                self.stats['voice_usage'].get(voice_to_use.value, 0) + 1
            
            # Track response time
            self._response_times.append(response_time_ms)
            if len(self._response_times) > 100:  # Keep last 100 response times
                self._response_times = self._response_times[-100:]
            
            self.stats['average_response_time_ms'] = sum(self._response_times) / len(self._response_times)
            
            response = TTSResponse(
                audio_data=audio_data,
                text=text,
                voice_used=voice_to_use.value,
                model_used=self.config.model,
                audio_format=self.config.audio_format.value,
                duration_ms=response_time_ms,
                file_size=file_size
            )
            
            logger.info(f"Synthesized text using {voice_to_use.value}: "
                       f"{file_size} bytes, {response_time_ms}ms")
            
            return response
            
        except Exception as e:
            self.stats['requests_failed'] += 1
            self._track_error("synthesis_error", str(e), voice.value if voice else "unknown")
            
            logger.error(f"Failed to synthesize text: {e}")
            raise
    
    async def _synthesize_with_retry(self, text: str, voice: VoiceType) -> bytes:
        """Synthesize text with retry logic."""
        last_error = None
        
        for attempt in range(self.config.max_retries):
            try:
                start_time = time.time()
                
                response = await self.client.audio.speech.create(
                    model=self.config.model,
                    voice=voice.value,
                    input=text,
                    response_format=self.config.audio_format.value,
                    speed=self.config.speed
                )
                
                # Read audio data
                audio_data = await response.read()
                
                response_time_ms = int((time.time() - start_time) * 1000)
                
                logger.debug(f"Synthesis successful on attempt {attempt + 1}: "
                           f"{len(audio_data)} bytes, {response_time_ms}ms")
                
                return audio_data
                
            except Exception as e:
                last_error = e
                self._track_error("api_error", str(e), voice.value)
                
                logger.warning(f"Attempt {attempt + 1} failed with voice {voice.value}: {e}")
                
                # If this is not the last attempt, wait before retrying
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (self.config.backoff_factor ** attempt)
                    await asyncio.sleep(delay)
        
        # All attempts failed
        raise last_error or Exception("All synthesis attempts failed")
    
    def _track_error(self, error_type: str, error_message: str, voice: str):
        """Track error statistics."""
        self.stats['errors_by_type'][error_type] = \
            self.stats['errors_by_type'].get(error_type, 0) + 1
        
        logger.error(f"TTS Error [{error_type}] with {voice}: {error_message}")
    
    async def test_connection(self) -> bool:
        """Test the OpenAI TTS API connection."""
        try:
            # Test with a simple synthesis request
            response = await self.client.audio.speech.create(
                model=self.config.model,
                voice=self.config.voice.value,
                input="Hello",
                response_format=self.config.audio_format.value
            )
            
            # Read the response to ensure it's valid
            audio_data = await response.read()
            
            if len(audio_data) > 0:
                logger.info("OpenAI TTS API connection test successful")
                return True
            else:
                logger.error("OpenAI TTS API connection test failed: Empty response")
                return False
            
        except Exception as e:
            logger.error(f"OpenAI TTS API connection test failed: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            **self.stats,
            'success_rate': (
                self.stats['requests_successful'] / max(self.stats['requests_total'], 1)
            ) * 100,
            'average_file_size': (
                self.stats['total_audio_bytes'] / max(self.stats['requests_successful'], 1)
            ) if self.stats['requests_successful'] > 0 else 0
        }
    
    async def close(self):
        """Close the client."""
        try:
            await self.client.close()
            logger.info("OpenAI TTS client closed")
        except Exception as e:
            logger.error(f"Error closing OpenAI TTS client: {e}")
