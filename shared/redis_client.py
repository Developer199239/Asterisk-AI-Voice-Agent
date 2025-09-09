"""
Redis Message Queue Infrastructure for Asterisk AI Voice Agent v2.0

This module provides async Redis Pub/Sub functionality for inter-service communication
with connection pooling, retry logic, and message serialization.
"""

import asyncio
import json
from typing import Callable, List, Dict, Any
from enum import Enum
import redis.asyncio as redis
import structlog
from pydantic import BaseModel, Field
import uuid

from shared.config import RedisConfig

logger = structlog.get_logger(__name__)

class Channels(str, Enum):
    CALLS_NEW = "calls:new"
    CALLS_CONTROL_PLAY = "calls:control:play"
    CALLS_CONTROL_STOP = "calls:control:stop"
    STT_TRANSCRIPTION_COMPLETE = "stt:transcription:complete"
    LLM_RESPONSE_READY = "llm:response:ready"

class BaseMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: f"msg-{uuid.uuid4()}")
    source_service: str

class CallNewMessage(BaseMessage):
    call_id: str
    channel_id: str
    caller_id: str
    caller_name: str

class CallControlMessage(BaseMessage):
    call_id: str
    action: str
    parameters: Dict[str, Any] = {}

class RedisMessageQueue:
    def __init__(self, config: RedisConfig):
        self.redis_url = f"redis://{config.host}:{config.port}"
        self.redis: redis.Redis = None
        self.pubsub = None
        self.listening_task = None

    async def connect(self):
        try:
            logger.info("Attempting to connect to Redis...")
            self.redis = redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
            await self.redis.ping()
            logger.info("✅ Successfully connected to Redis.")
        except Exception as e:
            logger.error("Failed to connect to Redis", exc_info=True)
            raise

    async def disconnect(self):
        if self.listening_task:
            self.listening_task.cancel()
        if self.pubsub:
            await self.pubsub.close()
        if self.redis:
            await self.redis.close()
        logger.info("Disconnected from Redis")

    async def publish(self, channel: str, message: BaseModel):
        try:
            message_json = message.model_dump_json()
            num_subscribers = await self.redis.publish(channel, message_json)
            logger.debug(f"Published message to {channel}, {num_subscribers} subscribers", message=message_json)
        except Exception as e:
            logger.error("Failed to publish message", channel=channel, exc_info=True)

    async def subscribe(self, channels: List[str], handler: Callable):
        if not self.redis:
            await self.connect()
        
        self.pubsub = self.redis.pubsub()
        self.handler = handler
        
        # Create a mapping of channel names to the handler
        handler_map = {channel: self._message_handler for channel in channels}
        
        # Subscribe using the handler map
        await self.pubsub.subscribe(**handler_map)
        logger.info("Subscribed to channels", channels=channels)

    async def start_listening(self):
        if not self.pubsub:
            raise RuntimeError("Must subscribe to channels before listening.")
        
        logger.info("Started listening for messages")
        self.listening_task = asyncio.create_task(self._listen())
        try:
            await self.listening_task
        except asyncio.CancelledError:
            logger.info("Listening task cancelled.")

    async def _listen(self):
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    data_str = message["data"]
                    try:
                        data = json.loads(data_str)
                        # We are passing the channel to the handler now
                        await self.handler(channel, data)
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode JSON message", channel=channel, data=data_str)
        except Exception as e:
            logger.error("Error in Redis listen loop", exc_info=True)
    
    async def _message_handler(self, message: Dict[str, Any]):
        """
        Default message handler that's used by pubsub.subscribe.
        It calls the main handler with both channel and data.
        """
        channel = message.get("channel")
        data_str = message.get("data")
        if channel and data_str:
            try:
                data = json.loads(data_str)
                await self.handler(channel, data)
            except json.JSONDecodeError:
                logger.warning("Failed to decode JSON message in handler", channel=channel, data=data_str)

