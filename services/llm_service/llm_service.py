"""
LLM Service - Main Service Implementation

This module implements the main LLM service that handles conversation management,
OpenAI integration, and Redis message publishing for the microservices architecture.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from redis.asyncio import Redis

from conversation_manager import ConversationManager, ConversationConfig
from openai_client import OpenAIClient, LLMConfig as OpenAIConfig, ModelType
from shared.fallback_responses import FallbackResponseManager
from shared.health_check import create_health_check_app
import uvicorn

logger = logging.getLogger(__name__)


@dataclass
class LLMServiceConfig:
    """Configuration for the LLM service."""
    # OpenAI settings
    openai_api_key: str

    # Redis settings
    redis_url: str = "redis://localhost:6379"
    
    openai_base_url: Optional[str] = None
    primary_model: str = "gpt-4o"
    fallback_model: str = "gpt-3.5-turbo"
    temperature: float = 0.8
    max_tokens: int = 4096
    
    # Conversation settings
    conversation_ttl: int = 3600  # 1 hour
    max_conversation_tokens: int = 4000
    system_message: str = "You are a helpful AI assistant for Jugaar LLC."
    
    # Service settings
    health_check_interval: int = 30
    enable_debug_logging: bool = True
    service_name: str = "llm_service"
    health_check_port: int = 8000


class LLMService:
    """
    Main LLM service that handles conversation management and response generation.
    
    This service integrates conversation context management, OpenAI API calls,
    and Redis message publishing for the microservices architecture.
    """
    
    def __init__(self, config: LLMServiceConfig):
        """Initialize the LLM service."""
        self.config = config
        self.redis_client: Optional[Redis] = None
        
        # Initialize components
        self.conversation_manager = ConversationManager(
            ConversationConfig(
                redis_url=config.redis_url,
                conversation_ttl=config.conversation_ttl,
                max_tokens=config.max_conversation_tokens,
                system_message=config.system_message
            )
        )
        
        # Map model strings to ModelType enum
        model_mapping = {
            "gpt-4o": ModelType.GPT_4O,
            "gpt-4o-mini": ModelType.GPT_4O_MINI,
            "gpt-3.5-turbo": ModelType.GPT_3_5_TURBO
        }
        
        self.openai_client = OpenAIClient(
            OpenAIConfig(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                primary_model=model_mapping.get(config.primary_model, ModelType.GPT_4O),
                fallback_model=model_mapping.get(config.fallback_model, ModelType.GPT_3_5_TURBO),
                temperature=config.temperature,
                max_tokens=config.max_tokens
            )
        )
        
        self.fallback_manager = FallbackResponseManager()
        
        # Service state
        self._running = False
        
        # Statistics
        self.stats = {
            'service_started_at': 0,
            'requests_processed': 0,
            'responses_generated': 0,
            'conversations_created': 0,
            'conversations_ended': 0,
            'errors': 0,
            'redis_errors': 0,
            'openai_errors': 0
        }
    
    async def _start_health_check_server(self):
        """Start the health check server."""
        dependency_checks = {
            "redis": self.redis_client.ping,
            "openai": self.openai_client.test_connection
        }
        app = create_health_check_app(self.config.service_name, dependency_checks)
        
        config = uvicorn.Config(app, host="0.0.0.0", port=self.config.health_check_port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def start(self):
        """Start the LLM service."""
        try:
            logger.info("Starting LLM service...")
            
            # Initialize Redis client
            self.redis_client = Redis.from_url(self.config.redis_url, decode_responses=True)
            await self.redis_client.ping()
            
            # Start conversation manager
            await self.conversation_manager.start()
            
            # Test OpenAI connection
            if not await self.openai_client.test_connection():
                raise Exception("OpenAI API connection test failed")
            
            # Start background tasks
            self._running = True
            health_check_task = asyncio.create_task(self._start_health_check_server())
            message_processing_task = asyncio.create_task(self._start_message_processing())
            
            self.stats['service_started_at'] = time.time()
            logger.info("LLM service started successfully")

            # Keep the service running by waiting on the tasks
            await asyncio.gather(health_check_task, message_processing_task)
            
        except Exception as e:
            logger.error(f"Failed to start LLM service: {e}")
            raise
    
    async def stop(self):
        """Stop the LLM service."""
        try:
            logger.info("Stopping LLM service...")
            
            self._running = False
            
            # Stop conversation manager
            await self.conversation_manager.stop()
            
            # Close OpenAI client
            await self.openai_client.close()
            
            # Close Redis client
            if self.redis_client:
                await self.redis_client.close()
            
            logger.info("LLM service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping LLM service: {e}")
    
    async def _start_message_processing(self):
        """Start processing Redis messages."""
        try:
            # Subscribe to relevant channels
            pubsub = self.redis_client.pubsub()
            await pubsub.subscribe(
                "stt:transcription:complete",
                "calls:control:generate_response",
                "calls:control:end_conversation"
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
            
            if channel == "stt:transcription:complete":
                await self._handle_transcription(data)
            elif channel == "calls:control:generate_response":
                await self._handle_generate_response(data)
            elif channel == "calls:control:end_conversation":
                await self._handle_end_conversation(data)
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error handling message: {e}")
    
    async def _handle_transcription(self, data: Dict[str, Any]):
        """Handle transcription completion from STT service."""
        try:
            channel_id = data.get('channel_id')
            transcript = data.get('transcript', '')
            confidence = data.get('confidence', 0.0)
            
            if not channel_id or not transcript:
                logger.warning("Invalid transcription data received")
                return
            
            # Add user message to conversation
            await self.conversation_manager.add_message(
                channel_id=channel_id,
                role="user",
                content=transcript,
                metadata={
                    'confidence': confidence,
                    'source': 'stt_service',
                    'timestamp': time.time()
                }
            )
            
            # Generate response
            await self._generate_response_for_channel(channel_id)
            
            self.stats['requests_processed'] += 1
            
            logger.info(f"Processed transcription for channel {channel_id}: {transcript[:50]}...")
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error handling transcription: {e}")
    
    async def _handle_generate_response(self, data: Dict[str, Any]):
        """Handle explicit response generation request."""
        try:
            channel_id = data.get('channel_id')
            if not channel_id:
                logger.warning("No channel_id in generate_response request")
                return
            
            await self._generate_response_for_channel(channel_id)
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error handling generate_response: {e}")
    
    async def _handle_end_conversation(self, data: Dict[str, Any]):
        """Handle conversation end request."""
        try:
            channel_id = data.get('channel_id')
            if not channel_id:
                logger.warning("No channel_id in end_conversation request")
                return
            
            # End conversation
            await self.conversation_manager.end_conversation(channel_id)
            self.stats['conversations_ended'] += 1
            
            logger.info(f"Ended conversation for channel {channel_id}")
            
        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"Error handling end_conversation: {e}")
    
    async def _generate_response_for_channel(self, channel_id: str):
        """Generate a response for a specific channel."""
        try:
            # Get or create conversation
            conversation = await self.conversation_manager.get_conversation(channel_id)
            if not conversation:
                conversation = await self.conversation_manager.create_conversation(channel_id)
                self.stats['conversations_created'] += 1
            
            # Get conversation history
            messages = await self.conversation_manager.get_conversation_history(channel_id)
            
            # Generate response using OpenAI
            response = await self.openai_client.generate_response(messages)
            
            # Add assistant response to conversation
            await self.conversation_manager.add_message(
                channel_id=channel_id,
                role="assistant",
                content=response.content,
                metadata={
                    'model_used': response.model_used,
                    'tokens_used': response.tokens_used,
                    'response_time_ms': response.response_time_ms,
                    'finish_reason': response.finish_reason,
                    'timestamp': time.time()
                }
            )
            
            # Publish response to TTS service
            await self._publish_response(channel_id, response)
            
            self.stats['responses_generated'] += 1
            
            logger.info(f"Generated response for channel {channel_id} using {response.model_used}: "
                       f"{response.tokens_used} tokens")
            
        except Exception as e:
            self.stats['openai_errors'] += 1
            logger.error(f"Error generating response for channel {channel_id}: {e}")
            
            # Use fallback response
            fallback_text = self.fallback_manager.get_response("ERROR_GENERIC")
            if fallback_text:
                await self._publish_response(channel_id, {"content": fallback_text, "model_used": "fallback"})
            else:
                # Publish error to TTS service if no fallback available
                await self._publish_error(channel_id, str(e))
    
    async def _publish_response(self, channel_id: str, response):
        """Publish LLM response to TTS service."""
        try:
            message = {
                'channel_id': channel_id,
                'text': response.content,
                'model_used': response.model_used,
                'tokens_used': response.tokens_used,
                'response_time_ms': response.response_time_ms,
                'timestamp': time.time()
            }
            
            await self.redis_client.publish(
                "llm:response:ready",
                json.dumps(message)
            )
            
            logger.debug(f"Published response for channel {channel_id}")
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Error publishing response: {e}")
    
    async def _publish_error(self, channel_id: str, error_message: str):
        """Publish error message to TTS service."""
        try:
            message = {
                'channel_id': channel_id,
                'error': error_message,
                'timestamp': time.time()
            }
            
            await self.redis_client.publish(
                "llm:error",
                json.dumps(message)
            )
            
            logger.debug(f"Published error for channel {channel_id}")
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Error publishing error message: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        uptime = time.time() - self.stats['service_started_at'] if self.stats['service_started_at'] > 0 else 0
        
        return {
            **self.stats,
            'uptime_seconds': uptime,
            'conversation_stats': self.conversation_manager.get_stats(),
            'openai_stats': self.openai_client.get_stats()
        }
    
    async def create_conversation(self, channel_id: str) -> bool:
        """Create a new conversation for a channel."""
        try:
            conversation = await self.conversation_manager.create_conversation(channel_id)
            if conversation:
                self.stats['conversations_created'] += 1
                return True
            return False
        except Exception as e:
            logger.error(f"Error creating conversation for channel {channel_id}: {e}")
            return False
    
    async def end_conversation(self, channel_id: str) -> bool:
        """End a conversation for a channel."""
        try:
            success = await self.conversation_manager.end_conversation(channel_id)
            if success:
                self.stats['conversations_ended'] += 1
            return success
        except Exception as e:
            logger.error(f"Error ending conversation for channel {channel_id}: {e}")
            return False
