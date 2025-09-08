"""
LLM Service Integration Tests

This module provides comprehensive integration tests for the LLM service,
testing conversation context persistence, channel isolation, and concurrent call handling.
"""

import asyncio
import json
import logging
import pytest
import time
from typing import Dict, List, Any
from unittest.mock import AsyncMock, MagicMock, patch

from conversation_manager import ConversationManager, ConversationConfig, ConversationState
from openai_client import OpenAIClient, LLMConfig as OpenAIConfig, ModelType
from llm_service import LLMService, LLMServiceConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestLLMServiceIntegration:
    """Integration tests for the LLM service."""
    
    @pytest.fixture
    async def mock_redis(self):
        """Mock Redis client for testing."""
        redis_mock = AsyncMock()
        redis_mock.ping.return_value = True
        redis_mock.pubsub.return_value = AsyncMock()
        redis_mock.publish.return_value = 1
        return redis_mock
    
    @pytest.fixture
    async def mock_openai_client(self):
        """Mock OpenAI client for testing."""
        client_mock = AsyncMock()
        client_mock.test_connection.return_value = True
        client_mock.generate_response.return_value = MagicMock(
            content="Test response",
            model_used="gpt-4o",
            tokens_used=10,
            response_time_ms=100
        )
        return client_mock
    
    @pytest.fixture
    def llm_config(self):
        """LLM service configuration for testing."""
        return LLMServiceConfig(
            redis_url="redis://localhost:6379",
            openai_api_key="test-key",
            primary_model="gpt-4o",
            fallback_model="gpt-3.5-turbo",
            temperature=0.8,
            max_tokens=1000,
            conversation_ttl=3600,
            max_conversation_tokens=2000,
            system_message="You are a test assistant.",
            enable_debug_logging=True
        )
    
    @pytest.mark.asyncio
    async def test_conversation_creation_and_isolation(self, llm_config, mock_redis, mock_openai_client):
        """Test conversation creation and channel isolation."""
        # Create conversation manager
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="You are a test assistant."
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
        
        try:
            # Create conversations for different channels
            channel1 = "channel_001"
            channel2 = "channel_002"
            
            conv1 = await conv_manager.create_conversation(channel1)
            conv2 = await conv_manager.create_conversation(channel2)
            
            # Verify conversations are created
            assert conv1 is not None
            assert conv2 is not None
            assert conv1.channel_id == channel1
            assert conv2.channel_id == channel2
            assert conv1.conversation_id != conv2.conversation_id
            
            # Add messages to each conversation
            await conv_manager.add_message(channel1, "user", "Hello from channel 1")
            await conv_manager.add_message(channel2, "user", "Hello from channel 2")
            
            # Verify messages are isolated
            history1 = await conv_manager.get_conversation_history(channel1)
            history2 = await conv_manager.get_conversation_history(channel2)
            
            assert len(history1) == 3  # system + user message
            assert len(history2) == 3  # system + user message
            assert history1[2]["content"] == "Hello from channel 1"
            assert history2[2]["content"] == "Hello from channel 2"
            
            # Verify no cross-contamination
            assert history1[2]["content"] != history2[2]["content"]
            
            logger.info("✅ Conversation creation and isolation test passed")
            
        finally:
            await conv_manager.stop()
    
    @pytest.mark.asyncio
    async def test_concurrent_conversation_handling(self, llm_config, mock_redis, mock_openai_client):
        """Test handling multiple concurrent conversations."""
        # Create conversation manager
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="You are a test assistant."
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
        
        try:
            # Create multiple conversations concurrently
            channels = [f"channel_{i:03d}" for i in range(10)]
            
            # Create conversations concurrently
            tasks = [conv_manager.create_conversation(channel) for channel in channels]
            conversations = await asyncio.gather(*tasks)
            
            # Verify all conversations were created
            assert len(conversations) == 10
            for i, conv in enumerate(conversations):
                assert conv is not None
                assert conv.channel_id == channels[i]
            
            # Add messages concurrently
            message_tasks = []
            for i, channel in enumerate(channels):
                message_tasks.append(
                    conv_manager.add_message(channel, "user", f"Message from {channel}")
                )
            
            await asyncio.gather(*message_tasks)
            
            # Verify all messages were added correctly
            for i, channel in enumerate(channels):
                history = await conv_manager.get_conversation_history(channel)
                assert len(history) == 3  # system + user message
                assert history[2]["content"] == f"Message from {channel}"
            
            logger.info("✅ Concurrent conversation handling test passed")
            
        finally:
            await conv_manager.stop()
    
    @pytest.mark.asyncio
    async def test_token_limit_management(self, llm_config, mock_redis, mock_openai_client):
        """Test conversation truncation when token limits are exceeded."""
        # Create conversation manager with low token limit
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=100,  # Very low limit for testing
            system_message="You are a test assistant."
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
        
        try:
            channel = "test_channel"
            conv = await conv_manager.create_conversation(channel)
            
            # Add multiple messages to exceed token limit
            long_message = "This is a very long message that will consume many tokens. " * 10
            
            for i in range(5):
                await conv_manager.add_message(channel, "user", f"{long_message} Message {i}")
            
            # Get conversation history
            history = await conv_manager.get_conversation_history(channel)
            
            # Verify conversation was truncated (should have system message + recent messages)
            assert len(history) < 6  # Less than 5 user messages + system
            assert history[0]["role"] == "system"  # System message should be preserved
            
            # Verify total tokens are within limit
            conv = await conv_manager.get_conversation(channel)
            assert conv.total_tokens <= conv_config.max_tokens
            
            logger.info("✅ Token limit management test passed")
            
        finally:
            await conv_manager.stop()
    
    @pytest.mark.asyncio
    async def test_fallback_model_activation(self, llm_config, mock_redis):
        """Test fallback model activation when primary model fails."""
        # Mock OpenAI client with primary model failure
        client_mock = AsyncMock()
        client_mock.test_connection.return_value = True
        
        # First call fails, second call succeeds with fallback
        call_count = 0
        async def mock_generate_response(messages, model=None, stream=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Primary model failed")
            else:
                return MagicMock(
                    content="Fallback response",
                    model_used="gpt-3.5-turbo",
                    tokens_used=5,
                    response_time_ms=200
                )
        
        client_mock.generate_response.side_effect = mock_generate_response
        
        # Create LLM service with mocked client
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis), \
             patch('openai_client.OpenAIClient', return_value=client_mock):
            
            service = LLMService(llm_config)
            await service.start()
        
        try:
            # Test fallback behavior
            messages = [{"role": "user", "content": "Test message"}]
            response = await service.openai_client.generate_response(messages)
            
            # Verify fallback was used
            assert response.model_used == "gpt-3.5-turbo"
            assert response.content == "Fallback response"
            assert call_count == 2  # Primary failed, fallback succeeded
            
            logger.info("✅ Fallback model activation test passed")
            
        finally:
            await service.stop()
    
    @pytest.mark.asyncio
    async def test_conversation_persistence_across_restarts(self, llm_config, mock_redis, mock_openai_client):
        """Test conversation persistence across service restarts."""
        # Create conversation manager
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="You are a test assistant."
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
        
        try:
            # Create conversation and add messages
            channel = "persistent_channel"
            conv = await conv_manager.create_conversation(channel)
            await conv_manager.add_message(channel, "user", "First message")
            await conv_manager.add_message(channel, "assistant", "First response")
            
            # Simulate service restart by creating new manager
            await conv_manager.stop()
            
            # Create new manager (simulating restart)
            with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
                new_conv_manager = ConversationManager(conv_config)
                await new_conv_manager.start()
            
            try:
                # Retrieve conversation after restart
                retrieved_conv = await new_conv_manager.get_conversation(channel)
                
                # Verify conversation was persisted
                assert retrieved_conv is not None
                assert retrieved_conv.channel_id == channel
                assert retrieved_conv.conversation_id == conv.conversation_id
                
                # Verify messages were persisted
                history = await new_conv_manager.get_conversation_history(channel)
                assert len(history) == 4  # system + 2 messages
                assert history[1]["content"] == "First message"
                assert history[2]["content"] == "First response"
                
                logger.info("✅ Conversation persistence test passed")
                
            finally:
                await new_conv_manager.stop()
                
        finally:
            await conv_manager.stop()
    
    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self, llm_config, mock_redis, mock_openai_client):
        """Test error handling and recovery mechanisms."""
        # Mock Redis with intermittent failures
        redis_mock = AsyncMock()
        redis_mock.ping.return_value = True
        redis_mock.pubsub.return_value = AsyncMock()
        
        call_count = 0
        async def mock_publish(channel, message):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # First two calls fail
                raise Exception("Redis publish failed")
            return 1
        
        redis_mock.publish.side_effect = mock_publish
        
        # Create LLM service with mocked Redis
        with patch('redis.asyncio.Redis.from_url', return_value=redis_mock), \
             patch('openai_client.OpenAIClient', return_value=mock_openai_client):
            
            service = LLMService(llm_config)
            await service.start()
        
        try:
            # Test error handling
            channel = "error_test_channel"
            await service.create_conversation(channel)
            
            # This should handle Redis errors gracefully
            await service._publish_response(channel, mock_openai_client.generate_response.return_value)
            
            # Verify error was handled (no exception raised)
            assert call_count >= 1
            
            logger.info("✅ Error handling and recovery test passed")
            
        finally:
            await service.stop()
    
    @pytest.mark.asyncio
    async def test_performance_under_load(self, llm_config, mock_redis, mock_openai_client):
        """Test service performance under load."""
        # Create conversation manager
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="You are a test assistant."
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
        
        try:
            # Test with many concurrent operations
            num_channels = 50
            messages_per_channel = 10
            
            start_time = time.time()
            
            # Create conversations concurrently
            channels = [f"perf_channel_{i:03d}" for i in range(num_channels)]
            conv_tasks = [conv_manager.create_conversation(channel) for channel in channels]
            await asyncio.gather(*conv_tasks)
            
            # Add messages concurrently
            message_tasks = []
            for i, channel in enumerate(channels):
                for j in range(messages_per_channel):
                    message_tasks.append(
                        conv_manager.add_message(channel, "user", f"Message {j} from {channel}")
                    )
            
            await asyncio.gather(*message_tasks)
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Verify performance is reasonable
            assert total_time < 10.0  # Should complete within 10 seconds
            
            # Verify all data was processed correctly
            for channel in channels:
                history = await conv_manager.get_conversation_history(channel)
                assert len(history) == messages_per_channel + 1  # +1 for system message
            
            logger.info(f"✅ Performance test passed: {num_channels} channels, "
                       f"{messages_per_channel} messages each in {total_time:.2f}s")
            
        finally:
            await conv_manager.stop()


async def run_integration_tests():
    """Run all integration tests."""
    test_instance = TestLLMServiceIntegration()
    
    # Run tests
    tests = [
        test_instance.test_conversation_creation_and_isolation,
        test_instance.test_concurrent_conversation_handling,
        test_instance.test_token_limit_management,
        test_instance.test_fallback_model_activation,
        test_instance.test_conversation_persistence_across_restarts,
        test_instance.test_error_handling_and_recovery,
        test_instance.test_performance_under_load
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            logger.error(f"❌ Test {test.__name__} failed: {e}")
            failed += 1
    
    logger.info(f"Integration tests completed: {passed} passed, {failed} failed")
    return passed, failed


if __name__ == "__main__":
    asyncio.run(run_integration_tests())
