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

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from config import CallControllerConfig
from redis_client import RedisMessageQueue
from rtp_handler import RTPStreamManager, RTPStreamInfo
from vad_handler import SpeechSegment
from rtp_stt_handler import RTPSTTHandler, RTPSTTConfig
from channel_correlation import ChannelCorrelationManager
from realtime_client import RealtimeClient, RealtimeConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class STTService:
    def __init__(self):
        self.config = CallControllerConfig()
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
            voice=VoiceType.ALLOY,
            model="gpt-4o-realtime-preview-2024-10-01"
        )
        self.realtime_client = RealtimeClient(self.realtime_config)
        
        # Initialize RTP STT handler
        self.rtp_stt_handler = RTPSTTHandler(self.rtp_stt_config, self.realtime_client)

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
            
            # Start RTP UDP server with VAD support
            rtp_started = await self.rtp_manager.start(
                on_audio_data=self._handle_rtp_audio_data,
                on_speech_segment=self._handle_speech_segment
            )
            if not rtp_started:
                raise Exception("Failed to start RTP UDP server")
            logger.info("RTP UDP server started on port 5004 with VAD")
            
            self.running = True
            
            # Start listening for messages
            await self.redis_client.start_listening()
            
            # Main service loop
            while self.running:
                try:
                    await asyncio.sleep(1)
                except KeyboardInterrupt:
                    break
                    
        except Exception as e:
            logger.error(f"Failed to start STT service: {e}")
            raise

    async def _handle_new_call(self, channel: str, message: dict):
        """Handle new call events"""
        try:
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
            
        except Exception as e:
            logger.error(f"Error handling speech segment: {e}")
    
    async def _handle_transcript(self, text: str, is_final: bool, metadata: Dict[str, Any] = None):
        """Handle transcript from RTP STT handler"""
        try:
            logger.info(f"Transcript received: '{text}' (final: {is_final})")
            
            # Update channel correlation for transcript activity
            if metadata and 'ssrc' in metadata:
                ssrc = metadata['ssrc']
                channel_info = self.channel_correlation.get_channel_by_ssrc(ssrc)
                if channel_info:
                    self.channel_correlation.update_channel_activity(
                        channel_info.channel_id,
                        activity_type="transcript",
                        transcript_text=text,
                        is_final=is_final
                    )
            
            # Publish transcription to Redis
            message = {
                'text': text,
                'is_final': is_final,
                'timestamp': time.time(),
                'metadata': metadata or {}
            }
            
            await self.redis_client.publish("stt:transcription:complete", message)
            logger.info("Published transcription to stt:transcription:complete")
            
        except Exception as e:
            logger.error(f"Error handling transcript: {e}")
    
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
            # Additional error handling can be added here
            
        except Exception as e:
            logger.error(f"Error handling STT error: {e}")

    async def stop(self):
        """Stop the STT service"""
        logger.info("Stopping STT Service")
        self.running = False
        
        # Stop RTP STT handler
        if self.rtp_stt_handler:
            await self.rtp_stt_handler.stop()
        
        # Stop RTP server
        await self.rtp_manager.stop()
        
        # Stop channel correlation manager
        await self.channel_correlation.stop()
        logger.info("Channel correlation manager stopped")
        
        # Disconnect from Redis
        await self.redis_client.disconnect()

async def main():
    """Main entry point"""
    service = STTService()
    
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