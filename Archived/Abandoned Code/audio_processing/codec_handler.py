"""
Codec Handler for G.711 and G.722 audio codecs.

This module provides codec negotiation, transcoding, and format conversion
for voice communication over SIP.
"""

import logging
import numpy as np
import struct
from typing import Optional, Dict, Any, List, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

logger = logging.getLogger(__name__)


class CodecType(Enum):
    """Supported audio codec types."""
    G711_ULAW = "PCMU"  # G.711 μ-law
    G711_ALAW = "PCMA"  # G.711 A-law
    G722 = "G722"       # G.722
    PCM = "PCM"         # Linear PCM (internal format)


class CodecCapability(Enum):
    """Codec capability levels."""
    REQUIRED = "required"    # Must be supported
    PREFERRED = "preferred"  # Preferred if available
    OPTIONAL = "optional"    # Optional support


@dataclass
class CodecInfo:
    """Information about a codec."""
    codec_type: CodecType
    sample_rate: int
    channels: int
    bit_rate: int
    payload_type: int
    capability: CodecCapability = CodecCapability.PREFERRED
    description: str = ""


@dataclass
class CodecConfig:
    """Configuration for codec handler."""
    preferred_codecs: List[CodecType] = None
    fallback_codecs: List[CodecType] = None
    enable_logging: bool = True
    max_concurrent_transcodes: int = 10
    
    def __post_init__(self):
        if self.preferred_codecs is None:
            self.preferred_codecs = [CodecType.G722, CodecType.G711_ULAW, CodecType.G711_ALAW]
        if self.fallback_codecs is None:
            self.fallback_codecs = [CodecType.G711_ULAW, CodecType.G711_ALAW]


