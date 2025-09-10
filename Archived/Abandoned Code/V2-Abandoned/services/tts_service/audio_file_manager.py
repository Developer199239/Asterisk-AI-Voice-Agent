"""
Audio File Manager for TTS Service

This module manages audio file operations including file storage, format conversion,
cleanup, and shared volume access for the TTS service.
"""

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import aiofiles
from pydub import AudioSegment
from pydub.utils import which

logger = logging.getLogger(__name__)


class AudioFormat(Enum):
    """Supported audio formats."""
    WAV = "wav"
    MP3 = "mp3"
    OPUS = "opus"
    AAC = "aac"
    FLAC = "flac"


@dataclass
class AudioFileInfo:
    """Information about an audio file."""
    file_id: str
    file_path: str
    original_format: str
    converted_format: str
    file_size: int
    duration_ms: int
    sample_rate: int
    channels: int
    bit_depth: int
    created_at: float
    expires_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioFileConfig:
    """Configuration for audio file management."""
    # Directory settings
    base_directory: str = "/shared/audio"
    temp_directory: str = "/tmp/tts_audio"
    
    # File settings
    file_ttl: int = 300  # 5 minutes in seconds
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    cleanup_interval: int = 60  # 1 minute
    
    # Audio format settings
    target_format: AudioFormat = AudioFormat.WAV
    target_sample_rate: int = 16000  # 16kHz for Asterisk compatibility
    target_channels: int = 1  # Mono
    target_bit_depth: int = 16
    
    # File naming
    use_uuid: bool = True
    include_timestamp: bool = True


