"""
STT Service - Main Entry Point

This service handles speech-to-text processing.
It adapts the existing stt_handler.py from the v1.0 architecture.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from config import CallControllerConfig
from redis_client import RedisMessageQueue
from rtp_handler import RTPStreamManager, RTPStreamInfo
from vad_handler import SpeechSegment

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
        self.rtp_manager = RTPStreamManager(host="0.0.0.0", port=5004)
        self.running = False
        self.active_streams = {}  # Track active RTP streams

    async def start(self):
        """Start the STT service"""
        logger.info("Starting STT Service - v2.0")
        
        try:
            # Connect to Redis
            await self.redis_client.connect()
            logger.info("Connected to Redis")
            
            # Subscribe to new call events
            await self.redis_client.subscribe(["calls:new"], self._handle_new_call)
            logger.info("Subscribed to calls:new")
            
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
            
            # Track the new call
            self.active_streams[channel_id] = {
                'start_time': asyncio.get_event_loop().time(),
                'status': 'waiting_for_rtp'
            }
            
            logger.info(f"Tracking new call for channel {channel_id}")
            
        except Exception as e:
            logger.error(f"Error handling new call: {e}")

    async def _handle_rtp_audio_data(self, audio_data: bytes, stream_info: RTPStreamInfo):
        """Handle RTP audio data from streams"""
        try:
            logger.debug(f"Received audio data from SSRC {stream_info.ssrc}: {len(audio_data)} bytes")
            
            # TODO: Process audio data with VAD
            # TODO: Perform speech-to-text conversion
            # TODO: Publish transcription to stt:transcription:complete
            
            # For now, just log the audio data
            logger.info(f"Processing audio: SSRC={stream_info.ssrc}, "
                       f"packets={stream_info.packet_count}, "
                       f"bytes={stream_info.bytes_received}")
            
        except Exception as e:
            logger.error(f"Error handling RTP audio data: {e}")
    
    async def _handle_speech_segment(self, segment: SpeechSegment, stream_info: RTPStreamInfo):
        """Handle detected speech segment"""
        try:
            logger.info(f"Speech segment detected: {segment.duration:.2f}s, {len(segment.audio_data)} bytes from SSRC {stream_info.ssrc}")
            
            # TODO: Process speech segment for transcription
            # TODO: Publish transcription to stt:transcription:complete
            
            # For now, just log the segment
            logger.debug(f"Speech segment: start={segment.start_time:.2f}, end={segment.end_time:.2f}, confidence={segment.confidence:.2f}")
            
        except Exception as e:
            logger.error(f"Error handling speech segment: {e}")

    async def stop(self):
        """Stop the STT service"""
        logger.info("Stopping STT Service")
        self.running = False
        
        # Stop RTP server
        await self.rtp_manager.stop()
        
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