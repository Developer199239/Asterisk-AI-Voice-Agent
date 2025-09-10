"""
Conversation Context Manager for LLM Service

This module manages conversation history and context for the LLM service,
providing Redis-based storage with channel ID isolation and token management.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import tiktoken
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ConversationState(Enum):
    """Conversation states."""
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"
    ERROR = "error"


@dataclass
class ConversationConfig:
    """Configuration for conversation management."""
    # Redis settings
    redis_url: str = "redis://localhost:6379"
    conversation_ttl: int = 3600  # 1 hour default
    
    # Token management
    max_tokens: int = 4000
    token_buffer: int = 200  # Buffer for system messages
    
    # Context management
    max_messages: int = 50
    system_message: str = "You are a helpful AI assistant for Jugaar LLC."
    
    # Cleanup settings
    cleanup_interval: int = 300  # 5 minutes
    inactive_timeout: int = 1800  # 30 minutes


@dataclass
class ConversationMessage:
    """Individual conversation message."""
    role: str  # "system", "user", "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationContext:
    """Complete conversation context for a channel."""
    channel_id: str
    conversation_id: str
    state: ConversationState = ConversationState.ACTIVE
    messages: List[ConversationMessage] = field(default_factory=list)
    total_tokens: int = 0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConversationManager:
    """
    Manages conversation context and history for the LLM service.
    
    Provides Redis-based storage with channel ID isolation, token management,
    and automatic cleanup of expired conversations.
    """
    
    def __init__(self, config: ConversationConfig):
        """Initialize the conversation manager."""
        self.config = config
        self.redis_client: Optional[Redis] = None
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        
        # In-memory cache for active conversations
        self.active_conversations: Dict[str, ConversationContext] = {}
        
        # Statistics
        self.stats = {
            'conversations_created': 0,
            'conversations_ended': 0,
            'messages_processed': 0,
            'tokens_processed': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'redis_errors': 0
        }
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start the conversation manager."""
        try:
            # Initialize Redis client
            self.redis_client = Redis.from_url(self.config.redis_url, decode_responses=True)
            
            # Test Redis connection
            await self.redis_client.ping()
            
            # Start cleanup task
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            
            logger.info("Conversation manager started")
            
        except Exception as e:
            logger.error(f"Failed to start conversation manager: {e}")
            raise
    
    async def stop(self):
        """Stop the conversation manager."""
        try:
            self._running = False
            
            if self._cleanup_task:
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
            
            if self.redis_client:
                await self.redis_client.close()
            
            logger.info("Conversation manager stopped")
            
        except Exception as e:
            logger.error(f"Error stopping conversation manager: {e}")
    
    async def create_conversation(self, channel_id: str, conversation_id: str = None) -> ConversationContext:
        """Create a new conversation context."""
        try:
            if conversation_id is None:
                conversation_id = f"conv_{channel_id}_{int(time.time())}"
            
            # Check if conversation already exists
            existing = await self.get_conversation(channel_id)
            if existing:
                logger.warning(f"Conversation already exists for channel {channel_id}")
                return existing
            
            # Create new conversation context
            context = ConversationContext(
                channel_id=channel_id,
                conversation_id=conversation_id,
                state=ConversationState.ACTIVE
            )
            
            # Add system message
            system_msg = ConversationMessage(
                role="system",
                content=self.config.system_message,
                tokens=self._count_tokens(self.config.system_message)
            )
            context.messages.append(system_msg)
            context.total_tokens = system_msg.tokens
            
            # Store in Redis
            await self._store_conversation(context)
            
            # Cache in memory
            self.active_conversations[channel_id] = context
            
            self.stats['conversations_created'] += 1
            
            logger.info(f"Created conversation {conversation_id} for channel {channel_id}")
            
            return context
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Failed to create conversation: {e}")
            raise
    
    async def get_conversation(self, channel_id: str) -> Optional[ConversationContext]:
        """Get conversation context for a channel."""
        try:
            # Check cache first
            if channel_id in self.active_conversations:
                self.stats['cache_hits'] += 1
                return self.active_conversations[channel_id]
            
            # Load from Redis
            self.stats['cache_misses'] += 1
            context = await self._load_conversation(channel_id)
            
            if context:
                # Cache in memory
                self.active_conversations[channel_id] = context
            
            return context
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Failed to get conversation for channel {channel_id}: {e}")
            return None
    
    async def add_message(self, channel_id: str, role: str, content: str, 
                         metadata: Dict[str, Any] = None) -> bool:
        """Add a message to the conversation."""
        try:
            # Get conversation context
            context = await self.get_conversation(channel_id)
            if not context:
                logger.error(f"No conversation found for channel {channel_id}")
                return False
            
            # Count tokens for the new message
            message_tokens = self._count_tokens(content)
            
            # Check if adding this message would exceed token limit
            if context.total_tokens + message_tokens > self.config.max_tokens - self.config.token_buffer:
                # Truncate conversation to make room
                await self._truncate_conversation(context, message_tokens)
            
            # Create message
            message = ConversationMessage(
                role=role,
                content=content,
                tokens=message_tokens,
                metadata=metadata or {}
            )
            
            # Add to context
            context.messages.append(message)
            context.total_tokens += message_tokens
            context.last_activity = time.time()
            
            # Store in Redis
            await self._store_conversation(context)
            
            self.stats['messages_processed'] += 1
            self.stats['tokens_processed'] += message_tokens
            
            logger.debug(f"Added message to channel {channel_id}: {role} - {content[:50]}...")
            
            return True
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Failed to add message to channel {channel_id}: {e}")
            return False
    
    async def get_conversation_history(self, channel_id: str, 
                                     max_messages: int = None) -> List[Dict[str, str]]:
        """Get conversation history for a channel."""
        try:
            context = await self.get_conversation(channel_id)
            if not context:
                return []
            
            # Convert to OpenAI format
            history = []
            messages = context.messages
            
            if max_messages:
                messages = messages[-max_messages:]
            
            for msg in messages:
                history.append({
                    "role": msg.role,
                    "content": msg.content
                })
            
            return history
            
        except Exception as e:
            logger.error(f"Failed to get conversation history for channel {channel_id}: {e}")
            return []
    
    async def end_conversation(self, channel_id: str) -> bool:
        """End a conversation."""
        try:
            context = await self.get_conversation(channel_id)
            if not context:
                return False
            
            # Update state
            context.state = ConversationState.ENDED
            context.last_activity = time.time()
            
            # Store in Redis
            await self._store_conversation(context)
            
            # Remove from cache
            if channel_id in self.active_conversations:
                del self.active_conversations[channel_id]
            
            self.stats['conversations_ended'] += 1
            
            logger.info(f"Ended conversation for channel {channel_id}")
            
            return True
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Failed to end conversation for channel {channel_id}: {e}")
            return False
    
    async def clear_conversation(self, channel_id: str) -> bool:
        """Clear conversation history for a channel."""
        try:
            # Remove from Redis
            await self.redis_client.delete(f"conversation:{channel_id}")
            
            # Remove from cache
            if channel_id in self.active_conversations:
                del self.active_conversations[channel_id]
            
            logger.info(f"Cleared conversation for channel {channel_id}")
            
            return True
            
        except Exception as e:
            self.stats['redis_errors'] += 1
            logger.error(f"Failed to clear conversation for channel {channel_id}: {e}")
            return False
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        try:
            return len(self.tokenizer.encode(text))
        except Exception as e:
            logger.error(f"Error counting tokens: {e}")
            # Fallback estimation: ~4 characters per token
            return len(text) // 4
    
    async def _truncate_conversation(self, context: ConversationContext, 
                                   required_tokens: int) -> None:
        """Truncate conversation to make room for new message."""
        try:
            # Keep system message and recent messages
            system_msg = None
            if context.messages and context.messages[0].role == "system":
                system_msg = context.messages.pop(0)
            
            # Calculate how many tokens we need to remove
            target_tokens = self.config.max_tokens - self.config.token_buffer - required_tokens
            
            # Remove oldest messages until we're under the target
            while context.messages and context.total_tokens > target_tokens:
                removed_msg = context.messages.pop(0)
                context.total_tokens -= removed_msg.tokens
            
            # Re-add system message at the beginning
            if system_msg:
                context.messages.insert(0, system_msg)
                context.total_tokens += system_msg.tokens
            
            logger.debug(f"Truncated conversation for channel {context.channel_id}: "
                        f"{context.total_tokens} tokens")
            
        except Exception as e:
            logger.error(f"Error truncating conversation: {e}")
    
    async def _store_conversation(self, context: ConversationContext) -> None:
        """Store conversation context in Redis."""
        try:
            # Convert to JSON-serializable format
            data = {
                'channel_id': context.channel_id,
                'conversation_id': context.conversation_id,
                'state': context.state.value,
                'messages': [
                    {
                        'role': msg.role,
                        'content': msg.content,
                        'timestamp': msg.timestamp,
                        'tokens': msg.tokens,
                        'metadata': msg.metadata
                    }
                    for msg in context.messages
                ],
                'total_tokens': context.total_tokens,
                'created_at': context.created_at,
                'last_activity': context.last_activity,
                'metadata': context.metadata
            }
            
            # Store with TTL
            key = f"conversation:{context.channel_id}"
            await self.redis_client.setex(
                key, 
                self.config.conversation_ttl, 
                json.dumps(data)
            )
            
        except Exception as e:
            logger.error(f"Error storing conversation: {e}")
            raise
    
    async def _load_conversation(self, channel_id: str) -> Optional[ConversationContext]:
        """Load conversation context from Redis."""
        try:
            key = f"conversation:{channel_id}"
            data = await self.redis_client.get(key)
            
            if not data:
                return None
            
            # Parse JSON data
            data = json.loads(data)
            
            # Reconstruct conversation context
            context = ConversationContext(
                channel_id=data['channel_id'],
                conversation_id=data['conversation_id'],
                state=ConversationState(data['state']),
                total_tokens=data['total_tokens'],
                created_at=data['created_at'],
                last_activity=data['last_activity'],
                metadata=data['metadata']
            )
            
            # Reconstruct messages
            for msg_data in data['messages']:
                message = ConversationMessage(
                    role=msg_data['role'],
                    content=msg_data['content'],
                    timestamp=msg_data['timestamp'],
                    tokens=msg_data['tokens'],
                    metadata=msg_data['metadata']
                )
                context.messages.append(message)
            
            return context
            
        except Exception as e:
            logger.error(f"Error loading conversation: {e}")
            return None
    
    async def _cleanup_loop(self):
        """Background cleanup loop for expired conversations."""
        while self._running:
            try:
                await asyncio.sleep(self.config.cleanup_interval)
                
                if not self._running:
                    break
                
                # Clean up inactive conversations from cache
                current_time = time.time()
                inactive_channels = []
                
                for channel_id, context in self.active_conversations.items():
                    if (current_time - context.last_activity) > self.config.inactive_timeout:
                        inactive_channels.append(channel_id)
                
                for channel_id in inactive_channels:
                    del self.active_conversations[channel_id]
                    logger.debug(f"Cleaned up inactive conversation for channel {channel_id}")
                
                logger.debug(f"Cleanup completed: {len(inactive_channels)} conversations removed")
                
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get conversation manager statistics."""
        return {
            **self.stats,
            'active_conversations': len(self.active_conversations),
            'cache_size': len(self.active_conversations)
        }
