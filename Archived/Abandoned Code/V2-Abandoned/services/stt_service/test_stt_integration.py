"""
STT Service Integration Tests

This module provides comprehensive testing of the complete RTP-to-transcription pipeline
with integration validation.
"""

import asyncio
import json
import logging
import socket
import struct
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any

# Add shared modules to path
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from config import CallControllerConfig
from redis_client import RedisMessageQueue
from rtp_handler import RTPPacket, RTPPayloadType, RTPStreamInfo
from vad_handler import SpeechSegment
from rtp_stt_handler import RTPSTTHandler, RTPSTTConfig
from channel_correlation import ChannelCorrelationManager
from transcription_publisher import TranscriptionPublisher, TranscriptionMessage
from barge_in_detector import BargeInDetector, BargeInConfig, BargeInEvent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockRTPPacket:
    """Mock RTP packet for testing."""
    
    def __init__(self, ssrc: int, payload_type: int, sequence_number: int, 
                 timestamp: int, payload: bytes):
        self.version = 2
        self.padding = False
        self.extension = False
        self.csrc_count = 0
        self.marker = False
        self.payload_type = payload_type
        self.sequence_number = sequence_number
        self.timestamp = timestamp
        self.ssrc = ssrc
        self.payload = payload
        self.csrc_list = []
        self.extension_header = None
    
    def get_audio_samples(self, sample_rate: int) -> bytes:
        """Convert payload to audio samples."""
        if self.payload_type == RTPPayloadType.PCMU.value:
            # Convert μ-law to linear PCM
            import audioop
            return audioop.ulaw2lin(self.payload, 2)
        elif self.payload_type == RTPPayloadType.PCMA.value:
            # Convert A-law to linear PCM
            import audioop
            return audioop.alaw2lin(self.payload, 2)
        else:
            # Return as-is for other codecs
            return self.payload


