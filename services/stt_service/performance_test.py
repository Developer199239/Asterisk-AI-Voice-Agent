#!/usr/bin/env python3
"""
STT Service Performance Test

This script tests the performance characteristics of the STT service components.
"""

import asyncio
import logging
import time
import statistics
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from config import CallControllerConfig
from redis_client import RedisMessageQueue
from channel_correlation import ChannelCorrelationManager
from transcription_publisher import TranscriptionPublisher
from barge_in_detector import BargeInDetector, BargeInConfig
from rtp_stt_handler import RTPSTTHandler, RTPSTTConfig
from realtime_client import RealtimeClient, RealtimeConfig

# Configure logging
logging.basicConfig(level=logging.WARNING)  # Reduce log noise
logger = logging.getLogger(__name__)


class PerformanceTest:
    """Performance testing for STT service components."""
    
    def __init__(self):
        self.config = CallControllerConfig()
        self.results = {}
    
    async def test_channel_correlation_performance(self, num_channels: int = 1000):
        """Test channel correlation performance."""
        logger.info(f"Testing channel correlation with {num_channels} channels...")
        
        correlation_manager = ChannelCorrelationManager()
        await correlation_manager.start()
        
        start_time = time.time()
        
        # Register channels
        for i in range(num_channels):
            channel_id = f"channel_{i}"
            ssrc = 1000 + i
            correlation_manager.register_channel(channel_id)
            correlation_manager.correlate_ssrc(ssrc, channel_id)
        
        register_time = time.time() - start_time
        
        # Test lookups
        start_time = time.time()
        for i in range(num_channels):
            ssrc = 1000 + i
            correlation_manager.get_channel_by_ssrc(ssrc)
        
        lookup_time = time.time() - start_time
        
        # Test activity updates
        start_time = time.time()
        for i in range(num_channels):
            channel_id = f"channel_{i}"
            correlation_manager.update_channel_activity(
                channel_id, 
                activity_type="rtp_packet",
                bytes=160
            )
        
        update_time = time.time() - start_time
        
        await correlation_manager.stop()
        
        self.results['channel_correlation'] = {
            'num_channels': num_channels,
            'register_time': register_time,
            'lookup_time': lookup_time,
            'update_time': update_time,
            'registers_per_second': num_channels / register_time,
            'lookups_per_second': num_channels / lookup_time,
            'updates_per_second': num_channels / update_time
        }
        
        logger.info(f"Channel correlation: {num_channels/register_time:.0f} registers/sec, "
                   f"{num_channels/lookup_time:.0f} lookups/sec, "
                   f"{num_channels/update_time:.0f} updates/sec")
    
    async def test_transcription_publisher_performance(self, num_messages: int = 1000):
        """Test transcription publisher performance."""
        logger.info(f"Testing transcription publisher with {num_messages} messages...")
        
        # Mock Redis client
        redis_client = type('MockRedis', (), {
            'publish': lambda self, channel, message: None
        })()
        
        publisher = TranscriptionPublisher(redis_client)
        await publisher.start()
        
        start_time = time.time()
        
        # Publish messages
        for i in range(num_messages):
            await publisher.publish_transcription(
                text=f"Test message {i}",
                is_final=True,
                channel_id=f"channel_{i % 100}",
                ssrc=1000 + (i % 100)
            )
        
        publish_time = time.time() - start_time
        
        # Wait for processing
        await asyncio.sleep(1.0)
        
        await publisher.stop()
        
        self.results['transcription_publisher'] = {
            'num_messages': num_messages,
            'publish_time': publish_time,
            'messages_per_second': num_messages / publish_time
        }
        
        logger.info(f"Transcription publisher: {num_messages/publish_time:.0f} messages/sec")
    
    async def test_barge_in_detector_performance(self, num_sessions: int = 100):
        """Test barge-in detector performance."""
        logger.info(f"Testing barge-in detector with {num_sessions} sessions...")
        
        # Mock Redis client
        redis_client = type('MockRedis', (), {
            'publish': lambda self, channel, message: None
        })()
        
        detector = BargeInDetector(BargeInConfig(), redis_client)
        await detector.start()
        
        start_time = time.time()
        
        # Register TTS sessions
        for i in range(num_sessions):
            session_id = f"session_{i}"
            channel_id = f"channel_{i}"
            detector.register_tts_session(session_id, channel_id)
        
        register_time = time.time() - start_time
        
        # Test speech detection
        start_time = time.time()
        for i in range(num_sessions * 10):  # 10 detections per session
            channel_id = f"channel_{i % num_sessions}"
            detector.process_speech_detection(
                channel_id=channel_id,
                ssrc=1000 + (i % num_sessions),
                confidence=0.8,
                duration=0.5
            )
        
        detection_time = time.time() - start_time
        
        await detector.stop()
        
        self.results['barge_in_detector'] = {
            'num_sessions': num_sessions,
            'register_time': register_time,
            'detection_time': detection_time,
            'sessions_per_second': num_sessions / register_time,
            'detections_per_second': (num_sessions * 10) / detection_time
        }
        
        logger.info(f"Barge-in detector: {num_sessions/register_time:.0f} sessions/sec, "
                   f"{(num_sessions * 10)/detection_time:.0f} detections/sec")
    
    async def test_audio_buffer_performance(self, num_chunks: int = 1000):
        """Test audio buffer performance."""
        logger.info(f"Testing audio buffer with {num_chunks} chunks...")
        
        from audio_buffer import AudioBufferManager, BufferConfig
        
        buffer_config = BufferConfig(
            max_duration_seconds=3.0,
            chunk_duration_seconds=1.0,
            sample_rate=8000,
            channels=1,
            bit_depth=16
        )
        
        buffer_manager = AudioBufferManager(buffer_config)
        buffer = buffer_manager.create_buffer("test_buffer")
        
        # Test audio data
        audio_data = b'\x00' * 160  # 20ms of 8kHz audio
        
        start_time = time.time()
        
        # Add audio chunks
        for i in range(num_chunks):
            buffer.add_audio(audio_data, time.time())
        
        add_time = time.time() - start_time
        
        # Test buffer status
        start_time = time.time()
        for i in range(100):
            buffer.get_status()
        
        status_time = time.time() - start_time
        
        self.results['audio_buffer'] = {
            'num_chunks': num_chunks,
            'add_time': add_time,
            'status_time': status_time,
            'chunks_per_second': num_chunks / add_time,
            'status_checks_per_second': 100 / status_time
        }
        
        logger.info(f"Audio buffer: {num_chunks/add_time:.0f} chunks/sec, "
                   f"{100/status_time:.0f} status checks/sec")
    
    def print_results(self):
        """Print performance test results."""
        print("\n" + "="*60)
        print("STT Service Performance Test Results")
        print("="*60)
        
        for component, results in self.results.items():
            print(f"\n{component.replace('_', ' ').title()}:")
            for key, value in results.items():
                if isinstance(value, float):
                    print(f"  {key}: {value:.2f}")
                else:
                    print(f"  {key}: {value}")
        
        print("\n" + "="*60)


async def main():
    """Main performance test runner."""
    logger.info("Starting STT Service Performance Tests...")
    
    test = PerformanceTest()
    
    # Run performance tests
    await test.test_channel_correlation_performance(1000)
    await test.test_transcription_publisher_performance(1000)
    await test.test_barge_in_detector_performance(100)
    await test.test_audio_buffer_performance(1000)
    
    # Print results
    test.print_results()
    
    logger.info("Performance tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
