"""
TTS Service - Main Service Implementation

This module implements the main TTS service that handles audio synthesis,
file management, and Redis message publishing for the microservices architecture.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from redis.asyncio import Redis

from openai_tts_client import OpenAITTSClient, TTSConfig as OpenAITTSConfig, VoiceType
from audio_file_manager import AudioFileManager, AudioFileConfig, AudioFileInfo
from asterisk_fallback import AsteriskFallbackHandler, AsteriskFallbackConfig, FallbackMode

logger = logging.getLogger(__name__)


@dataclass
class TTSServiceConfig:
    """Configuration for the TTS service."""
    # OpenAI settings
    openai_api_key: str

    # Redis settings
    redis_url: str = "redis://localhost:6379"
    
    openai_base_url: Optional[str] = None
    voice: str = "alloy"
    model: str = "tts-1"
    audio_format: str = "mp3"
    speed: float = 1.0
    
    # File management settings
    base_directory: str = "/shared/audio"
    temp_directory: str = "/tmp/tts_audio"
    file_ttl: int = 300  # 5 minutes
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    
    # Service settings
    health_check_interval: int = 30
    enable_debug_logging: bool = True
    
    # Fallback settings
    enable_fallback: bool = True
    fallback_mode: str = "sayalpha"
    asterisk_host: str = "localhost"
    asterisk_port: int = 8088
    ari_username: str = "AIAgent"
    ari_password: str = "c4d5359e2f9ddd394cd6aa116c1c6a96"


class TTSService:
    """
    Main TTS service that handles audio synthesis and file management.
    
    This service integrates OpenAI TTS API, audio file management, and Redis
    message publishing for the microservices architecture.
    """
    
    def __init__(self, config: TTSServiceConfig):
        """Initialize the TTS service."""
        self.config = config
        self.redis_client: Optional[Redis] = None
        
        # Initialize components
        self.tts_client = OpenAITTSClient(
            OpenAITTSConfig(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                voice=VoiceType(config.voice),
                model=config.model,
                audio_format=config.audio_format,
                speed=config.speed
            )
        )
        
        self.file_manager = AudioFileManager(
            AudioFileConfig(
                base_directory=config.base_directory,
                temp_directory=config.temp_directory,
                file_ttl=config.file_ttl,
                max_file_size=config.max_file_size
            )
        )
        
        self.fallback_handler = AsteriskFallbackHandler(
            AsteriskFallbackConfig(
                enabled=config.enable_fallback,
                fallback_mode=FallbackMode(config.fallback_mode),
                asterisk_host=config.asterisk_host,
                asterisk_port=config.asterisk_port,
                ari_username=config.ari_username,
                ari_password=config.ari_password
            )
        )
        
        # Service state
        self._running = False
        self._health_check_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            'service_started_at': 0,
            'requests_processed': 0,
            'audio_files_created': 0,
            'audio_files_deleted': 0,
            'errors': 0,
            'redis_errors': 0,
            'tts_errors': 0,
            'file_errors': 0
        }
    
    async def start(self):
        """Start the TTS service."""
        try:
            logger.info("Starting TTS service...")
            
            # Initialize Redis client
            self.redis_client = Redis.from_url(self.config.redis_url, decode_responses=True)
            await self.redis_client.ping()
            
            # Start file manager
            await self.file_manager.start()
            
            # Test OpenAI TTS connection
            if not await self.tts_client.test_connection():
                raise Exception("OpenAI TTS API connection test failed")
            
            # Start health check task
            self._running = True
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            
            # Start message processing
            await self._start_message_processing()
            
            self.stats['service_started_at'] = time.time()
            logger.info("TTS service started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start TTS service: {e}")
            raise
    
    async def stop(self):
        """Stop the TTS service."""
        try:
            logger.info("Stopping TTS service...")
            
            self._running = False
            
            # Stop health check task
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
            
            # Stop file manager
            await self.file_manager.stop()
            
            # Close TTS client
            await self.tts_client.close()
            
            # Close Redis client
            if self.redis_client:
                await self.redis_client.close()
            
            logger.info("TTS service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping TTS service: {e}")
    
    async def _start_message_processing(self):
        """Start processing Redis messages."""
        try:
            # Subscribe to relevant channels
            pubsub = self.redis_client.pubsub()
            await pubsub.subscribe(
                "llm:response:ready",
                "llm:error",
                "calls:control:play_audio",
                "calls:control:stop_audio"
            )
            
            logger.info("Started message processing")
            
            # Process messages
            async for message in pubsub.listen():
                if not self._running:
                    break
                
                try:
                    await self._handle_message(message)
                except Exception as e:
                    self.stats['errors'] += 1
                    logger.error(f"Error processing message: {e}")
            
        except Exception as e:
            logger.error(f"Error in message processing: {e}")
            raise
    
    async def _handle_message(self, message: Dict[str, Any]):
        """Handle incoming Redis messages."""
        try:
            if message['type'] != 'message':
                return
            
            channel = message['channel']
            data = json.loads(message['data'])
            
            if channel == "llm:response:ready":
                await self._handle_llm_response(data)
            elif channel == "llm:error":
                await self._handle_llm_error(data)
            elif channel == "calls:control:play_audio":
                await self._handle_play_audio(data)
            elif channel == "calls:control:stop_audio":
                await self._handle_stop_audio(data)
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error handling message: {e}")
    
    async def _handle_llm_response(self, data: Dict[str, Any]):
        """Handle LLM response ready for TTS synthesis."""
        try:
            channel_id = data.get('channel_id')
            text = data.get('text', '')
            model_used = data.get('model_used', 'unknown')
            tokens_used = data.get('tokens_used', 0)
            
            if not channel_id or not text:
                logger.warning("Invalid LLM response data received")
                return
            
            logger.info(f"Processing LLM response for channel {channel_id}: {text[:50]}...")
            
            # Try to synthesize audio with OpenAI TTS
            try:
                tts_response = await self.tts_client.synthesize_text(text)
                
                # Save audio file
                file_info = await self.file_manager.save_audio_file(
                    audio_data=tts_response.audio_data,
                    text=text,
                    original_format=tts_response.audio_format,
                    metadata={
                        'channel_id': channel_id,
                        'model_used': model_used,
                        'tokens_used': tokens_used,
                        'voice_used': tts_response.voice_used,
                        'tts_model': tts_response.model_used,
                        'duration_ms': tts_response.duration_ms,
                        'file_size': tts_response.file_size
                    }
                )
                
                # Publish audio ready message
                await self._publish_audio_ready(channel_id, file_info)
                
            except Exception as tts_error:
                logger.warning(f"OpenAI TTS failed for channel {channel_id}: {tts_error}")
                
                # Try fallback to Asterisk SayAlpha
                fallback_result = await self.fallback_handler.handle_fallback(text, channel_id)
                
                if fallback_result['success']:
                    # Publish fallback response
                    await self._publish_fallback_response(channel_id, fallback_result)
                    logger.info(f"Fallback successful for channel {channel_id}: {fallback_result['fallback_mode']}")
                else:
                    # Both TTS and fallback failed
                    logger.error(f"Both TTS and fallback failed for channel {channel_id}")
                    await self._publish_error(channel_id, f"TTS and fallback failed: {fallback_result.get('error', 'Unknown error')}")
            
            self.stats['requests_processed'] += 1
            self.stats['audio_files_created'] += 1
            
            logger.info(f"Audio synthesized for channel {channel_id}: {file_info.file_id}")
            
        except Exception as e:
            self.stats['tts_errors'] += 1
            logger.error(f"Error processing LLM response: {e}")
            
            # Publish error message
            await self._publish_error(data.get('channel_id', 'unknown'), str(e))
    
    async def _handle_llm_error(self, data: Dict[str, Any]):
        """Handle LLM error message."""
        try:
            channel_id = data.get('channel_id')
            error_message = data.get('error', 'Unknown error')
            
            if not channel_id:
                logger.warning("No channel_id in LLM error message")
                return
            
            logger.warning(f"LLM error for channel {channel_id}: {error_message}")
            
            # Publish error to call controller
            await self._publish_error(channel_id, f"LLM Error: {error_message}")
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error handling LLM error: {e}")
    
    async def _handle_play_audio(self, data: Dict[str, Any]):
        """Handle play audio request."""
        try:
            channel_id = data.get('channel_id')
            file_id = data.get('file_id')
            
            if not channel_id or not file_id:
                logger.warning("Invalid play audio request")
                return
            
            # Get file information
            file_info = await self.file_manager.get_audio_file(file_id)
            if not file_info:
                logger.error(f"Audio file {file_id} not found for channel {channel_id}")
                await self._publish_error(channel_id, f"Audio file {file_id} not found")
                return
            
            # Publish audio file info to call controller
            await self._publish_audio_file_info(channel_id, file_info)
            
            logger.info(f"Audio file {file_id} ready for playback on channel {channel_id}")
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error handling play audio request: {e}")
    
    async def _handle_stop_audio(self, data: Dict[str, Any]):
        """Handle stop audio request."""
        try:
            channel_id = data.get('channel_id')
            
            if not channel_id:
                logger.warning("No channel_id in stop audio request")
                return
            
            # Publish stop audio message to call controller
            await self._publish_stop_audio(channel_id)
            
            logger.info(f"Stop audio requested for channel {channel_id}")
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error handling stop audio request: {e}")
    
    async def _publish_audio_ready(self, channel_id: str, file_info: AudioFileInfo):
        """Publish audio ready message."""
        try:
            message = {
                'channel_id': channel_id,
                'file_id': file_info.file_id,
                'file_path': file_info.file_path,
                'duration_ms': file_info.duration_ms,
                'file_size': file_info.file_size,
                'audio_format': file_info.converted_format,
                'sample_rate': file_info.sample_rate,
                'channels': file_info.channels,
                'bit_depth': file_info.bit_depth,
                'timestamp': time.time()
            }
            
            await self.redis_client.publish(
                "tts:audio:ready",
                json.dumps(message)
            )
            
            logger.debug(f"Published audio ready for channel {channel_id}")
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Error publishing audio ready: {e}")
    
    async def _publish_audio_file_info(self, channel_id: str, file_info: AudioFileInfo):
        """Publish audio file information."""
        try:
            message = {
                'channel_id': channel_id,
                'file_id': file_info.file_id,
                'file_path': file_info.file_path,
                'duration_ms': file_info.duration_ms,
                'file_size': file_info.file_size,
                'audio_format': file_info.converted_format,
                'sample_rate': file_info.sample_rate,
                'channels': file_info.channels,
                'bit_depth': file_info.bit_depth,
                'timestamp': time.time()
            }
            
            await self.redis_client.publish(
                "tts:audio:file_info",
                json.dumps(message)
            )
            
            logger.debug(f"Published audio file info for channel {channel_id}")
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Error publishing audio file info: {e}")
    
    async def _publish_stop_audio(self, channel_id: str):
        """Publish stop audio message."""
        try:
            message = {
                'channel_id': channel_id,
                'timestamp': time.time()
            }
            
            await self.redis_client.publish(
                "tts:audio:stop",
                json.dumps(message)
            )
            
            logger.debug(f"Published stop audio for channel {channel_id}")
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Error publishing stop audio: {e}")
    
    async def _publish_fallback_response(self, channel_id: str, fallback_result: Dict[str, Any]):
        """Publish fallback response message."""
        try:
            message = {
                'channel_id': channel_id,
                'fallback_mode': fallback_result['fallback_mode'],
                'text': fallback_result['text'],
                'asterisk_command': fallback_result.get('asterisk_command', ''),
                'success': fallback_result['success'],
                'timestamp': time.time()
            }
            
            await self.redis_client.publish(
                "tts:fallback:ready",
                json.dumps(message)
            )
            
            logger.debug(f"Published fallback response for channel {channel_id}")
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Error publishing fallback response: {e}")
    
    async def _publish_error(self, channel_id: str, error_message: str):
        """Publish error message."""
        try:
            message = {
                'channel_id': channel_id,
                'error': error_message,
                'timestamp': time.time()
            }
            
            await self.redis_client.publish(
                "tts:error",
                json.dumps(message)
            )
            
            logger.debug(f"Published error for channel {channel_id}")
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Error publishing error message: {e}")
    
    async def _health_check_loop(self):
        """Background health check loop."""
        while self._running:
            try:
                await asyncio.sleep(self.config.health_check_interval)
                
                if not self._running:
                    break
                
                # Check Redis connection
                try:
                    await self.redis_client.ping()
                except Exception as e:
                    logger.error(f"Redis health check failed: {e}")
                    self.stats['redis_errors'] += 1
                
                # Check TTS client connection
                try:
                    if not await self.tts_client.test_connection():
                        logger.error("TTS client health check failed")
                        self.stats['tts_errors'] += 1
                except Exception as e:
                    logger.error(f"TTS client health check failed: {e}")
                    self.stats['tts_errors'] += 1
                
                # Publish health status
                await self._publish_health_status()
                
                logger.debug("Health check completed")
                
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
    
    async def _publish_health_status(self):
        """Publish health status to Redis."""
        try:
            health_data = {
                'service': 'tts_service',
                'status': 'healthy',
                'timestamp': time.time(),
                'stats': self.get_stats()
            }
            
            await self.redis_client.publish(
                "services:health:tts",
                json.dumps(health_data)
            )
            
        except Exception as e:
            logger.error(f"Error publishing health status: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        uptime = time.time() - self.stats['service_started_at'] if self.stats['service_started_at'] > 0 else 0
        
        return {
            **self.stats,
            'uptime_seconds': uptime,
            'tts_stats': self.tts_client.get_stats(),
            'file_manager_stats': self.file_manager.get_stats()
        }
    
    async def synthesize_text(self, text: str, channel_id: str = None) -> Optional[AudioFileInfo]:
        """Synthesize text to audio file."""
        try:
            # Synthesize audio
            tts_response = await self.tts_client.synthesize_text(text)
            
            # Save audio file
            file_info = await self.file_manager.save_audio_file(
                audio_data=tts_response.audio_data,
                text=text,
                original_format=tts_response.audio_format,
                metadata={
                    'channel_id': channel_id,
                    'voice_used': tts_response.voice_used,
                    'tts_model': tts_response.model_used,
                    'duration_ms': tts_response.duration_ms,
                    'file_size': tts_response.file_size
                }
            )
            
            self.stats['requests_processed'] += 1
            self.stats['audio_files_created'] += 1
            
            return file_info
            
        except Exception as e:
            self.stats['tts_errors'] += 1
            logger.error(f"Error synthesizing text: {e}")
            return None
    
    async def get_audio_file(self, file_id: str) -> Optional[AudioFileInfo]:
        """Get audio file information."""
        return await self.file_manager.get_audio_file(file_id)
    
    async def delete_audio_file(self, file_id: str) -> bool:
        """Delete an audio file."""
        success = await self.file_manager.delete_audio_file(file_id)
        if success:
            self.stats['audio_files_deleted'] += 1
        return success
