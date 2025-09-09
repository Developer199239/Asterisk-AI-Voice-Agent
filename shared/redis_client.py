"""
Redis Message Queue Infrastructure for Asterisk AI Voice Agent v2.0

This module provides async Redis Pub/Sub functionality for inter-service communication
with connection pooling, retry logic, and message serialization.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Callable, Union
from datetime import datetime
import redis.asyncio as aioredis
from redis.asyncio import Redis, ConnectionPool
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from shared.config import RedisConfig
import structlog

logger = structlog.get_logger(__name__)


class MessageBase(BaseModel):
    """Base message class with common fields"""
    
    message_id: str = Field(..., description="Unique message identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")
    source_service: str = Field(..., description="Service that sent the message")
    message_type: str = Field(..., description="Type of message for routing")


class CallNewMessage(MessageBase):
    """Message sent when a new call is received"""
    
    message_type: str = Field(default="call_new", description="Message type")
    call_id: str = Field(..., description="Unique call identifier")
    channel_id: str = Field(..., description="Asterisk channel ID")
    caller_id: Optional[str] = Field(None, description="Caller ID number")
    caller_name: Optional[str] = Field(None, description="Caller name")


class MediaChunkMessage(MessageBase):
    """Message for raw audio chunks from RTP stream"""
    
    message_type: str = Field(default="media_chunk", description="Message type")
    call_id: str = Field(..., description="Call identifier")
    chunk_data: bytes = Field(..., description="Raw audio chunk data")
    sample_rate: int = Field(default=16000, description="Audio sample rate")
    channels: int = Field(default=1, description="Number of audio channels")


class STTTranscriptionMessage(MessageBase):
    """Message sent when speech-to-text transcription is complete"""
    
    message_type: str = Field(default="stt_transcription", description="Message type")
    call_id: str = Field(..., description="Call identifier")
    transcription: str = Field(..., description="Transcribed text")
    confidence: float = Field(..., description="Confidence score (0.0-1.0)")
    is_final: bool = Field(default=True, description="Whether this is a final transcription")


class LLMResponseMessage(MessageBase):
    """Message sent when LLM generates a response"""
    
    message_type: str = Field(default="llm_response", description="Message type")
    call_id: str = Field(..., description="Call identifier")
    response_text: str = Field(..., description="Generated response text")
    conversation_id: str = Field(..., description="Conversation identifier")
    tokens_used: Optional[int] = Field(None, description="Number of tokens used")


class TTSSynthesisMessage(MessageBase):
    """Message sent when text-to-speech synthesis is complete"""
    
    message_type: str = Field(default="tts_synthesis", description="Message type")
    call_id: str = Field(..., description="Call identifier")
    audio_file_path: str = Field(..., description="Path to generated audio file")
    duration_seconds: float = Field(..., description="Audio duration in seconds")
    sample_rate: int = Field(default=16000, description="Audio sample rate")


class CallControlMessage(MessageBase):
    """Message for call control commands"""
    
    message_type: str = Field(default="call_control", description="Message type")
    call_id: str = Field(..., description="Call identifier")
    action: str = Field(..., description="Control action (play, stop, hangup, etc.)")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")


class RedisMessageQueue:
    """Async Redis message queue with Pub/Sub functionality"""
    
    def __init__(self, config: RedisConfig):
        self.config = config
        self.redis: Optional[Redis] = None
        self.pubsub = None
        self.subscribers: Dict[str, List[Callable]] = {}
        self._running = False
        self._health_check_task: Optional[asyncio.Task] = None
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ConnectionError, OSError))
    )
    async def connect(self):
        """Connect to Redis with retry logic"""
        try:
            self.redis = aioredis.from_url(
                self.config.url,
                encoding="utf-8",
                decode_responses=self.config.decode_responses,
                retry_on_timeout=True,
                socket_keepalive=True,
                socket_keepalive_options={}
            )
            
            # Test connection
            await self.redis.ping()
            logger.info(f"✅ Connected to Redis at {self.config.url}")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.pubsub:
            await self.pubsub.close()
        if self.redis:
            await self.redis.close()
        self._running = False
        logger.info("Disconnected from Redis")
    
    async def publish(self, channel: str, message: MessageBase) -> int:
        """
        Publish a message to a Redis channel
        
        Args:
            channel: Redis channel name
            message: Message object to publish
            
        Returns:
            Number of subscribers that received the message
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        try:
            # Serialize message to JSON
            message_data = message.model_dump_json()
            
            # Publish to Redis
            subscribers = await self.redis.publish(channel, message_data)
            logger.debug(f"Published message to {channel}, {subscribers} subscribers")
            
            return subscribers
            
        except Exception as e:
            logger.error(f"Failed to publish message to {channel}: {e}")
            raise
    
    async def subscribe(self, channels: List[str], message_handler: Callable):
        """
        Subscribe to Redis channels
        
        Args:
            channels: List of channel names to subscribe to
            message_handler: Async function to handle received messages
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        async def do_subscribe():
            self.pubsub = self.redis.pubsub()
            await self.pubsub.subscribe(*channels)
            
            # Store subscribers for cleanup
            for channel in channels:
                if channel not in self.subscribers:
                    self.subscribers[channel] = []
                self.subscribers[channel].append(message_handler)
            
            logger.info(f"Subscribed to channels: {channels}")

        await do_subscribe()
    
    async def start_listening(self):
        """Start listening for messages on subscribed channels"""
        if not self.pubsub:
            raise RuntimeError("No active subscriptions")
        
        self._running = True
        logger.info("Started listening for messages")
        
        # Start health check loop
        self._health_check_task = asyncio.create_task(self._health_check_loop())

        while self._running:
            try:
                async for message in self.pubsub.listen():
                    if not self._running:
                        break
                    
                    if message["type"] == "message":
                        await self._handle_message(message)
                        
            except Exception as e:
                logger.error(f"Error in message listening loop: {e}, attempting to reconnect...")
                await asyncio.sleep(5) # Wait before retrying
                # Attempt to re-establish the pubsub connection
                if self.redis:
                    try:
                        self.pubsub = self.redis.pubsub()
                        channels = list(self.subscribers.keys())
                        if channels:
                            await self.pubsub.subscribe(*channels)
                            logger.info(f"Re-subscribed to channels: {channels}")
                    except Exception as sub_e:
                        logger.error(f"Failed to re-subscribe after connection error: {sub_e}")

    async def stop_listening(self):
        """Stop listening for messages"""
        self._running = False
        if self.pubsub:
            await self.pubsub.unsubscribe()
        
        # Stop health check loop
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        logger.info("Stopped listening for messages")
    
    async def _health_check_loop(self):
        """Periodically check Redis connection and reconnect if necessary."""
        while self._running:
            await asyncio.sleep(30) # Check every 30 seconds
            is_healthy = await self.health_check()
            if not is_healthy:
                logger.warning("Redis connection lost. Attempting to reconnect...")
                try:
                    await self.connect()
                    # Re-subscribe to channels
                    if self.subscribers:
                        channels = list(self.subscribers.keys())
                        # This is a simplified re-subscription. A more robust
                        # implementation would re-apply the original handlers.
                        await self.pubsub.subscribe(*channels)
                        logger.info(f"Re-subscribed to channels: {channels}")
                except Exception as e:
                    logger.error(f"Failed to reconnect to Redis: {e}")

    async def _handle_message(self, message: Dict[str, Any]):
        """Handle incoming message from Redis"""
        try:
            channel = message["channel"]
            data = message["data"]
            
            # Deserialize message
            message_data = json.loads(data)
            message_type = message_data.get("message_type")
            
            # Route to appropriate handler
            if channel in self.subscribers:
                for handler in self.subscribers[channel]:
                    try:
                        await handler(channel, message_data)
                    except Exception as e:
                        logger.error(f"Error in message handler for {channel}: {e}")
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def health_check(self) -> bool:
        """Check Redis connection health"""
        try:
            if not self.redis:
                return False
            await self.redis.ping()
            return True
        except Exception:
            return False


# Message channel constants
class Channels:
    """Redis channel names for inter-service communication"""
    
    # Call lifecycle
    CALLS_NEW = "calls:new"
    CALLS_ENDED = "calls:ended"
    
    # Media processing
    MEDIA_CHUNK_RAW = "media:chunk:raw"
    STT_TRANSCRIPTION_COMPLETE = "stt:transcription:complete"
    
    # AI processing
    LLM_RESPONSE_READY = "llm:response:ready"
    TTS_SYNTHESIS_COMPLETE = "tts:synthesis:complete"
    
    # Call control
    CALLS_CONTROL_PLAY = "calls:control:play"
    CALLS_CONTROL_STOP = "calls:control:stop"
    
    # VAD and barge-in
    VAD_ACTIVITY = "vad:activity"
    
    # Error handling
    ERRORS = "errors"


# Global Redis instance
_redis_queue: Optional[RedisMessageQueue] = None


async def get_redis_queue(redis_url: str = "redis://redis:6379") -> RedisMessageQueue:
    """Get or create global Redis message queue instance"""
    global _redis_queue
    
    if _redis_queue is None:
        _redis_queue = RedisMessageQueue(redis_url)
        await _redis_queue.connect()
    
    return _redis_queue


async def cleanup_redis_queue():
    """Cleanup global Redis queue instance"""
    global _redis_queue
    
    if _redis_queue:
        await _redis_queue.disconnect()
        _redis_queue = None


if __name__ == "__main__":
    # Test Redis connection and message publishing
    async def test_redis():
        redis_queue = RedisMessageQueue()
        
        try:
            await redis_queue.connect()
            
            # Test message
            test_message = CallNewMessage(
                message_id="test-123",
                source_service="test",
                call_id="call-123",
                channel_id="channel-123",
                caller_id="+1234567890"
            )
            
            # Publish test message
            subscribers = await redis_queue.publish(Channels.CALLS_NEW, test_message)
            print(f"✅ Published test message, {subscribers} subscribers")
            
            # Health check
            health = await redis_queue.health_check()
            print(f"✅ Redis health check: {health}")
            
        except Exception as e:
            print(f"❌ Redis test failed: {e}")
        finally:
            await redis_queue.disconnect()
    
    # Run test
    asyncio.run(test_redis())
