"""
OpenAI Realtime API Large Language Model (LLM) Handler

This module provides specialized functionality for streaming LLM operations
using the OpenAI Realtime API.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from .realtime_client import RealtimeClient, RealtimeConfig, VoiceType

logger = logging.getLogger(__name__)


class LLMState(Enum):
    """LLM processing states."""
    IDLE = "idle"
    PROCESSING = "processing"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ERROR = "error"


class ResponseType(Enum):
    """Types of LLM responses."""
    TEXT = "text"
    AUDIO = "audio"
    MIXED = "mixed"


@dataclass
class LLMConfig:
    """Configuration for LLM handler."""
    # Model settings
    model: str = "gpt-4o-realtime-preview-2024-10-01"
    temperature: float = 0.8
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    
    # Response settings
    response_type: ResponseType = ResponseType.MIXED
    enable_streaming: bool = True
    enable_audio_response: bool = True
    enable_text_response: bool = True
    
    # Conversation settings
    system_instructions: str = "You are a helpful AI assistant for Jugaar LLC."
    conversation_context: List[Dict[str, str]] = field(default_factory=list)
    max_context_length: int = 50  # Maximum number of conversation turns
    
    # Callback settings
    on_text_chunk: Optional[Callable[[str], None]] = None
    on_audio_chunk: Optional[Callable[[bytes], None]] = None
    on_response_start: Optional[Callable[[], None]] = None
    on_response_complete: Optional[Callable[[Dict[str, Any]], None]] = None
    on_error: Optional[Callable[[str, Exception], None]] = None
    
    # Logging
    enable_logging: bool = True
    log_level: str = "INFO"


@dataclass
class LLMResponse:
    """LLM response structure."""
    text: str = ""
    audio_data: bytes = b""
    response_type: ResponseType = ResponseType.TEXT
    is_complete: bool = False
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 0
    tokens_used: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class LLMHandler:
    """
    Large Language Model handler using OpenAI Realtime API.
    
    This handler manages the streaming LLM process, including conversation
    management, response generation, and streaming text/audio output.
    """
    
    def __init__(self, config: LLMConfig, realtime_client: RealtimeClient):
        """Initialize the LLM handler."""
        self.config = config
        self.client = realtime_client
        self.state = LLMState.IDLE
        
        # Response management
        self.current_response = LLMResponse()
        self.response_buffer = ""
        self.audio_buffer = b""
        
        # Conversation management
        self.conversation_history: List[Dict[str, str]] = []
        self.current_conversation_id: Optional[str] = None
        
        # Statistics
        self.stats = {
            'requests_processed': 0,
            'responses_completed': 0,
            'text_chunks_received': 0,
            'audio_chunks_received': 0,
            'total_tokens_used': 0,
            'average_response_time_ms': 0,
            'errors': 0,
            'conversations_started': 0
        }
        
        # Response tracking
        self._is_responding = False
        self.response_start_time = 0
        self.last_activity_time = 0
        
        # Setup client callbacks
        self._setup_client_callbacks()
    
    def _setup_client_callbacks(self):
        """Setup callbacks for the Realtime client."""
        self.client.on_transcript = self._handle_text_chunk
        self.client.on_audio = self._handle_audio_chunk
        self.client.on_response_done = self._handle_response_complete
        self.client.on_error = self._handle_error
    
    async def start_conversation(self, conversation_id: str = None) -> bool:
        """Start a new conversation session."""
        try:
            if self.state != LLMState.IDLE:
                logger.warning("LLM handler is not in IDLE state")
                return False
            
            if not self.client.is_connected:
                logger.error("Realtime client is not connected")
                return False
            
            # Initialize session if not already done
            if not self.client.session_id:
                session_initialized = await self.client.initialize_session()
                if not session_initialized:
                    logger.error("Failed to initialize session")
                    return False
            
            # Set conversation ID
            self.current_conversation_id = conversation_id or f"conv_{int(time.time())}"
            
            # Clear conversation history
            self.conversation_history.clear()
            
            # Add system instructions
            if self.config.system_instructions:
                self.conversation_history.append({
                    "role": "system",
                    "content": self.config.system_instructions
                })
            
            self.state = LLMState.IDLE
            self.stats['conversations_started'] += 1
            
            if self.config.enable_logging:
                logger.info(f"Conversation started: {self.current_conversation_id}")
            
            return True
            
        except Exception as e:
            self.state = LLMState.ERROR
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Failed to start conversation: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Failed to start conversation: {e}", e)
                else:
                    self.config.on_error(f"Failed to start conversation: {e}", e)
            
            return False
    
    async def send_message(self, message: str, role: str = "user") -> bool:
        """Send a message to the LLM."""
        try:
            if self.state == LLMState.ERROR:
                logger.error("LLM handler is in ERROR state")
                return False
            
            if not self.client.is_connected:
                logger.error("Realtime client is not connected")
                return False
            
            # Add message to conversation history
            self.conversation_history.append({
                "role": role,
                "content": message
            })
            
            # Trim conversation history if too long
            if len(self.conversation_history) > self.config.max_context_length:
                # Keep system message and recent messages
                system_msg = None
                if self.conversation_history[0]["role"] == "system":
                    system_msg = self.conversation_history.pop(0)
                
                # Keep last max_context_length - 1 messages (excluding system message)
                keep_count = self.config.max_context_length - 1
                self.conversation_history = self.conversation_history[-keep_count:]
                
                if system_msg:
                    self.conversation_history.insert(0, system_msg)
            
            # Send message to Realtime API
            success = await self.client.send_text_message(message)
            if not success:
                logger.error("Failed to send message to Realtime API")
                return False
            
            self.stats['requests_processed'] += 1
            self.last_activity_time = time.time()
            
            if self.config.enable_logging:
                logger.info(f"Message sent: {message[:50]}...")
            
            return True
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error sending message: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Message sending error: {e}", e)
                else:
                    self.config.on_error(f"Message sending error: {e}", e)
            
            return False
    
    async def create_response(self, modalities: List[str] = None) -> bool:
        """Create a response from the LLM."""
        try:
            if self.state == LLMState.ERROR:
                logger.error("LLM handler is in ERROR state")
                return False
            
            if not self.client.is_connected:
                logger.error("Realtime client is not connected")
                return False
            
            # Determine response modalities
            if modalities is None:
                modalities = []
                if self.config.enable_text_response:
                    modalities.append("text")
                if self.config.enable_audio_response:
                    modalities.append("audio")
            
            # Create response
            success = await self.client.create_response(modalities)
            if not success:
                logger.error("Failed to create response")
                return False
            
            # Update state
            self.state = LLMState.PROCESSING
            self._is_responding = True
            self.response_start_time = time.time()
            
            # Reset response buffers
            self.current_response = LLMResponse()
            self.response_buffer = ""
            self.audio_buffer = b""
            
            # Call response start callback
            if self.config.on_response_start:
                if asyncio.iscoroutinefunction(self.config.on_response_start):
                    await self.config.on_response_start()
                else:
                    self.config.on_response_start()
            
            if self.config.enable_logging:
                logger.info(f"Response creation started with modalities: {modalities}")
            
            return True
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error creating response: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Response creation error: {e}", e)
                else:
                    self.config.on_error(f"Response creation error: {e}", e)
            
            return False
    
    async def cancel_response(self) -> bool:
        """Cancel the current response."""
        try:
            if not self._is_responding:
                logger.warning("No response in progress")
                return False
            
            # Cancel response via client
            success = await self.client.cancel_response()
            if not success:
                logger.error("Failed to cancel response")
                return False
            
            # Update state
            self.state = LLMState.IDLE
            self._is_responding = False
            
            if self.config.enable_logging:
                logger.info("Response cancelled")
            
            return True
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error cancelling response: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Response cancellation error: {e}", e)
                else:
                    self.config.on_error(f"Response cancellation error: {e}", e)
            
            return False
    
    async def _handle_text_chunk(self, text: str):
        """Handle text chunk from Realtime API."""
        try:
            if not text:
                return
            
            # Update response buffer
            self.response_buffer += text
            self.current_response.text = self.response_buffer
            
            # Update statistics
            self.stats['text_chunks_received'] += 1
            self.last_activity_time = time.time()
            
            # Update state to streaming
            if self.state == LLMState.PROCESSING:
                self.state = LLMState.STREAMING
            
            # Call text chunk callback
            if self.config.on_text_chunk:
                if asyncio.iscoroutinefunction(self.config.on_text_chunk):
                    await self.config.on_text_chunk(text)
                else:
                    self.config.on_text_chunk(text)
            
            if self.config.enable_logging:
                logger.debug(f"Text chunk received: {text}")
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error handling text chunk: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Text chunk handling error: {e}", e)
                else:
                    self.config.on_error(f"Text chunk handling error: {e}", e)
    
    async def _handle_audio_chunk(self, audio_data: bytes):
        """Handle audio chunk from Realtime API."""
        try:
            if not audio_data:
                return
            
            # Update audio buffer
            self.audio_buffer += audio_data
            self.current_response.audio_data = self.audio_buffer
            
            # Update statistics
            self.stats['audio_chunks_received'] += 1
            self.last_activity_time = time.time()
            
            # Update state to streaming
            if self.state == LLMState.PROCESSING:
                self.state = LLMState.STREAMING
            
            # Call audio chunk callback
            if self.config.on_audio_chunk:
                if asyncio.iscoroutinefunction(self.config.on_audio_chunk):
                    await self.config.on_audio_chunk(audio_data)
                else:
                    self.config.on_audio_chunk(audio_data)
            
            if self.config.enable_logging:
                logger.debug(f"Audio chunk received: {len(audio_data)} bytes")
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error handling audio chunk: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Audio chunk handling error: {e}", e)
                else:
                    self.config.on_error(f"Audio chunk handling error: {e}", e)
    
    async def _handle_response_complete(self, response_data: Dict[str, Any]):
        """Handle response completion from Realtime API."""
        try:
            # Update response
            self.current_response.is_complete = True
            self.current_response.duration_ms = int((time.time() - self.response_start_time) * 1000)
            
            # Extract usage information
            usage = response_data.get('usage', {})
            self.current_response.tokens_used = usage.get('total_tokens', 0)
            self.current_response.metadata = response_data
            
            # Update statistics
            self.stats['responses_completed'] += 1
            self.stats['total_tokens_used'] += self.current_response.tokens_used
            
            # Calculate average response time
            if self.stats['responses_completed'] > 0:
                total_time = self.current_response.duration_ms
                self.stats['average_response_time_ms'] = total_time / self.stats['responses_completed']
            
            # Add response to conversation history
            if self.current_response.text:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": self.current_response.text
                })
            
            # Update state
            self.state = LLMState.COMPLETED
            self._is_responding = False
            
            # Call response complete callback
            if self.config.on_response_complete:
                if asyncio.iscoroutinefunction(self.config.on_response_complete):
                    await self.config.on_response_complete(response_data)
                else:
                    self.config.on_response_complete(response_data)
            
            if self.config.enable_logging:
                logger.info(f"Response completed: {len(self.current_response.text)} chars, {self.current_response.tokens_used} tokens")
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error handling response completion: {e}")
            
            if self.config.on_error:
                if asyncio.iscoroutinefunction(self.config.on_error):
                    await self.config.on_error(f"Response completion error: {e}", e)
                else:
                    self.config.on_error(f"Response completion error: {e}", e)
    
    async def _handle_error(self, error_message: str, error: Exception):
        """Handle errors from the Realtime client."""
        self.stats['errors'] += 1
        self.state = LLMState.ERROR
        self._is_responding = False
        
        if self.config.enable_logging:
            logger.error(f"LLM error: {error_message}")
        
        if self.config.on_error:
            if asyncio.iscoroutinefunction(self.config.on_error):
                await self.config.on_error(error_message, error)
            else:
                self.config.on_error(error_message, error)
    
    def get_current_response(self) -> LLMResponse:
        """Get the current response."""
        return self.current_response
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get the conversation history."""
        return self.conversation_history.copy()
    
    def clear_conversation(self):
        """Clear the conversation history."""
        self.conversation_history.clear()
        if self.config.system_instructions:
            self.conversation_history.append({
                "role": "system",
                "content": self.config.system_instructions
            })
    
    def is_processing(self) -> bool:
        """Check if the handler is currently processing."""
        return self.state in [LLMState.PROCESSING, LLMState.STREAMING]
    
    def is_responding(self) -> bool:
        """Check if the handler is currently responding."""
        return self._is_responding
    
    def get_stats(self) -> Dict[str, Any]:
        """Get LLM handler statistics."""
        stats = self.stats.copy()
        stats['state'] = self.state.value
        stats['is_processing'] = self.is_processing()
        stats['is_responding'] = self.is_responding()
        stats['conversation_id'] = self.current_conversation_id
        stats['conversation_length'] = len(self.conversation_history)
        stats['current_response_length'] = len(self.current_response.text)
        stats['current_audio_length'] = len(self.current_response.audio_data)
        
        return stats
    
    async def reset(self):
        """Reset the LLM handler to initial state."""
        try:
            # Cancel any ongoing response
            if self._is_responding:
                await self.cancel_response()
            
            # Clear all data
            self.current_response = LLMResponse()
            self.response_buffer = ""
            self.audio_buffer = ""
            self.conversation_history.clear()
            self.current_conversation_id = None
            
            # Reset state
            self.state = LLMState.IDLE
            self._is_responding = False
            self.response_start_time = 0
            self.last_activity_time = 0
            
            if self.config.enable_logging:
                logger.info("LLM handler reset")
            
        except Exception as e:
            if self.config.enable_logging:
                logger.error(f"Error resetting LLM handler: {e}")


