#!/usr/bin/env python3
"""
LLM Service Performance Tests

This script performs comprehensive performance testing of the LLM service
including conversation management, Redis operations, and OpenAI API calls.
"""

import asyncio
import logging
import time
import statistics
from typing import List, Dict, Any
from pathlib import Path
import sys

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent / "shared"))

from conversation_manager import ConversationManager, ConversationConfig
from openai_client import OpenAIClient, LLMConfig as OpenAIConfig, ModelType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LLMServicePerformanceTester:
    """Performance tester for LLM service components."""
    
    def __init__(self):
        """Initialize the performance tester."""
        self.results = {}
    
    async def test_conversation_creation_performance(self, num_conversations: int = 1000):
        """Test conversation creation performance."""
        logger.info(f"Testing conversation creation with {num_conversations} conversations...")
        
        # Mock Redis for testing
        from unittest.mock import AsyncMock, patch
        
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.setex.return_value = True
        mock_redis.get.return_value = None
        mock_redis.delete.return_value = True
        
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="Performance test assistant"
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
            
            try:
                # Test sequential creation
                start_time = time.time()
                for i in range(num_conversations):
                    channel = f"perf_channel_{i:04d}"
                    await conv_manager.create_conversation(channel)
                sequential_time = time.time() - start_time
                
                # Test concurrent creation
                start_time = time.time()
                tasks = []
                for i in range(num_conversations, num_conversations * 2):
                    channel = f"perf_channel_{i:04d}"
                    tasks.append(conv_manager.create_conversation(channel))
                await asyncio.gather(*tasks)
                concurrent_time = time.time() - start_time
                
                # Calculate metrics
                sequential_rate = num_conversations / sequential_time
                concurrent_rate = num_conversations / concurrent_time
                
                self.results['conversation_creation'] = {
                    'sequential_time': sequential_time,
                    'concurrent_time': concurrent_time,
                    'sequential_rate': sequential_rate,
                    'concurrent_rate': concurrent_rate,
                    'concurrent_improvement': (concurrent_rate / sequential_rate) - 1
                }
                
                logger.info(f"Sequential: {sequential_rate:.2f} conversations/s")
                logger.info(f"Concurrent: {concurrent_rate:.2f} conversations/s")
                logger.info(f"Improvement: {self.results['conversation_creation']['concurrent_improvement']:.1%}")
                
            finally:
                await conv_manager.stop()
    
    async def test_message_processing_performance(self, num_messages: int = 5000):
        """Test message processing performance."""
        logger.info(f"Testing message processing with {num_messages} messages...")
        
        # Mock Redis for testing
        from unittest.mock import AsyncMock, patch
        
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.setex.return_value = True
        mock_redis.get.return_value = None
        mock_redis.delete.return_value = True
        
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="Performance test assistant"
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
            
            try:
                # Create test conversation
                channel = "perf_message_channel"
                await conv_manager.create_conversation(channel)
                
                # Test message processing
                start_time = time.time()
                for i in range(num_messages):
                    await conv_manager.add_message(
                        channel, 
                        "user", 
                        f"Test message {i} with some content to test token counting"
                    )
                processing_time = time.time() - start_time
                
                # Calculate metrics
                messages_per_second = num_messages / processing_time
                
                self.results['message_processing'] = {
                    'total_messages': num_messages,
                    'processing_time': processing_time,
                    'messages_per_second': messages_per_second
                }
                
                logger.info(f"Processed {num_messages} messages in {processing_time:.2f}s")
                logger.info(f"Rate: {messages_per_second:.2f} messages/s")
                
            finally:
                await conv_manager.stop()
    
    async def test_token_counting_performance(self, num_texts: int = 1000):
        """Test token counting performance."""
        logger.info(f"Testing token counting with {num_texts} texts...")
        
        # Mock Redis for testing
        from unittest.mock import AsyncMock, patch
        
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.setex.return_value = True
        mock_redis.get.return_value = None
        mock_redis.delete.return_value = True
        
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="Performance test assistant"
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
            
            try:
                # Test texts of varying lengths
                test_texts = [
                    "Short text",
                    "This is a medium length text that should have more tokens than the short one.",
                    "This is a very long text that contains many words and should have significantly more tokens than the previous texts. " * 10
                ]
                
                # Test token counting performance
                start_time = time.time()
                total_tokens = 0
                
                for i in range(num_texts):
                    text = test_texts[i % len(test_texts)]
                    tokens = conv_manager._count_tokens(text)
                    total_tokens += tokens
                
                counting_time = time.time() - start_time
                
                # Calculate metrics
                texts_per_second = num_texts / counting_time
                avg_tokens_per_text = total_tokens / num_texts
                
                self.results['token_counting'] = {
                    'total_texts': num_texts,
                    'counting_time': counting_time,
                    'texts_per_second': texts_per_second,
                    'total_tokens': total_tokens,
                    'avg_tokens_per_text': avg_tokens_per_text
                }
                
                logger.info(f"Counted tokens for {num_texts} texts in {counting_time:.2f}s")
                logger.info(f"Rate: {texts_per_second:.2f} texts/s")
                logger.info(f"Average tokens per text: {avg_tokens_per_text:.1f}")
                
            finally:
                await conv_manager.stop()
    
    async def test_conversation_truncation_performance(self, num_messages: int = 1000):
        """Test conversation truncation performance."""
        logger.info(f"Testing conversation truncation with {num_messages} messages...")
        
        # Mock Redis for testing
        from unittest.mock import AsyncMock, patch
        
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.setex.return_value = True
        mock_redis.get.return_value = None
        mock_redis.delete.return_value = True
        
        # Use low token limit to force truncation
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=100,  # Very low limit
            system_message="Performance test assistant"
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
            
            try:
                # Create test conversation
                channel = "perf_truncation_channel"
                await conv_manager.create_conversation(channel)
                
                # Add messages that will trigger truncation
                long_message = "This is a long message that will consume many tokens. " * 5
                
                start_time = time.time()
                for i in range(num_messages):
                    await conv_manager.add_message(channel, "user", f"{long_message} Message {i}")
                processing_time = time.time() - start_time
                
                # Get final conversation state
                conv = await conv_manager.get_conversation(channel)
                history = await conv_manager.get_conversation_history(channel)
                
                # Calculate metrics
                messages_per_second = num_messages / processing_time
                
                self.results['conversation_truncation'] = {
                    'total_messages': num_messages,
                    'processing_time': processing_time,
                    'messages_per_second': messages_per_second,
                    'final_message_count': len(history),
                    'final_token_count': conv.total_tokens if conv else 0
                }
                
                logger.info(f"Processed {num_messages} messages with truncation in {processing_time:.2f}s")
                logger.info(f"Rate: {messages_per_second:.2f} messages/s")
                logger.info(f"Final conversation: {len(history)} messages, {conv.total_tokens if conv else 0} tokens")
                
            finally:
                await conv_manager.stop()
    
    async def test_concurrent_channel_isolation(self, num_channels: int = 100, messages_per_channel: int = 50):
        """Test concurrent channel isolation performance."""
        logger.info(f"Testing concurrent channel isolation with {num_channels} channels, {messages_per_channel} messages each...")
        
        # Mock Redis for testing
        from unittest.mock import AsyncMock, patch
        
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.setex.return_value = True
        mock_redis.get.return_value = None
        mock_redis.delete.return_value = True
        
        conv_config = ConversationConfig(
            redis_url="redis://localhost:6379",
            conversation_ttl=3600,
            max_tokens=2000,
            system_message="Performance test assistant"
        )
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis):
            conv_manager = ConversationManager(conv_config)
            await conv_manager.start()
            
            try:
                # Create conversations concurrently
                start_time = time.time()
                channels = [f"isolation_channel_{i:03d}" for i in range(num_channels)]
                
                conv_tasks = [conv_manager.create_conversation(channel) for channel in channels]
                conversations = await asyncio.gather(*conv_tasks)
                creation_time = time.time() - start_time
                
                # Add messages concurrently
                start_time = time.time()
                message_tasks = []
                
                for i, channel in enumerate(channels):
                    for j in range(messages_per_channel):
                        message_tasks.append(
                            conv_manager.add_message(channel, "user", f"Message {j} from {channel}")
                        )
                
                await asyncio.gather(*message_tasks)
                message_time = time.time() - start_time
                
                # Verify isolation
                isolation_verified = True
                for i, channel in enumerate(channels):
                    history = await conv_manager.get_conversation_history(channel)
                    if len(history) != messages_per_channel + 1:  # +1 for system message
                        isolation_verified = False
                        break
                
                # Calculate metrics
                channels_per_second = num_channels / creation_time
                messages_per_second = (num_channels * messages_per_channel) / message_time
                
                self.results['concurrent_isolation'] = {
                    'num_channels': num_channels,
                    'messages_per_channel': messages_per_channel,
                    'total_messages': num_channels * messages_per_channel,
                    'creation_time': creation_time,
                    'message_time': message_time,
                    'channels_per_second': channels_per_second,
                    'messages_per_second': messages_per_second,
                    'isolation_verified': isolation_verified
                }
                
                logger.info(f"Created {num_channels} channels in {creation_time:.2f}s ({channels_per_second:.2f}/s)")
                logger.info(f"Processed {num_channels * messages_per_channel} messages in {message_time:.2f}s ({messages_per_second:.2f}/s)")
                logger.info(f"Isolation verified: {isolation_verified}")
                
            finally:
                await conv_manager.stop()
    
    def print_performance_report(self):
        """Print comprehensive performance report."""
        logger.info("=" * 60)
        logger.info("LLM Service Performance Report")
        logger.info("=" * 60)
        
        for test_name, results in self.results.items():
            logger.info(f"\n{test_name.replace('_', ' ').title()}:")
            logger.info("-" * 40)
            
            for key, value in results.items():
                if isinstance(value, float):
                    if 'rate' in key or 'per_second' in key:
                        logger.info(f"  {key}: {value:.2f}")
                    elif 'time' in key:
                        logger.info(f"  {key}: {value:.3f}s")
                    else:
                        logger.info(f"  {key}: {value:.1f}")
                else:
                    logger.info(f"  {key}: {value}")
        
        # Performance recommendations
        logger.info("\nPerformance Recommendations:")
        logger.info("-" * 40)
        
        if 'conversation_creation' in self.results:
            conv_results = self.results['conversation_creation']
            if conv_results['concurrent_rate'] > conv_results['sequential_rate'] * 1.5:
                logger.info("✅ Concurrent conversation creation shows good performance improvement")
            else:
                logger.info("⚠️  Consider optimizing concurrent conversation creation")
        
        if 'message_processing' in self.results:
            msg_results = self.results['message_processing']
            if msg_results['messages_per_second'] > 100:
                logger.info("✅ Message processing performance is good")
            else:
                logger.info("⚠️  Consider optimizing message processing performance")
        
        if 'concurrent_isolation' in self.results:
            iso_results = self.results['concurrent_isolation']
            if iso_results['isolation_verified']:
                logger.info("✅ Channel isolation is working correctly")
            else:
                logger.error("❌ Channel isolation has issues - investigate immediately")


async def main():
    """Main performance test runner."""
    logger.info("Starting LLM Service Performance Tests")
    logger.info("=" * 60)
    
    tester = LLMServicePerformanceTester()
    
    # Run performance tests
    await tester.test_conversation_creation_performance(1000)
    await tester.test_message_processing_performance(5000)
    await tester.test_token_counting_performance(2000)
    await tester.test_conversation_truncation_performance(500)
    await tester.test_concurrent_channel_isolation(100, 25)
    
    # Print comprehensive report
    tester.print_performance_report()
    
    logger.info("\n🎉 Performance testing completed!")


if __name__ == "__main__":
    asyncio.run(main())
