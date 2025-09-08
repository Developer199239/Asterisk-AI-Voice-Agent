"""
OpenAI Client Wrapper for LLM Service

This module provides a wrapper around OpenAI's API for the LLM service,
supporting both GPT-4o and GPT-3.5-turbo with fallback capabilities.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

import openai
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class ModelType(Enum):
    """Supported OpenAI models."""
    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_3_5_TURBO = "gpt-3.5-turbo"


@dataclass
class LLMConfig:
    """Configuration for LLM client."""
    # API settings
    api_key: str
    base_url: Optional[str] = None
    
    # Model settings
    primary_model: ModelType = ModelType.GPT_4O
    fallback_model: ModelType = ModelType.GPT_3_5_TURBO
    temperature: float = 0.8
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    
    # Response settings
    enable_streaming: bool = True
    timeout: int = 30
    
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0
    backoff_factor: float = 2.0


@dataclass
class LLMResponse:
    """LLM response structure."""
    content: str
    model_used: str
    tokens_used: int
    finish_reason: str
    response_time_ms: int
    is_streaming: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMError:
    """LLM error structure."""
    error_type: str
    error_message: str
    model_attempted: str
    retry_count: int
    timestamp: float = field(default_factory=time.time)


class OpenAIClient:
    """
    OpenAI client wrapper with fallback support and error handling.
    
    Provides a unified interface for OpenAI's API with automatic fallback
    from primary to fallback model on failures.
    """
    
    def __init__(self, config: LLMConfig):
        """Initialize the OpenAI client."""
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout
        )
        
        # Statistics
        self.stats = {
            'requests_total': 0,
            'requests_successful': 0,
            'requests_failed': 0,
            'fallback_used': 0,
            'tokens_used': 0,
            'average_response_time_ms': 0,
            'errors_by_type': {},
            'model_usage': {}
        }
        
        # Response tracking
        self._response_times: List[float] = []
    
    async def generate_response(self, messages: List[Dict[str, str]], 
                              model: Optional[ModelType] = None,
                              stream: bool = None) -> LLMResponse:
        """Generate a response using the specified or primary model."""
        try:
            self.stats['requests_total'] += 1
            
            # Determine model to use
            if model is None:
                model = self.config.primary_model
            
            # Determine streaming
            if stream is None:
                stream = self.config.enable_streaming
            
            # Generate response with retry logic
            response = await self._generate_with_retry(messages, model, stream)
            
            # Update statistics
            self.stats['requests_successful'] += 1
            self.stats['tokens_used'] += response.tokens_used
            self.stats['model_usage'][response.model_used] = \
                self.stats['model_usage'].get(response.model_used, 0) + 1
            
            # Track response time
            self._response_times.append(response.response_time_ms)
            if len(self._response_times) > 100:  # Keep last 100 response times
                self._response_times = self._response_times[-100:]
            
            self.stats['average_response_time_ms'] = sum(self._response_times) / len(self._response_times)
            
            logger.info(f"Generated response using {response.model_used}: "
                       f"{response.tokens_used} tokens, {response.response_time_ms}ms")
            
            return response
            
        except Exception as e:
            self.stats['requests_failed'] += 1
            self._track_error("generation_error", str(e), model.value if model else "unknown")
            
            logger.error(f"Failed to generate response: {e}")
            raise
    
    async def generate_streaming_response(self, messages: List[Dict[str, str]], 
                                        model: Optional[ModelType] = None) -> AsyncGenerator[str, None]:
        """Generate a streaming response."""
        try:
            self.stats['requests_total'] += 1
            
            # Determine model to use
            if model is None:
                model = self.config.primary_model
            
            # Generate streaming response with retry logic
            async for chunk in self._generate_streaming_with_retry(messages, model):
                yield chunk
            
            # Update statistics
            self.stats['requests_successful'] += 1
            
        except Exception as e:
            self.stats['requests_failed'] += 1
            self._track_error("streaming_error", str(e), model.value if model else "unknown")
            
            logger.error(f"Failed to generate streaming response: {e}")
            raise
    
    async def _generate_with_retry(self, messages: List[Dict[str, str]], 
                                 model: ModelType, stream: bool) -> LLMResponse:
        """Generate response with retry logic and fallback."""
        last_error = None
        models_to_try = [model]
        
        # Add fallback model if different from primary
        if model != self.config.fallback_model:
            models_to_try.append(self.config.fallback_model)
        
        for attempt, current_model in enumerate(models_to_try):
            try:
                start_time = time.time()
                
                if stream:
                    # For streaming, collect all chunks
                    content_parts = []
                    tokens_used = 0
                    finish_reason = "stop"
                    
                    async for chunk in self._generate_streaming_with_retry(messages, current_model):
                        content_parts.append(chunk)
                    
                    content = "".join(content_parts)
                else:
                    # Non-streaming response
                    response = await self.client.chat.completions.create(
                        model=current_model.value,
                        messages=messages,
                        temperature=self.config.temperature,
                        max_tokens=self.config.max_tokens,
                        top_p=self.config.top_p,
                        frequency_penalty=self.config.frequency_penalty,
                        presence_penalty=self.config.presence_penalty,
                        stream=False
                    )
                    
                    content = response.choices[0].message.content or ""
                    tokens_used = response.usage.total_tokens if response.usage else 0
                    finish_reason = response.choices[0].finish_reason or "stop"
                
                response_time_ms = int((time.time() - start_time) * 1000)
                
                # Track fallback usage
                if current_model != model:
                    self.stats['fallback_used'] += 1
                
                return LLMResponse(
                    content=content,
                    model_used=current_model.value,
                    tokens_used=tokens_used,
                    finish_reason=finish_reason,
                    response_time_ms=response_time_ms,
                    is_streaming=stream
                )
                
            except Exception as e:
                last_error = e
                self._track_error("api_error", str(e), current_model.value)
                
                logger.warning(f"Attempt {attempt + 1} failed with model {current_model.value}: {e}")
                
                # If this is not the last model to try, wait before retrying
                if attempt < len(models_to_try) - 1:
                    delay = self.config.retry_delay * (self.config.backoff_factor ** attempt)
                    await asyncio.sleep(delay)
        
        # All models failed
        raise last_error or Exception("All model attempts failed")
    
    async def _generate_streaming_with_retry(self, messages: List[Dict[str, str]], 
                                           model: ModelType) -> AsyncGenerator[str, None]:
        """Generate streaming response with retry logic."""
        last_error = None
        models_to_try = [model]
        
        # Add fallback model if different from primary
        if model != self.config.fallback_model:
            models_to_try.append(self.config.fallback_model)
        
        for attempt, current_model in enumerate(models_to_try):
            try:
                response = await self.client.chat.completions.create(
                    model=current_model.value,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    top_p=self.config.top_p,
                    frequency_penalty=self.config.frequency_penalty,
                    presence_penalty=self.config.presence_penalty,
                    stream=True
                )
                
                # Track fallback usage
                if current_model != model:
                    self.stats['fallback_used'] += 1
                
                # Stream the response
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                
                return
                
            except Exception as e:
                last_error = e
                self._track_error("streaming_api_error", str(e), current_model.value)
                
                logger.warning(f"Streaming attempt {attempt + 1} failed with model {current_model.value}: {e}")
                
                # If this is not the last model to try, wait before retrying
                if attempt < len(models_to_try) - 1:
                    delay = self.config.retry_delay * (self.config.backoff_factor ** attempt)
                    await asyncio.sleep(delay)
        
        # All models failed
        raise last_error or Exception("All streaming model attempts failed")
    
    def _track_error(self, error_type: str, error_message: str, model: str):
        """Track error statistics."""
        self.stats['errors_by_type'][error_type] = \
            self.stats['errors_by_type'].get(error_type, 0) + 1
        
        logger.error(f"LLM Error [{error_type}] with {model}: {error_message}")
    
    async def test_connection(self) -> bool:
        """Test the OpenAI API connection."""
        try:
            response = await self.client.chat.completions.create(
                model=self.config.primary_model.value,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            
            logger.info("OpenAI API connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"OpenAI API connection test failed: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            **self.stats,
            'success_rate': (
                self.stats['requests_successful'] / max(self.stats['requests_total'], 1)
            ) * 100,
            'fallback_rate': (
                self.stats['fallback_used'] / max(self.stats['requests_successful'], 1)
            ) * 100
        }
    
    async def close(self):
        """Close the client."""
        try:
            await self.client.close()
            logger.info("OpenAI client closed")
        except Exception as e:
            logger.error(f"Error closing OpenAI client: {e}")
