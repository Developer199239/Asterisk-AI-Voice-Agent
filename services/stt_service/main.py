"""
STT Service - Main Entry Point

This service handles speech-to-text processing.
It adapts the existing stt_handler.py from the v1.0 architecture.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

import structlog

from shared.logging_config import setup_logging
from shared.config import load_config, STTServiceConfig, CallControllerConfig
from shared.health_check import create_health_check_app
import uvicorn

# Add shared modules to path
# sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from shared.redis_client import RedisMessageQueue
from rtp_handler import RTPStreamManager, RTPStreamInfo
from vad_handler import SpeechSegment
from rtp_stt_handler import RTPSTTHandler, RTPSTTConfig
from channel_correlation import ChannelCorrelationManager
from realtime_client import RealtimeClient, RealtimeConfig, VoiceType
from transcription_publisher import TranscriptionPublisher, TranscriptionMessage
from barge_in_detector import BargeInDetector, BargeInConfig, BargeInEvent

# Load configuration and set up logging
config = load_config("stt_service")
setup_logging(log_level=config.log_level)

logger = structlog.get_logger(__name__)

class STTService:
    def __init__(self, config: STTServiceConfig):
        self.config = config
        self.redis_client = RedisMessageQueue()
        self.channel_correlation = ChannelCorrelationManager()
        self.rtp_manager = RTPStreamManager(host="0.0.0.0", port=5004, correlation_manager=self.channel_correlation)
        self.running = False
        self.active_streams = {}  # Track active RTP streams
        
        # Initialize RTP STT handler
        self.rtp_stt_config = RTPSTTConfig(
            rtp_sample_rate=8000,
            target_sample_rate=24000,
            enable_audio_resampling=True,
            on_transcript=self._handle_transcript,
            on_speech_segment=self._handle_speech_segment_callback,
            on_error=self._handle_stt_error
        )
        
        # Initialize Realtime API client
        self.realtime_config = RealtimeConfig(
            api_key=self.config.openai_api_key,
            model="gpt-4o-realtime-preview",
            voice=VoiceType.ALLOY
        )
        self.realtime_client = RealtimeClient(self.realtime_config)
        
        # Initialize RTP STT handler
        self.rtp_stt_handler = RTPSTTHandler(self.rtp_stt_config, self.realtime_client)
        
        # Initialize transcription publisher
        self.transcription_publisher = TranscriptionPublisher(self.redis_client, self.channel_correlation)
        
        # Initialize barge-in detector
        barge_in_config = BargeInConfig(
            sensitivity_threshold=0.7,
            debounce_duration_ms=200,
            min_speech_duration_ms=100,
            max_silence_duration_ms=500,
            enable_debouncing=True,
            enable_volume_correlation=True,
            enable_timing_correlation=True
        )
        self.barge_in_detector = BargeInDetector(self.redis_client, barge_in_config)

    async def start(self):
        """Start the STT service"""
        logger.info("Starting STT Service - v2.0")
        
        try:
            # Start channel correlation manager
            await self.channel_correlation.start()
            logger.info("Channel correlation manager started")
            
            # Connect to Redis
            await self.redis_client.connect()
            logger.info("Connected to Redis")
            
            # Subscribe to new call events
            await self.redis_client.subscribe(["calls:new"], self._handle_new_call)
            logger.info("Subscribed to calls:new")
            
            # Start RTP STT handler
            stt_started = await self.rtp_stt_handler.start()
            if not stt_started:
                raise Exception("Failed to start RTP STT handler")
            logger.info("RTP STT handler started")
            
            # Start transcription publisher
            await self.transcription_publisher.start()
            logger.info("Transcription publisher started")
            
            # Start barge-in detector
            await self.barge_in_detector.start()
            logger.info("Barge-in detector started")
            
            # Start RTP UDP server with VAD support
            rtp_started = await self.rtp_manager.start(
                on_audio_data=self._handle_rtp_audio_data,
                on_speech_segment=self._handle_speech_segment
            )
            if not rtp_started:
                raise Exception("Failed to start RTP UDP server")
            logger.info("RTP UDP server started on port 5004 with VAD")
            
            self.running = True
            
            # Start health check server in a background task
            health_check_task = asyncio.create_task(self._start_health_check_server())
            
            # Start listening for messages in a background task
            listening_task = asyncio.create_task(self.redis_client.start_listening())
            
            # Gather all background tasks
            tasks = [health_check_task, listening_task]
            
            # Main service loop to keep the service alive
            while self.running:
                try:
                    # Wait for any task to complete
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    
                    for task in done:
                        # If a task has an exception, it will be raised here
                        exc = task.exception()
                        if exc:
                            logger.error(f"A background task failed: {exc}")
                            self.running = False # Trigger shutdown
                    
                    # If a task completes without error, it might be unexpected
                    # We can decide to log this or restart it if necessary
                    if self.running and not any(t.done() for t in tasks if not t.exception()):
                        await asyncio.sleep(1)
                        
                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt received, shutting down.")
                    self.running = False
                    
                # Cancel all pending tasks on shutdown
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"Failed to start STT service: {e}")
            raise

    async def _start_health_check_server(self):
        """Start the health check server."""
        dependency_checks = {
            "redis": self.redis_client.health_check,
            "openai_realtime": self.realtime_client.test_connection
        }
        app = create_health_check_app(self.config.service_name, dependency_checks)
        
        config = uvicorn.Config(app, host="0.0.0.0", port=self.config.health_check_port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def _handle_new_call(self, channel: str, message: dict):
        """Handle new call events"""
        try:
            # set_correlation_id(message.get('channel_id')) # This line is removed as per new_code
            logger.info(f"Received new call on {channel}: {message}")
            
            # Extract channel ID from message
            channel_id = message.get('channel_id')
            if not channel_id:
                logger.warning("No channel_id in new call message")
                return
            
            # Register channel with correlation manager
            self.channel_correlation.register_channel(channel_id, {
                'call_start_time': asyncio.get_event_loop().time(),
                'status': 'waiting_for_rtp'
            })
            
            # Track the new call
            self.active_streams[channel_id] = {
                'start_time': asyncio.get_event_loop().time(),
                'status': 'waiting_for_rtp'
            }
            
            logger.info(f"Registered and tracking new call for channel {channel_id}")
            
        except Exception as e:
            logger.error(f"Error handling new call: {e}")

    async def _handle_rtp_audio_data(self, audio_data: bytes, stream_info: RTPStreamInfo):
        """Handle RTP audio data from streams"""
        try:
            logger.debug(f"Received audio data from SSRC {stream_info.ssrc}: {len(audio_data)} bytes")
            
            # Convert stream info to dict for RTP STT handler
            stream_dict = {
                'ssrc': stream_info.ssrc,
                'payload_type': stream_info.payload_type,
                'sample_rate': stream_info.sample_rate,
                'channels': stream_info.channels,
                'packet_count': stream_info.packet_count,
                'bytes_received': stream_info.bytes_received
            }
            
            # Process audio with RTP STT handler
            success = await self.rtp_stt_handler.process_rtp_audio(audio_data, stream_dict)
            if not success:
                logger.warning(f"Failed to process RTP audio for SSRC {stream_info.ssrc}")
            
        except Exception as e:
            logger.error(f"Error handling RTP audio data: {e}")
    
    async def _handle_speech_segment(self, segment: SpeechSegment, stream_info: RTPStreamInfo):
        """Handle detected speech segment"""
        try:
            logger.info(f"Speech segment detected: {segment.duration:.2f}s, {len(segment.audio_data)} bytes from SSRC {stream_info.ssrc}")
            
            # Convert stream info to dict for RTP STT handler
            stream_dict = {
                'ssrc': stream_info.ssrc,
                'payload_type': stream_info.payload_type,
                'sample_rate': stream_info.sample_rate,
                'channels': stream_info.channels,
                'packet_count': stream_info.packet_count,
                'bytes_received': stream_info.bytes_received
            }
            
            # Process speech segment with RTP STT handler
            success = await self.rtp_stt_handler.process_speech_segment(segment, stream_dict)
            if not success:
                logger.warning(f"Failed to process speech segment for SSRC {stream_info.ssrc}")
            
            # Process barge-in detection
            channel_id = None
            if stream_info.ssrc:
                channel_info = self.channel_correlation.get_channel_by_ssrc(stream_info.ssrc)
                if channel_info:
                    channel_id = channel_info.channel_id
            
            if channel_id:
                # Process speech detection for barge-in analysis
                self.barge_in_detector.process_speech_detection(
                    channel_id=channel_id,
                    ssrc=stream_info.ssrc,
                    confidence=segment.confidence,
                    duration=segment.duration
                )
            
        except Exception as e:
            logger.error(f"Error handling speech segment: {e}")
    
    async def register_tts_session(self, session_id: str, channel_id: str, metadata: Dict[str, Any] = None) -> bool:
        """Register a TTS session for barge-in detection."""
        try:
            success = self.barge_in_detector.register_tts_session(session_id, channel_id, metadata)
            if success:
                logger.info(f"Registered TTS session {session_id} for channel {channel_id}")
            return success
        except Exception as e:
            logger.error(f"Error registering TTS session: {e}")
            return False
    
    async def unregister_tts_session(self, session_id: str) -> bool:
        """Unregister a TTS session from barge-in detection."""
        try:
            success = self.barge_in_detector.unregister_tts_session(session_id)
            if success:
                logger.info(f"Unregistered TTS session {session_id}")
            return success
        except Exception as e:
            logger.error(f"Error unregistering TTS session: {e}")
            return False
    
    async def update_tts_volume(self, session_id: str, volume_level: float) -> bool:
        """Update TTS volume level for barge-in detection."""
        try:
            success = self.barge_in_detector.update_tts_volume(session_id, volume_level)
            return success
        except Exception as e:
            logger.error(f"Error updating TTS volume: {e}")
            return False
    
    async def _handle_transcript(self, text: str, is_final: bool, metadata: Dict[str, Any] = None):
        """Handle transcript from RTP STT handler"""
        try:
            logger.info(f"Transcript received: '{text}' (final: {is_final})")
            
            # Extract channel information
            channel_id = None
            ssrc = None
            if metadata:
                ssrc = metadata.get('ssrc')
                if ssrc:
                    channel_info = self.channel_correlation.get_channel_by_ssrc(ssrc)
                    if channel_info:
                        channel_id = channel_info.channel_id
            
            # Publish transcription using the publisher
            success = await self.transcription_publisher.publish_transcription(
                text=text,
                is_final=is_final,
                channel_id=channel_id,
                ssrc=ssrc,
                confidence=metadata.get('confidence') if metadata else None,
                language=metadata.get('language') if metadata else None,
                duration=metadata.get('duration') if metadata else None,
                metadata=metadata
            )
            
            if success:
                logger.info("Published transcription to stt:transcription:complete")
            else:
                logger.warning("Failed to publish transcription")
            
        except Exception as e:
            logger.error(f"Error handling transcript: {e}")
            # Try to publish error message
            try:
                await self.transcription_publisher.publish_error(
                    error_message=f"Error processing transcript: {str(e)}",
                    channel_id=metadata.get('channel_id') if metadata else None,
                    ssrc=metadata.get('ssrc') if metadata else None,
                    metadata={'error': str(e)}
                )
            except Exception as publish_error:
                logger.error(f"Failed to publish error message: {publish_error}")
    
    async def _handle_speech_segment_callback(self, segment: SpeechSegment):
        """Handle speech segment callback from RTP STT handler"""
        try:
            logger.debug(f"Speech segment callback: {segment.duration:.2f}s")
            # Additional processing can be added here if needed
            
        except Exception as e:
            logger.error(f"Error in speech segment callback: {e}")
    
    async def _handle_stt_error(self, error_msg: str, exception: Exception):
        """Handle STT errors"""
        try:
            logger.error(f"STT Error: {error_msg} - {exception}")
            # Get channel_id and ssrc from exception if possible, or from context
            # This part is tricky as the error source might not have this context directly.
            # For now, we'll call the fallback without specific channel info.
            # A more robust solution would involve passing context with the error.
            await self._handle_stt_fallback()
            
        except Exception as e:
            logger.error(f"Error handling STT error: {e}")

    async def _handle_stt_fallback(self, channel_id: Optional[str] = None, ssrc: Optional[int] = None):
        """Handle STT failure by publishing a fallback message."""
        logger.warning(f"STT failure for channel_id: {channel_id}, ssrc: {ssrc}. Publishing fallback message.")
        try:
            await self.transcription_publisher.publish_error(
                error_message="I didn't catch that, could you please repeat?",
                channel_id=channel_id,
                ssrc=ssrc,
                metadata={'fallback_type': 'stt_failure'}
            )
        except Exception as e:
            logger.error(f"Failed to publish STT fallback message: {e}")

    async def stop(self):
        """Stop the STT service"""
        logger.info("Stopping STT Service")
        self.running = False
        
        # Stop RTP STT handler
        if self.rtp_stt_handler:
            await self.rtp_stt_handler.stop()
        
        # Stop RTP server
        await self.rtp_manager.stop()
        
        # Stop transcription publisher
        await self.transcription_publisher.stop()
        logger.info("Transcription publisher stopped")
        
        # Stop barge-in detector
        await self.barge_in_detector.stop()
        logger.info("Barge-in detector stopped")
        
        # Stop channel correlation manager
        await self.channel_correlation.stop()
        logger.info("Channel correlation manager stopped")
        
        # Disconnect from Redis
        await self.redis_client.disconnect()

async def main():
    """Main entry point"""
    service = STTService(config)
    
    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Service failed: {e}")
        sys.exit(1)
    finally:
        await service.stop()

if __name__ == "__main__":
    asyncio.run(main())