class AudioFileManager:
    """
    Manages audio file operations for the TTS service.
    
    Handles file storage, format conversion, cleanup, and shared volume access
    with proper error handling and monitoring.
    """
    
    def __init__(self, config: AudioFileConfig):
        """Initialize the audio file manager."""
        self.config = config
        self.base_dir = Path(config.base_directory)
        self.temp_dir = Path(config.temp_directory)
        
        # File tracking
        self.active_files: Dict[str, AudioFileInfo] = {}
        self.file_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Statistics
        self.stats = {
            'files_created': 0,
            'files_deleted': 0,
            'files_converted': 0,
            'total_bytes_processed': 0,
            'conversion_errors': 0,
            'file_errors': 0,
            'cleanup_runs': 0
        }
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start the audio file manager."""
        try:
            # Create directories
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Verify pydub dependencies
            if not which("ffmpeg"):
                logger.warning("FFmpeg not found. Audio conversion may not work properly.")
            
            # Start cleanup task
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            
            logger.info(f"Audio file manager started with base directory: {self.base_dir}")
            
        except Exception as e:
            logger.error(f"Failed to start audio file manager: {e}")
            raise
    
    async def stop(self):
        """Stop the audio file manager."""
        try:
            self._running = False
            
            if self._cleanup_task:
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
            
            # Clean up all active files
            await self._cleanup_all_files()
            
            logger.info("Audio file manager stopped")
            
        except Exception as e:
            logger.error(f"Error stopping audio file manager: {e}")
    
    async def save_audio_file(self, audio_data: bytes, text: str, 
                            original_format: str = "mp3",
                            metadata: Optional[Dict[str, Any]] = None) -> AudioFileInfo:
        """Save audio data to a file with format conversion."""
        try:
            # Generate unique file ID
            file_id = self._generate_file_id()
            
            # Create file paths
            temp_file_path = self.temp_dir / f"{file_id}.{original_format}"
            final_file_path = self.base_dir / f"{file_id}.{self.config.target_format.value}"
            
            # Save original audio to temp file
            async with aiofiles.open(temp_file_path, 'wb') as f:
                await f.write(audio_data)
            
            # Convert audio format if needed
            if original_format.lower() != self.config.target_format.value:
                await self._convert_audio_format(
                    temp_file_path, 
                    final_file_path, 
                    original_format, 
                    self.config.target_format.value
                )
                
                # Remove temp file
                temp_file_path.unlink(missing_ok=True)
            else:
                # Move temp file to final location
                temp_file_path.rename(final_file_path)
            
            # Get file information
            file_size = final_file_path.stat().st_size
            duration_ms = await self._get_audio_duration(final_file_path)
            
            # Create file info
            file_info = AudioFileInfo(
                file_id=file_id,
                file_path=str(final_file_path),
                original_format=original_format,
                converted_format=self.config.target_format.value,
                file_size=file_size,
                duration_ms=duration_ms,
                sample_rate=self.config.target_sample_rate,
                channels=self.config.target_channels,
                bit_depth=self.config.target_bit_depth,
                created_at=time.time(),
                expires_at=time.time() + self.config.file_ttl,
                metadata=metadata or {}
            )
            
            # Track file
            self.active_files[file_id] = file_info
            
            # Update statistics
            self.stats['files_created'] += 1
            self.stats['total_bytes_processed'] += file_size
            
            logger.info(f"Saved audio file {file_id}: {file_size} bytes, {duration_ms}ms")
            
            return file_info
            
        except Exception as e:
            self.stats['file_errors'] += 1
            logger.error(f"Failed to save audio file: {e}")
            raise
    
    async def get_audio_file(self, file_id: str) -> Optional[AudioFileInfo]:
        """Get information about an audio file."""
        try:
            # Check if file is tracked
            if file_id in self.active_files:
                file_info = self.active_files[file_id]
                
                # Check if file still exists
                if Path(file_info.file_path).exists():
                    return file_info
                else:
                    # File was deleted externally, remove from tracking
                    del self.active_files[file_id]
                    return None
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting audio file {file_id}: {e}")
            return None
    
    async def read_audio_file(self, file_id: str) -> Optional[bytes]:
        """Read audio file data."""
        try:
            file_info = await self.get_audio_file(file_id)
            if not file_info:
                return None
            
            async with aiofiles.open(file_info.file_path, 'rb') as f:
                return await f.read()
                
        except Exception as e:
            logger.error(f"Error reading audio file {file_id}: {e}")
            return None
    
    async def delete_audio_file(self, file_id: str) -> bool:
        """Delete an audio file."""
        try:
            file_info = self.active_files.get(file_id)
            if not file_info:
                return False
            
            # Delete file from filesystem
            file_path = Path(file_info.file_path)
            if file_path.exists():
                file_path.unlink()
            
            # Remove from tracking
            del self.active_files[file_id]
            
            # Update statistics
            self.stats['files_deleted'] += 1
            
            logger.info(f"Deleted audio file {file_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting audio file {file_id}: {e}")
            return False
    
    async def _convert_audio_format(self, input_path: Path, output_path: Path, 
                                  input_format: str, output_format: str):
        """Convert audio format using pydub."""
        try:
            # Load audio file
            audio = AudioSegment.from_file(str(input_path), format=input_format)
            
            # Convert to target format
            if output_format == "wav":
                audio = audio.set_frame_rate(self.config.target_sample_rate)
                audio = audio.set_channels(self.config.target_channels)
                audio = audio.set_sample_width(self.config.target_bit_depth // 8)
            
            # Export to target format
            audio.export(str(output_path), format=output_format)
            
            self.stats['files_converted'] += 1
            
            logger.debug(f"Converted audio from {input_format} to {output_format}")
            
        except Exception as e:
            self.stats['conversion_errors'] += 1
            logger.error(f"Audio conversion failed: {e}")
            raise
    
    async def _get_audio_duration(self, file_path: Path) -> int:
        """Get audio duration in milliseconds."""
        try:
            audio = AudioSegment.from_file(str(file_path))
            return len(audio)  # pydub returns duration in milliseconds
        except Exception as e:
            logger.error(f"Error getting audio duration: {e}")
            return 0
    
    def _generate_file_id(self) -> str:
        """Generate a unique file ID."""
        if self.config.use_uuid:
            file_id = str(uuid.uuid4())
        else:
            file_id = f"tts_{int(time.time() * 1000)}"
        
        if self.config.include_timestamp:
            timestamp = int(time.time())
            file_id = f"{file_id}_{timestamp}"
        
        return file_id
    
    async def _cleanup_loop(self):
        """Background cleanup loop for expired files."""
        while self._running:
            try:
                await asyncio.sleep(self.config.cleanup_interval)
                
                if not self._running:
                    break
                
                await self._cleanup_expired_files()
                
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    async def _cleanup_expired_files(self):
        """Clean up expired files."""
        try:
            current_time = time.time()
            expired_files = []
            
            for file_id, file_info in self.active_files.items():
                if current_time >= file_info.expires_at:
                    expired_files.append(file_id)
            
            # Delete expired files
            for file_id in expired_files:
                await self.delete_audio_file(file_id)
            
            if expired_files:
                logger.info(f"Cleaned up {len(expired_files)} expired files")
            
            self.stats['cleanup_runs'] += 1
            
        except Exception as e:
            logger.error(f"Error cleaning up expired files: {e}")
    
    async def _cleanup_all_files(self):
        """Clean up all active files."""
        try:
            file_ids = list(self.active_files.keys())
            
            for file_id in file_ids:
                await self.delete_audio_file(file_id)
            
            logger.info(f"Cleaned up {len(file_ids)} files")
            
        except Exception as e:
            logger.error(f"Error cleaning up all files: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get file manager statistics."""
        return {
            **self.stats,
            'active_files': len(self.active_files),
            'base_directory': str(self.base_dir),
            'temp_directory': str(self.temp_dir)
        }
    
    def get_active_files(self) -> List[AudioFileInfo]:
        """Get list of active files."""
        return list(self.active_files.values())
    
    async def get_file_usage(self) -> Dict[str, Any]:
        """Get file system usage information."""
        try:
            total_size = 0
            file_count = 0
            
            for file_info in self.active_files.values():
                if Path(file_info.file_path).exists():
                    total_size += file_info.file_size
                    file_count += 1
            
            return {
                'total_size_bytes': total_size,
                'total_size_mb': total_size / (1024 * 1024),
                'file_count': file_count,
                'average_file_size': total_size / max(file_count, 1)
            }
            
        except Exception as e:
            logger.error(f"Error getting file usage: {e}")
            return {
                'total_size_bytes': 0,
                'total_size_mb': 0,
                'file_count': 0,
                'average_file_size': 0
            }