class CodecHandler:
    """
    Handler for audio codec negotiation and transcoding.
    
    This class provides functionality for:
    - Codec negotiation via SDP
    - Real-time transcoding between codecs
    - Format conversion and validation
    - Automatic fallback handling
    """
    
    def __init__(self, config: Optional[CodecConfig] = None):
        """
        Initialize the codec handler.
        
        Args:
            config: Codec configuration. If None, uses default config.
        """
        self.config = config or CodecConfig()
        
        # Codec information database
        self.codec_info = {
            CodecType.G711_ULAW: CodecInfo(
                codec_type=CodecType.G711_ULAW,
                sample_rate=8000,
                channels=1,
                bit_rate=64000,
                payload_type=0,
                description="G.711 μ-law (8kHz, mono, 64kbps)"
            ),
            CodecType.G711_ALAW: CodecInfo(
                codec_type=CodecType.G711_ALAW,
                sample_rate=8000,
                channels=1,
                bit_rate=64000,
                payload_type=8,
                description="G.711 A-law (8kHz, mono, 64kbps)"
            ),
            CodecType.G722: CodecInfo(
                codec_type=CodecType.G722,
                sample_rate=16000,
                channels=1,
                bit_rate=64000,
                payload_type=9,
                description="G.722 (16kHz, mono, 64kbps)"
            ),
            CodecType.PCM: CodecInfo(
                codec_type=CodecType.PCM,
                sample_rate=16000,
                channels=1,
                bit_rate=256000,
                payload_type=-1,  # Internal format
                description="Linear PCM (16kHz, mono, 256kbps)"
            )
        }
        
        # Thread pool for concurrent transcoding
        self.executor = ThreadPoolExecutor(max_workers=self.config.max_concurrent_transcodes)
        
        # Statistics
        self.stats = {
            'transcodes_performed': 0,
            'bytes_processed': 0,
            'errors': 0,
            'codec_negotiations': 0
        }
        
        if self.config.enable_logging:
            logger.info(f"Codec handler initialized with {len(self.codec_info)} supported codecs")
    
    def get_supported_codecs(self) -> List[CodecInfo]:
        """Get list of supported codecs."""
        return list(self.codec_info.values())
    
    def get_codec_info(self, codec_type: CodecType) -> Optional[CodecInfo]:
        """Get information about a specific codec."""
        return self.codec_info.get(codec_type)
    
    def negotiate_codec(self, remote_codecs: List[str], 
                       local_preferences: List[CodecType] = None) -> Optional[CodecType]:
        """
        Negotiate codec with remote party.
        
        Args:
            remote_codecs: List of codec names from remote SDP
            local_preferences: Local codec preferences (optional)
            
        Returns:
            CodecType: Negotiated codec or None if no match
        """
        if local_preferences is None:
            local_preferences = self.config.preferred_codecs
        
        # Convert remote codec names to CodecType
        remote_codec_types = []
        for codec_name in remote_codecs:
            for codec_type, info in self.codec_info.items():
                if info.codec_type.value == codec_name:
                    remote_codec_types.append(codec_type)
                    break
        
        # Find first match in local preferences
        for preferred_codec in local_preferences:
            if preferred_codec in remote_codec_types:
                negotiated_codec = preferred_codec
                self.stats['codec_negotiations'] += 1
                
                if self.config.enable_logging:
                    logger.info(f"Codec negotiated: {negotiated_codec.value} "
                              f"({self.codec_info[negotiated_codec].description})")
                
                return negotiated_codec
        
        # Try fallback codecs
        for fallback_codec in self.config.fallback_codecs:
            if fallback_codec in remote_codec_types:
                negotiated_codec = fallback_codec
                self.stats['codec_negotiations'] += 1
                
                if self.config.enable_logging:
                    logger.warning(f"Using fallback codec: {negotiated_codec.value} "
                                 f"({self.codec_info[negotiated_codec].description})")
                
                return negotiated_codec
        
        if self.config.enable_logging:
            logger.error(f"No compatible codec found. Remote: {remote_codecs}, "
                        f"Local preferences: {[c.value for c in local_preferences]}")
        
        return None
    
    def _pcm_to_ulaw(self, pcm_data: np.ndarray) -> bytes:
        """Convert PCM to G.711 μ-law."""
        # Clamp to valid range
        pcm_data = np.clip(pcm_data, -1.0, 1.0)
        
        # Convert to 16-bit PCM
        pcm_16bit = (pcm_data * 32767.0).astype(np.int16)
        
        # Convert to μ-law
        ulaw_data = bytearray()
        for sample in pcm_16bit:
            ulaw_byte = self._linear_to_ulaw(sample)
            ulaw_data.append(ulaw_byte)
        
        return bytes(ulaw_data)
    
    def _ulaw_to_pcm(self, ulaw_data: bytes) -> np.ndarray:
        """Convert G.711 μ-law to PCM."""
        pcm_samples = []
        for ulaw_byte in ulaw_data:
            pcm_sample = self._ulaw_to_linear(ulaw_byte)
            pcm_samples.append(pcm_sample)
        
        pcm_array = np.array(pcm_samples, dtype=np.float32)
        return pcm_array / 32768.0  # Normalize to [-1, 1]
    
    def _pcm_to_alaw(self, pcm_data: np.ndarray) -> bytes:
        """Convert PCM to G.711 A-law."""
        # Clamp to valid range
        pcm_data = np.clip(pcm_data, -1.0, 1.0)
        
        # Convert to 16-bit PCM
        pcm_16bit = (pcm_data * 32767.0).astype(np.int16)
        
        # Convert to A-law
        alaw_data = bytearray()
        for sample in pcm_16bit:
            alaw_byte = self._linear_to_alaw(sample)
            alaw_data.append(alaw_byte)
        
        return bytes(alaw_data)
    
    def _alaw_to_pcm(self, alaw_data: bytes) -> np.ndarray:
        """Convert G.711 A-law to PCM."""
        pcm_samples = []
        for alaw_byte in alaw_data:
            pcm_sample = self._alaw_to_linear(alaw_byte)
            pcm_samples.append(pcm_sample)
        
        pcm_array = np.array(pcm_samples, dtype=np.float32)
        return pcm_array / 32768.0  # Normalize to [-1, 1]
    
    def _pcm_to_g722(self, pcm_data: np.ndarray) -> bytes:
        """Convert PCM to G.722 (simplified implementation)."""
        # G.722 is a complex codec, this is a simplified version
        # In a real implementation, you would use a proper G.722 encoder
        
        # For now, we'll use a simple downsampling approach
        # This is NOT a proper G.722 implementation
        
        # Downsample from 16kHz to 8kHz
        if len(pcm_data) % 2 == 0:
            downsampled = pcm_data[::2]  # Simple decimation
        else:
            downsampled = pcm_data[:-1:2]  # Handle odd length
        
        # Convert to 16-bit PCM
        pcm_16bit = (downsampled * 32767.0).astype(np.int16)
        
        # Pack as bytes (simplified - not real G.722)
        return pcm_16bit.tobytes()
    
    def _g722_to_pcm(self, g722_data: bytes) -> np.ndarray:
        """Convert G.722 to PCM (simplified implementation)."""
        # G.722 is a complex codec, this is a simplified version
        # In a real implementation, you would use a proper G.722 decoder
        
        # For now, we'll use a simple upsampling approach
        # This is NOT a proper G.722 implementation
        
        # Unpack bytes to 16-bit PCM
        pcm_16bit = np.frombuffer(g722_data, dtype=np.int16)
        
        # Convert to float
        pcm_float = pcm_16bit.astype(np.float32) / 32768.0
        
        # Upsample from 8kHz to 16kHz (simple interpolation)
        upsampled = np.repeat(pcm_float, 2)
        
        return upsampled
    
    def _linear_to_ulaw(self, sample: int) -> int:
        """Convert linear PCM to μ-law."""
        # G.711 μ-law conversion
        if sample < 0:
            sample = -sample
            sign = 0x80
        else:
            sign = 0x00
        
        if sample > 32635:
            sample = 32635
        
        sample += 0x84
        
        # Find segment
        if sample < 0x100:
            segment = 0
        elif sample < 0x200:
            segment = 1
        elif sample < 0x400:
            segment = 2
        elif sample < 0x800:
            segment = 3
        elif sample < 0x1000:
            segment = 4
        elif sample < 0x2000:
            segment = 5
        elif sample < 0x4000:
            segment = 6
        else:
            segment = 7
        
        # Quantize
        quantized = (sample >> (segment + 3)) & 0x0F
        
        return ~(sign | (segment << 4) | quantized) & 0xFF
    
    def _ulaw_to_linear(self, ulaw_byte: int) -> int:
        """Convert μ-law to linear PCM."""
        # G.711 μ-law conversion
        ulaw_byte = ~ulaw_byte & 0xFF
        
        sign = ulaw_byte & 0x80
        segment = (ulaw_byte >> 4) & 0x07
        quantized = ulaw_byte & 0x0F
        
        # Reconstruct
        sample = (quantized << (segment + 3)) + 0x84
        sample <<= segment
        
        if sign:
            sample = -sample
        
        return sample - 0x84
    
    def _linear_to_alaw(self, sample: int) -> int:
        """Convert linear PCM to A-law."""
        # G.711 A-law conversion
        if sample < 0:
            sample = -sample
            sign = 0x80
        else:
            sign = 0x00
        
        if sample > 32635:
            sample = 32635
        
        # Find segment
        if sample < 0x100:
            segment = 0
        elif sample < 0x200:
            segment = 1
        elif sample < 0x400:
            segment = 2
        elif sample < 0x800:
            segment = 3
        elif sample < 0x1000:
            segment = 4
        elif sample < 0x2000:
            segment = 5
        elif sample < 0x4000:
            segment = 6
        else:
            segment = 7
        
        # Quantize
        quantized = (sample >> (segment + 3)) & 0x0F
        
        return sign | (segment << 4) | quantized
    
    def _alaw_to_linear(self, alaw_byte: int) -> int:
        """Convert A-law to linear PCM."""
        # G.711 A-law conversion
        sign = alaw_byte & 0x80
        segment = (alaw_byte >> 4) & 0x07
        quantized = alaw_byte & 0x0F
        
        # Reconstruct
        sample = (quantized << (segment + 3)) + 0x84
        sample <<= segment
        
        if sign:
            sample = -sample
        
        return sample - 0x84
    
    def transcode(self, audio_data: bytes, from_codec: CodecType, 
                 to_codec: CodecType) -> bytes:
        """
        Transcode audio data between codecs.
        
        Args:
            audio_data: Input audio data
            from_codec: Source codec type
            to_codec: Target codec type
            
        Returns:
            bytes: Transcoded audio data
            
        Raises:
            ValueError: If codec types are not supported
        """
        if from_codec not in self.codec_info:
            raise ValueError(f"Unsupported source codec: {from_codec}")
        
        if to_codec not in self.codec_info:
            raise ValueError(f"Unsupported target codec: {to_codec}")
        
        try:
            # Convert to PCM first
            if from_codec == CodecType.PCM:
                pcm_data = np.frombuffer(audio_data, dtype=np.float32)
            elif from_codec == CodecType.G711_ULAW:
                pcm_data = self._ulaw_to_pcm(audio_data)
            elif from_codec == CodecType.G711_ALAW:
                pcm_data = self._alaw_to_pcm(audio_data)
            elif from_codec == CodecType.G722:
                pcm_data = self._g722_to_pcm(audio_data)
            else:
                raise ValueError(f"Unsupported source codec: {from_codec}")
            
            # Convert from PCM to target codec
            if to_codec == CodecType.PCM:
                result = pcm_data.astype(np.float32).tobytes()
            elif to_codec == CodecType.G711_ULAW:
                result = self._pcm_to_ulaw(pcm_data)
            elif to_codec == CodecType.G711_ALAW:
                result = self._pcm_to_alaw(pcm_data)
            elif to_codec == CodecType.G722:
                result = self._pcm_to_g722(pcm_data)
            else:
                raise ValueError(f"Unsupported target codec: {to_codec}")
            
            # Update statistics
            self.stats['transcodes_performed'] += 1
            self.stats['bytes_processed'] += len(audio_data)
            
            return result
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Transcoding error: {e}")
            raise
    
    async def transcode_async(self, audio_data: bytes, from_codec: CodecType, 
                            to_codec: CodecType) -> bytes:
        """
        Asynchronously transcode audio data between codecs.
        
        Args:
            audio_data: Input audio data
            from_codec: Source codec type
            to_codec: Target codec type
            
        Returns:
            bytes: Transcoded audio data
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, 
            self.transcode, 
            audio_data, 
            from_codec, 
            to_codec
        )
    
    def validate_audio_data(self, audio_data: bytes, codec_type: CodecType) -> bool:
        """
        Validate audio data for a specific codec.
        
        Args:
            audio_data: Audio data to validate
            codec_type: Expected codec type
            
        Returns:
            bool: True if data is valid for the codec
        """
        if not audio_data:
            return False
        
        try:
            if codec_type == CodecType.PCM:
                # Check if data can be interpreted as float32
                np.frombuffer(audio_data, dtype=np.float32)
                return True
            elif codec_type in [CodecType.G711_ULAW, CodecType.G711_ALAW]:
                # Check if all bytes are valid for the codec
                for byte in audio_data:
                    if not (0 <= byte <= 255):
                        return False
                return True
            elif codec_type == CodecType.G722:
                # Check if data length is appropriate for G.722
                # G.722 typically produces 1 byte per sample at 8kHz
                return len(audio_data) > 0
            else:
                return False
        except Exception:
            return False
    
    def get_codec_stats(self) -> Dict[str, Any]:
        """Get codec handler statistics."""
        return self.stats.copy()
    
    def reset_stats(self):
        """Reset codec handler statistics."""
        self.stats = {
            'transcodes_performed': 0,
            'bytes_processed': 0,
            'errors': 0,
            'codec_negotiations': 0
        }
    
    def close(self):
        """Close the codec handler and cleanup resources."""
        self.executor.shutdown(wait=True)
        if self.config.enable_logging:
            logger.info("Codec handler closed")


class CodecManager:
    """
    High-level manager for codec operations.
    
    This class provides a convenient interface for managing
    multiple codec handlers and handling codec negotiations.
    """
    
    def __init__(self, config: Optional[CodecConfig] = None):
        """Initialize the codec manager."""
        self.config = config or CodecConfig()
        self.handlers = {}
        self.active_codecs = {}
    
    def create_handler(self, handler_id: str, config: Optional[CodecConfig] = None) -> CodecHandler:
        """
        Create a new codec handler.
        
        Args:
            handler_id: Unique identifier for the handler
            config: Handler configuration (optional)
            
        Returns:
            CodecHandler: Created handler
        """
        if handler_id in self.handlers:
            logger.warning(f"Handler '{handler_id}' already exists")
            return self.handlers[handler_id]
        
        handler_config = config or self.config
        handler = CodecHandler(handler_config)
        self.handlers[handler_id] = handler
        
        logger.info(f"Created codec handler '{handler_id}'")
        return handler
    
    def get_handler(self, handler_id: str) -> Optional[CodecHandler]:
        """Get a handler by ID."""
        return self.handlers.get(handler_id)
    
    def remove_handler(self, handler_id: str):
        """Remove a handler."""
        if handler_id in self.handlers:
            self.handlers[handler_id].close()
            del self.handlers[handler_id]
            self.active_codecs.pop(handler_id, None)
            logger.info(f"Removed handler '{handler_id}'")
    
    def negotiate_codec_for_handler(self, handler_id: str, remote_codecs: List[str]) -> Optional[CodecType]:
        """Negotiate codec for a specific handler."""
        if handler_id not in self.handlers:
            logger.warning(f"Handler '{handler_id}' not found")
            return None
        
        handler = self.handlers[handler_id]
        negotiated_codec = handler.negotiate_codec(remote_codecs)
        
        if negotiated_codec:
            self.active_codecs[handler_id] = negotiated_codec
        
        return negotiated_codec
    
    def transcode_for_handler(self, handler_id: str, audio_data: bytes, 
                            from_codec: CodecType, to_codec: CodecType) -> bytes:
        """Transcode audio for a specific handler."""
        if handler_id not in self.handlers:
            raise ValueError(f"Handler '{handler_id}' not found")
        
        handler = self.handlers[handler_id]
        return handler.transcode(audio_data, from_codec, to_codec)
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all handlers."""
        stats = {}
        for handler_id, handler in self.handlers.items():
            stats[handler_id] = handler.get_codec_stats()
        return stats
    
    def close_all(self):
        """Close all handlers."""
        for handler in self.handlers.values():
            handler.close()
        self.handlers.clear()
        self.active_codecs.clear()