class STTIntegrationTest(unittest.TestCase):
    """Integration tests for STT service components."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = CallControllerConfig()
        self.redis_client = AsyncMock(spec=RedisMessageQueue)
        self.channel_correlation = ChannelCorrelationManager()
        self.transcription_publisher = TranscriptionPublisher(self.redis_client, self.channel_correlation)
        self.barge_in_detector = BargeInDetector(BargeInConfig(), self.redis_client, self.channel_correlation)
        
        # Mock OpenAI client
        self.mock_realtime_client = AsyncMock()
        self.mock_realtime_client.connect.return_value = True
        self.mock_realtime_client.disconnect.return_value = True
        self.mock_realtime_client.create_stream.return_value = "mock_stream_id"
        self.mock_realtime_client.send_audio_chunk.return_value = True
        self.mock_realtime_client.close_stream.return_value = True
        
        # Initialize RTP STT handler
        self.rtp_stt_config = RTPSTTConfig(
            rtp_sample_rate=8000,
            target_sample_rate=24000,
            enable_audio_resampling=True,
            on_transcript=self._mock_transcript_callback,
            on_speech_segment=self._mock_speech_segment_callback,
            on_error=self._mock_error_callback
        )
        self.rtp_stt_handler = RTPSTTHandler(self.rtp_stt_config, self.mock_realtime_client)
        
        # Test data
        self.test_ssrc = 12345
        self.test_channel_id = "test_channel_123"
        self.test_audio_data = b'\x00' * 160  # 20ms of 8kHz audio
        
        # Callback tracking
        self.transcript_callbacks = []
        self.speech_segment_callbacks = []
        self.error_callbacks = []
    
    def _mock_transcript_callback(self, text: str, is_final: bool, metadata: Dict[str, Any] = None):
        """Mock transcript callback."""
        self.transcript_callbacks.append({
            'text': text,
            'is_final': is_final,
            'metadata': metadata or {}
        })
    
    def _mock_speech_segment_callback(self, segment: SpeechSegment):
        """Mock speech segment callback."""
        self.speech_segment_callbacks.append(segment)
    
    def _mock_error_callback(self, error_msg: str, exception: Exception):
        """Mock error callback."""
        self.error_callbacks.append({
            'error_msg': error_msg,
            'exception': exception
        })
    
    async def test_channel_correlation(self):
        """Test channel correlation functionality."""
        # Register a channel
        channel_info = self.channel_correlation.register_channel(
            self.test_channel_id, 
            {'test': 'data'}
        )
        self.assertIsNotNone(channel_info)
        self.assertEqual(channel_info.channel_id, self.test_channel_id)
        
        # Correlate SSRC
        success = self.channel_correlation.correlate_ssrc(self.test_ssrc, self.test_channel_id)
        self.assertTrue(success)
        
        # Verify correlation
        retrieved_channel = self.channel_correlation.get_channel_by_ssrc(self.test_ssrc)
        self.assertIsNotNone(retrieved_channel)
        self.assertEqual(retrieved_channel.channel_id, self.test_channel_id)
        
        # Update activity
        self.channel_correlation.update_channel_activity(
            self.test_channel_id,
            activity_type="rtp_packet",
            bytes=160
        )
        
        # Verify stats
        stats = self.channel_correlation.get_channel_stats()
        self.assertEqual(stats['total_channels'], 1)
        self.assertEqual(stats['total_packets'], 1)
    
    async def test_rtp_packet_parsing(self):
        """Test RTP packet parsing and audio extraction."""
        # Create test RTP packet
        rtp_packet = MockRTPPacket(
            ssrc=self.test_ssrc,
            payload_type=RTPPayloadType.PCMU.value,
            sequence_number=100,
            timestamp=1234567890,
            payload=b'\x00' * 160
        )
        
        # Test audio sample extraction
        audio_samples = rtp_packet.get_audio_samples(8000)
        self.assertIsInstance(audio_samples, bytes)
        self.assertGreater(len(audio_samples), 0)
    
    async def test_transcription_publisher(self):
        """Test transcription publisher functionality."""
        # Start publisher
        await self.transcription_publisher.start()
        
        # Publish transcription
        success = await self.transcription_publisher.publish_transcription(
            text="Hello world",
            is_final=True,
            channel_id=self.test_channel_id,
            ssrc=self.test_ssrc,
            confidence=0.95
        )
        self.assertTrue(success)
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Verify Redis publish was called
        self.redis_client.publish.assert_called()
        
        # Stop publisher
        await self.transcription_publisher.stop()
    
    async def test_barge_in_detection(self):
        """Test barge-in detection functionality."""
        # Start detector
        await self.barge_in_detector.start()
        
        # Register TTS session
        session_id = "tts_session_123"
        success = self.barge_in_detector.register_tts_session(
            session_id, 
            self.test_channel_id,
            {'volume': 0.8}
        )
        self.assertTrue(success)
        
        # Process speech detection (should trigger barge-in)
        success = self.barge_in_detector.process_speech_detection(
            channel_id=self.test_channel_id,
            ssrc=self.test_ssrc,
            confidence=0.8,
            duration=0.5
        )
        self.assertTrue(success)
        
        # Wait for debounce
        await asyncio.sleep(0.3)
        
        # Verify barge-in event was published
        self.redis_client.publish.assert_called()
        
        # Unregister session
        success = self.barge_in_detector.unregister_tts_session(session_id)
        self.assertTrue(success)
        
        # Stop detector
        await self.barge_in_detector.stop()
    
    async def test_rtp_stt_handler_integration(self):
        """Test RTP STT handler integration."""
        # Start handler
        success = await self.rtp_stt_handler.start()
        self.assertTrue(success)
        
        # Process RTP audio
        stream_info = {
            'ssrc': self.test_ssrc,
            'payload_type': RTPPayloadType.PCMU.value,
            'sample_rate': 8000,
            'channels': 1,
            'packet_count': 1,
            'bytes_received': 160
        }
        
        success = await self.rtp_stt_handler.process_rtp_audio(
            self.test_audio_data, 
            stream_info
        )
        self.assertTrue(success)
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Verify OpenAI client was called
        self.mock_realtime_client.send_audio_chunk.assert_called()
        
        # Stop handler
        await self.rtp_stt_handler.stop()
    
    async def test_end_to_end_pipeline(self):
        """Test complete end-to-end pipeline."""
        # Start all components
        await self.channel_correlation.start()
        await self.transcription_publisher.start()
        await self.barge_in_detector.start()
        
        # Register channel
        self.channel_correlation.register_channel(self.test_channel_id)
        self.channel_correlation.correlate_ssrc(self.test_ssrc, self.test_channel_id)
        
        # Register TTS session
        self.barge_in_detector.register_tts_session("tts_123", self.test_channel_id)
        
        # Start RTP STT handler
        await self.rtp_stt_handler.start()
        
        # Process multiple RTP packets
        for i in range(5):
            stream_info = {
                'ssrc': self.test_ssrc,
                'payload_type': RTPPayloadType.PCMU.value,
                'sample_rate': 8000,
                'channels': 1,
                'packet_count': i + 1,
                'bytes_received': 160
            }
            
            success = await self.rtp_stt_handler.process_rtp_audio(
                self.test_audio_data, 
                stream_info
            )
            self.assertTrue(success)
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Verify all components processed the data
        self.mock_realtime_client.send_audio_chunk.assert_called()
        self.redis_client.publish.assert_called()
        
        # Check channel correlation stats
        stats = self.channel_correlation.get_channel_stats()
        self.assertGreater(stats['total_packets'], 0)
        
        # Check barge-in detector stats
        barge_stats = self.barge_in_detector.get_stats()
        self.assertGreater(barge_stats['tts_sessions_tracked'], 0)
        
        # Stop all components
        await self.rtp_stt_handler.stop()
        await self.barge_in_detector.stop()
        await self.transcription_publisher.stop()
        await self.channel_correlation.stop()
    
    def test_audio_format_conversion(self):
        """Test audio format conversion utilities."""
        from audio_buffer import AudioFormatConverter
        
        # Test μ-law to linear conversion
        test_audio = b'\x00' * 160
        converted, sample_rate = AudioFormatConverter.convert_to_whisper_format(
            test_audio,
            source_sample_rate=8000,
            target_sample_rate=24000,
            source_channels=1,
            target_channels=1,
            source_bit_depth=16,
            target_bit_depth=16
        )
        
        self.assertIsInstance(converted, bytes)
        self.assertEqual(sample_rate, 24000)
        self.assertGreater(len(converted), 0)
    
    def test_vad_integration(self):
        """Test VAD integration with audio processing."""
        from vad_handler import VADHandler
        
        # Create VAD handler
        vad = VADHandler(
            sample_rate=8000,
            frame_duration_ms=20,
            vad_mode=3
        )
        
        # Process test audio
        test_audio = b'\x00' * 320  # 20ms of 8kHz 16-bit audio
        segments = vad.process_audio(test_audio)
        
        self.assertIsInstance(segments, list)
        # Note: With silence audio, we might not get speech segments
    
    async def test_error_handling(self):
        """Test error handling throughout the pipeline."""
        # Test Redis connection failure
        self.redis_client.publish.side_effect = Exception("Redis connection failed")
        
        # Start transcription publisher
        await self.transcription_publisher.start()
        
        # Try to publish transcription
        success = await self.transcription_publisher.publish_transcription(
            text="Test",
            is_final=True,
            channel_id=self.test_channel_id
        )
        # Should still return True (queued for retry)
        self.assertTrue(success)
        
        # Wait for retry attempts
        await asyncio.sleep(1.0)
        
        # Stop publisher
        await self.transcription_publisher.stop()
    
    def test_performance_metrics(self):
        """Test performance metrics and statistics."""
        # Test channel correlation stats
        stats = self.channel_correlation.get_channel_stats()
        self.assertIn('total_channels', stats)
        self.assertIn('total_packets', stats)
        self.assertIn('total_bytes', stats)
        
        # Test transcription publisher stats
        pub_stats = self.transcription_publisher.get_stats()
        self.assertIn('messages_published', pub_stats)
        self.assertIn('messages_failed', pub_stats)
        self.assertIn('queue_size', pub_stats)
        
        # Test barge-in detector stats
        barge_stats = self.barge_in_detector.get_stats()
        self.assertIn('barge_in_events', barge_stats)
        self.assertIn('active_tts_sessions', barge_stats)
        self.assertIn('monitored_channels', barge_stats)


class MockUDPServer:
    """Mock UDP server for testing RTP packet reception."""
    
    def __init__(self, port: int = 5004):
        self.port = port
        self.socket = None
        self.running = False
        self.received_packets = []
    
    async def start(self):
        """Start the mock UDP server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('0.0.0.0', self.port))
        self.socket.setblocking(False)
        self.running = True
        
        # Start receiving loop
        asyncio.create_task(self._receive_loop())
    
    async def stop(self):
        """Stop the mock UDP server."""
        self.running = False
        if self.socket:
            self.socket.close()
    
    async def _receive_loop(self):
        """Receive loop for UDP packets."""
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                data, addr = await loop.sock_recvfrom(self.socket, 1024)
                self.received_packets.append((data, addr))
            except BlockingIOError:
                await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"Error receiving UDP packet: {e}")
                break
    
    def send_test_rtp_packet(self, ssrc: int, payload_type: int, payload: bytes):
        """Send a test RTP packet to the server."""
        # Create RTP header
        header = struct.pack('!BBHII',
            0x80,  # Version=2, Padding=0, Extension=0, CSRC=0
            payload_type,  # Payload type
            100,  # Sequence number
            int(time.time() * 1000),  # Timestamp
            ssrc  # SSRC
        )
        
        packet = header + payload
        
        # Send to local server
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(packet, ('127.0.0.1', self.port))
        sock.close()


async def run_integration_tests():
    """Run all integration tests."""
    print("Starting STT Service Integration Tests...")
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test cases
    test_cases = [
        STTIntegrationTest('test_channel_correlation'),
        STTIntegrationTest('test_rtp_packet_parsing'),
        STTIntegrationTest('test_transcription_publisher'),
        STTIntegrationTest('test_barge_in_detection'),
        STTIntegrationTest('test_rtp_stt_handler_integration'),
        STTIntegrationTest('test_end_to_end_pipeline'),
        STTIntegrationTest('test_audio_format_conversion'),
        STTIntegrationTest('test_vad_integration'),
        STTIntegrationTest('test_error_handling'),
        STTIntegrationTest('test_performance_metrics'),
    ]
    
    for test_case in test_cases:
        suite.addTest(test_case)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print results
    print(f"\nTest Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"  {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"  {test}: {traceback}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    # Run integration tests
    success = asyncio.run(run_integration_tests())
    exit(0 if success else 1)
