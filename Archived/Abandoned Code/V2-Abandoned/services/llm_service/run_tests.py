#!/usr/bin/env python3
"""
LLM Service Test Runner

This script runs all tests for the LLM service including unit tests,
integration tests, and performance tests.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def run_unit_tests():
    """Run unit tests for individual components."""
    logger.info("Running unit tests...")
    
    try:
        # Test conversation manager
        from conversation_manager import ConversationManager, ConversationConfig
        from openai_client import OpenAIClient, LLMConfig as OpenAIConfig, ModelType
        
        # Test conversation manager
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=1000,
            system_message="Test assistant"
        )
        
        # Mock Redis for unit tests
        import redis.asyncio
        from unittest.mock import AsyncMock
        
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.setex.return_value = True
        mock_redis.get.return_value = None
        mock_redis.delete.return_value = True
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
            
            # Test basic functionality
            channel = "test_channel"
            conv = await conv_manager.create_conversation(channel)
            assert conv is not None
            assert conv.channel_id == channel
            
            # Test message addition
            await conv_manager.add_message(channel, "user", "Test message")
            history = await conv_manager.get_conversation_history(channel)
            assert len(history) == 2  # system + user message
            
            await conv_manager.stop()
        
        logger.info("✅ Unit tests passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ Unit tests failed: {e}")
        return False


async def run_integration_tests():
    """Run integration tests."""
    logger.info("Running integration tests...")
    
    try:
        from test_llm_integration import run_integration_tests
        passed, failed = await run_integration_tests()
        
        if failed == 0:
            logger.info("✅ Integration tests passed")
            return True
        else:
            logger.error(f"❌ Integration tests failed: {failed} tests failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Integration tests failed: {e}")
        return False


async def run_performance_tests():
    """Run performance tests."""
    logger.info("Running performance tests...")
    
    try:
        from conversation_manager import ConversationManager, ConversationConfig
        from openai_client import OpenAIClient, LLMConfig as OpenAIConfig, ModelType
        
        # Performance test configuration
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="Performance test assistant"
        )
        
        # Mock Redis for performance tests
        from unittest.mock import AsyncMock, patch
        
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.setex.return_value = True
        mock_redis.get.return_value = None
        mock_redis.delete.return_value = True
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
            
            # Performance test: Create many conversations
            num_conversations = 100
            start_time = time.time()
            
            tasks = []
            for i in range(num_conversations):
                channel = f"perf_channel_{i:03d}"
                tasks.append(conv_manager.create_conversation(channel))
            
            conversations = await asyncio.gather(*tasks)
            creation_time = time.time() - start_time
            
            # Performance test: Add messages concurrently
            message_tasks = []
            for i, conv in enumerate(conversations):
                channel = f"perf_channel_{i:03d}"
                for j in range(5):  # 5 messages per conversation
                    message_tasks.append(
                        conv_manager.add_message(channel, "user", f"Message {j}")
                    )
            
            start_time = time.time()
            await asyncio.gather(*message_tasks)
            message_time = time.time() - start_time
            
            await conv_manager.stop()
            
            # Verify performance metrics
            conversations_per_second = num_conversations / creation_time
            messages_per_second = (num_conversations * 5) / message_time
            
            logger.info(f"Performance metrics:")
            logger.info(f"  - Conversations created: {conversations_per_second:.2f}/s")
            logger.info(f"  - Messages processed: {messages_per_second:.2f}/s")
            
            # Performance thresholds
            if conversations_per_second > 10 and messages_per_second > 50:
                logger.info("✅ Performance tests passed")
                return True
            else:
                logger.error("❌ Performance tests failed: Below threshold")
                return False
                
    except Exception as e:
        logger.error(f"❌ Performance tests failed: {e}")
        return False


async def main():
    """Main test runner."""
    logger.info("Starting LLM Service Test Suite")
    logger.info("=" * 50)
    
    start_time = time.time()
    
    # Run all test suites
    test_results = []
    
    # Unit tests
    unit_passed = await run_unit_tests()
    test_results.append(("Unit Tests", unit_passed))
    
    # Integration tests
    integration_passed = await run_integration_tests()
    test_results.append(("Integration Tests", integration_passed))
    
    # Performance tests
    performance_passed = await run_performance_tests()
    test_results.append(("Performance Tests", performance_passed))
    
    # Summary
    total_time = time.time() - start_time
    passed_count = sum(1 for _, passed in test_results if passed)
    total_count = len(test_results)
    
    logger.info("=" * 50)
    logger.info("Test Results Summary:")
    for test_name, passed in test_results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"  {test_name}: {status}")
    
    logger.info(f"Total: {passed_count}/{total_count} test suites passed")
    logger.info(f"Total time: {total_time:.2f} seconds")
    
    if passed_count == total_count:
        logger.info("🎉 All tests passed!")
        return 0
    else:
        logger.error("💥 Some tests failed!")
        return 1


if __name__ == "__main__":
    # Add unittest.mock import
    from unittest.mock import patch
    sys.exit(asyncio.run(main()))
