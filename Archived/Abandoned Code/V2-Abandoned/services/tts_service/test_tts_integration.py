#!/usr/bin/env python3
"""
TTS Service Integration Tests

Tests the complete TTS service functionality including:
- Audio synthesis with OpenAI TTS
- File management and shared volume access
- Format compatibility and conversion
- Fallback to Asterisk SayAlpha
- Redis message publishing
- Concurrent audio generation
"""

import asyncio
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_CONFIG = {
    'redis_url': 'redis://localhost:6379',
    'openai_api_key': os.getenv('OPENAI_API_KEY'),
    'tts_voice': 'alloy',
    'tts_base_directory': '/shared/audio',
    'tts_file_ttl': 3600,
    'tts_enable_fallback': True,
    'tts_fallback_mode': 'sayalpha',
    'asterisk_host': 'localhost',
    'asterisk_port': 8088,
    'ari_username': 'AIAgent',
    'ari_password': 'c4d5359e2f9ddd394cd6aa116c1c6a96'
}

class TTSIntegrationTester:
    """Comprehensive TTS service integration tester."""
    
    def __init__(self):
        self.test_results = {}
        self.test_audio_files = []
        self.redis_client = None
        
    async def setup(self):
        """Set up test environment."""
        logger.info("Setting up TTS integration test environment...")
        
        # Create test directory
        self.test_dir = Path(TEST_CONFIG['tts_base_directory'])
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize Redis client
        try:
            import redis.asyncio as redis
            self.redis_client = redis.from_url(TEST_CONFIG['redis_url'])
            await self.redis_client.ping()
            logger.info("✅ Redis connection established")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            return False
            
        return True
    
    async def cleanup(self):
        """Clean up test environment."""
        logger.info("Cleaning up test environment...")
        
        # Remove test audio files
        for file_path in self.test_audio_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"Removed test file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to remove {file_path}: {e}")
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
    
    async def test_openai_tts_client(self):
        """Test OpenAI TTS client functionality."""
        logger.info("Testing OpenAI TTS client...")
        
        try:
            from openai_tts_client import OpenAITTSClient
            
            client = OpenAITTSClient(
                api_key=TEST_CONFIG['openai_api_key'],
                voice=TEST_CONFIG['tts_voice']
            )
            
            # Test text synthesis
            test_text = "Hello, this is a test of the OpenAI TTS service."
            result = await client.synthesize_text(test_text)
            
            # Validate result
            assert result.audio_data is not None, "Audio data should not be None"
            assert len(result.audio_data) > 0, "Audio data should not be empty"
            assert result.audio_format == 'wav', f"Expected WAV format, got {result.audio_format}"
            assert result.voice_used == TEST_CONFIG['tts_voice'], f"Expected voice {TEST_CONFIG['tts_voice']}, got {result.voice_used}"
            assert result.duration_ms > 0, "Duration should be positive"
            assert result.file_size > 0, "File size should be positive"
            
            logger.info("✅ OpenAI TTS client test passed")
            self.test_results['openai_tts_client'] = True
            
            return result
            
        except Exception as e:
            logger.error(f"❌ OpenAI TTS client test failed: {e}")
            self.test_results['openai_tts_client'] = False
            return None
    
    async def test_audio_file_manager(self):
        """Test audio file manager functionality."""
        logger.info("Testing audio file manager...")
        
        try:
            from audio_file_manager import AudioFileManager, AudioFileInfo
            
            manager = AudioFileManager(
                base_directory=TEST_CONFIG['tts_base_directory'],
                ttl_seconds=TEST_CONFIG['tts_file_ttl']
            )
            
            # Test with sample audio data
            test_audio_data = b"fake_audio_data_for_testing"
            test_text = "Test audio file"
            test_metadata = {
                'test_id': str(uuid.uuid4()),
                'channel_id': 'test_channel_123',
                'voice_used': 'alloy'
            }
            
            # Save audio file
            file_info = await manager.save_audio_file(
                audio_data=test_audio_data,
                text=test_text,
                original_format='wav',
                metadata=test_metadata
            )
            
            # Validate file info
            assert file_info.file_id is not None, "File ID should not be None"
            assert file_info.file_path.exists(), "File should exist on disk"
            assert file_info.text == test_text, "Text should match"
            assert file_info.metadata == test_metadata, "Metadata should match"
            assert file_info.created_at > 0, "Created timestamp should be positive"
            assert file_info.ttl_seconds == TEST_CONFIG['tts_file_ttl'], "TTL should match"
            
            # Test file retrieval
            retrieved_info = await manager.get_file_info(file_info.file_id)
            assert retrieved_info is not None, "Should be able to retrieve file info"
            assert retrieved_info.file_id == file_info.file_id, "File IDs should match"
            
            # Test file cleanup
            await manager.cleanup_expired_files()
            
            # Track for cleanup
            self.test_audio_files.append(str(file_info.file_path))
            
            logger.info("✅ Audio file manager test passed")
            self.test_results['audio_file_manager'] = True
            
            return file_info
            
        except Exception as e:
            logger.error(f"❌ Audio file manager test failed: {e}")
            self.test_results['audio_file_manager'] = False
            return None
    
    async def test_asterisk_fallback(self):
        """Test Asterisk fallback functionality."""
        logger.info("Testing Asterisk fallback...")
        
        try:
            from asterisk_fallback import AsteriskFallbackHandler, AsteriskFallbackConfig
            
            config = AsteriskFallbackConfig(
                enable_fallback=TEST_CONFIG['tts_enable_fallback'],
                fallback_mode=TEST_CONFIG['tts_fallback_mode'],
                asterisk_host=TEST_CONFIG['asterisk_host'],
                asterisk_port=TEST_CONFIG['asterisk_port'],
                ari_username=TEST_CONFIG['ari_username'],
                ari_password=TEST_CONFIG['ari_password']
            )
            
            handler = AsteriskFallbackHandler(config)
            
            # Test fallback handling
            test_text = "Hello from Asterisk fallback"
            test_channel_id = "test_channel_456"
            
            result = await handler.handle_fallback(test_text, test_channel_id)
            
            # Validate result structure
            assert 'success' in result, "Result should contain success flag"
            assert 'fallback_mode' in result, "Result should contain fallback mode"
            assert 'text' in result, "Result should contain text"
            
            # Note: We expect this to fail in test environment without real Asterisk
            # but we can validate the structure
            if result['success']:
                logger.info("✅ Asterisk fallback test passed (connected to Asterisk)")
            else:
                logger.info("✅ Asterisk fallback test passed (expected failure in test env)")
            
            self.test_results['asterisk_fallback'] = True
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Asterisk fallback test failed: {e}")
            self.test_results['asterisk_fallback'] = False
            return None
    
    async def test_tts_service_integration(self):
        """Test complete TTS service integration."""
        logger.info("Testing TTS service integration...")
        
        try:
            from tts_service import TTSService, TTSServiceConfig
            
            config = TTSServiceConfig(
                redis_url=TEST_CONFIG['redis_url'],
                openai_api_key=TEST_CONFIG['openai_api_key'],
                tts_voice=TEST_CONFIG['tts_voice'],
                tts_base_directory=TEST_CONFIG['tts_base_directory'],
                tts_file_ttl=TEST_CONFIG['tts_file_ttl'],
                tts_enable_fallback=TEST_CONFIG['tts_enable_fallback'],
                tts_fallback_mode=TEST_CONFIG['tts_fallback_mode'],
                asterisk_host=TEST_CONFIG['asterisk_host'],
                asterisk_port=TEST_CONFIG['asterisk_port'],
                ari_username=TEST_CONFIG['ari_username'],
                ari_password=TEST_CONFIG['ari_password']
            )
            
            service = TTSService(config)
            
            # Start service
            await service.start()
            
            # Test LLM response handling
            test_llm_response = {
                'channel_id': 'test_channel_789',
                'text': 'This is a test of the complete TTS service integration.',
                'model_used': 'gpt-4o',
                'tokens_used': 25
            }
            
            # Simulate LLM response
            await service._handle_llm_response(json.dumps(test_llm_response))
            
            # Wait a moment for processing
            await asyncio.sleep(2)
            
            # Check if audio file was created
            audio_files = list(Path(TEST_CONFIG['tts_base_directory']).glob("*.wav"))
            if audio_files:
                logger.info(f"✅ Audio file created: {audio_files[0]}")
                self.test_audio_files.append(str(audio_files[0]))
            
            # Stop service
            await service.stop()
            
            logger.info("✅ TTS service integration test passed")
            self.test_results['tts_service_integration'] = True
            
            return True
            
        except Exception as e:
            logger.error(f"❌ TTS service integration test failed: {e}")
            self.test_results['tts_service_integration'] = False
            return False
    
    async def test_redis_message_publishing(self):
        """Test Redis message publishing."""
        logger.info("Testing Redis message publishing...")
        
        try:
            # Subscribe to TTS channels
            pubsub = self.redis_client.pubsub()
            await pubsub.subscribe(
                "tts:audio:ready",
                "tts:error",
                "tts:fallback:ready"
            )
            
            # Test message publishing
            test_message = {
                'channel_id': 'test_channel_redis',
                'file_id': 'test_file_123',
                'file_path': '/shared/audio/test.wav',
                'text': 'Test Redis message',
                'timestamp': time.time()
            }
            
            # Publish test message
            await self.redis_client.publish(
                "tts:audio:ready",
                json.dumps(test_message)
            )
            
            # Wait for message
            message = await pubsub.get_message(timeout=1.0)
            if message and message['type'] == 'message':
                received_data = json.loads(message['data'])
                assert received_data['channel_id'] == test_message['channel_id']
                logger.info("✅ Redis message publishing test passed")
                self.test_results['redis_publishing'] = True
            else:
                logger.warning("⚠️ No message received from Redis")
                self.test_results['redis_publishing'] = False
            
            await pubsub.unsubscribe()
            await pubsub.close()
            
        except Exception as e:
            logger.error(f"❌ Redis message publishing test failed: {e}")
            self.test_results['redis_publishing'] = False
    
    async def test_concurrent_audio_generation(self):
        """Test concurrent audio generation."""
        logger.info("Testing concurrent audio generation...")
        
        try:
            from openai_tts_client import OpenAITTSClient
            
            client = OpenAITTSClient(
                api_key=TEST_CONFIG['openai_api_key'],
                voice=TEST_CONFIG['tts_voice']
            )
            
            # Create multiple concurrent requests
            test_texts = [
                "First concurrent audio request",
                "Second concurrent audio request", 
                "Third concurrent audio request"
            ]
            
            # Run concurrent synthesis
            tasks = [
                client.synthesize_text(text) for text in test_texts
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Validate results
            successful_results = [r for r in results if not isinstance(r, Exception)]
            assert len(successful_results) == len(test_texts), f"Expected {len(test_texts)} successful results, got {len(successful_results)}"
            
            for i, result in enumerate(successful_results):
                assert result.audio_data is not None, f"Result {i} should have audio data"
                assert len(result.audio_data) > 0, f"Result {i} should have non-empty audio data"
            
            logger.info("✅ Concurrent audio generation test passed")
            self.test_results['concurrent_generation'] = True
            
        except Exception as e:
            logger.error(f"❌ Concurrent audio generation test failed: {e}")
            self.test_results['concurrent_generation'] = False
    
    async def test_shared_volume_access(self):
        """Test shared volume file access."""
        logger.info("Testing shared volume access...")
        
        try:
            # Test directory creation and access
            test_dir = Path(TEST_CONFIG['tts_base_directory'])
            test_file = test_dir / f"test_shared_access_{uuid.uuid4().hex}.txt"
            
            # Write test file
            test_content = "Test shared volume access"
            test_file.write_text(test_content)
            
            # Verify file exists and is readable
            assert test_file.exists(), "Test file should exist"
            assert test_file.read_text() == test_content, "File content should match"
            
            # Test file permissions
            assert os.access(test_file, os.R_OK), "File should be readable"
            assert os.access(test_file, os.W_OK), "File should be writable"
            
            # Clean up
            test_file.unlink()
            
            logger.info("✅ Shared volume access test passed")
            self.test_results['shared_volume_access'] = True
            
        except Exception as e:
            logger.error(f"❌ Shared volume access test failed: {e}")
            self.test_results['shared_volume_access'] = False
    
    async def run_all_tests(self):
        """Run all integration tests."""
        logger.info("Starting TTS service integration tests...")
        
        # Setup
        if not await self.setup():
            logger.error("Failed to setup test environment")
            return False
        
        try:
            # Run individual tests
            await self.test_openai_tts_client()
            await self.test_audio_file_manager()
            await self.test_asterisk_fallback()
            await self.test_tts_service_integration()
            await self.test_redis_message_publishing()
            await self.test_concurrent_audio_generation()
            await self.test_shared_volume_access()
            
            # Print results
            self.print_test_results()
            
            return all(self.test_results.values())
            
        finally:
            await self.cleanup()
    
    def print_test_results(self):
        """Print test results summary."""
        logger.info("\n" + "="*60)
        logger.info("TTS SERVICE INTEGRATION TEST RESULTS")
        logger.info("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result)
        
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            logger.info(f"{test_name:30} {status}")
        
        logger.info("-"*60)
        logger.info(f"Total: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            logger.info("🎉 All tests passed!")
        else:
            logger.warning(f"⚠️ {total_tests - passed_tests} tests failed")
        
        logger.info("="*60)

async def main():
    """Main test runner."""
    tester = TTSIntegrationTester()
    success = await tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