class LLMManager:
    """
    Manager for multiple LLM handlers.
    
    This class manages multiple LLM handlers for different conversations or sessions.
    """
    
    def __init__(self):
        """Initialize the LLM manager."""
        self.handlers: Dict[str, LLMHandler] = {}
        self.default_config = LLMConfig()
    
    def create_handler(self, handler_id: str, config: LLMConfig = None, 
                      realtime_client: RealtimeClient = None) -> LLMHandler:
        """Create a new LLM handler."""
        if handler_id in self.handlers:
            raise ValueError(f"Handler {handler_id} already exists")
        
        if config is None:
            config = self.default_config
        
        if realtime_client is None:
            raise ValueError("RealtimeClient is required")
        
        handler = LLMHandler(config, realtime_client)
        self.handlers[handler_id] = handler
        
        return handler
    
    def get_handler(self, handler_id: str) -> Optional[LLMHandler]:
        """Get an LLM handler by ID."""
        return self.handlers.get(handler_id)
    
    def remove_handler(self, handler_id: str) -> bool:
        """Remove an LLM handler."""
        if handler_id in self.handlers:
            del self.handlers[handler_id]
            return True
        return False
    
    def get_all_handlers(self) -> Dict[str, LLMHandler]:
        """Get all LLM handlers."""
        return self.handlers.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all handlers."""
        stats = {
            'total_handlers': len(self.handlers),
            'active_handlers': sum(1 for h in self.handlers.values() if h.is_processing()),
            'responding_handlers': sum(1 for h in self.handlers.values() if h.is_responding()),
            'handlers': {}
        }
        
        for handler_id, handler in self.handlers.items():
            stats['handlers'][handler_id] = handler.get_stats()
        
        return stats
