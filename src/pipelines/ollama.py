"""
Ollama-compatible LLM adapter for free LLM APIs.

This adapter implements the LLMComponent interface for Ollama-style /api/generate
endpoints, specifically designed to work with mlvoca.com's free LLM API.

IMPORTANT LIMITATIONS:
- NO tool/function calling support
- Users must hang up calls manually
- For demo/testing purposes only
- Sign up for OpenAI/Groq API key for full functionality
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Union

import aiohttp

from ..logging_config import get_logger
from .base import Component, LLMComponent, LLMResponse

logger = get_logger(__name__)

# Default free LLM API endpoint (mlvoca.com)
_DEFAULT_BASE_URL = "https://mlvoca.com"
_DEFAULT_MODEL = "deepseek-r1:1.5b"  # or "tinyllama"


class OllamaLLMAdapter(LLMComponent):
    """
    LLM adapter for Ollama-compatible APIs (e.g., mlvoca.com free API).
    
    This adapter does NOT support tool/function calling.
    For production use with tools, use OpenAI or Groq LLM adapters.
    """

    component_key = "free_llm"

    def __init__(
        self,
        app_config: Any,
        pipeline_defaults: Optional[Dict[str, Any]] = None,
    ):
        self._app_config = app_config
        self._pipeline_defaults = pipeline_defaults or {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._sessions: Dict[str, Dict[str, Any]] = {}  # per-call state

    def _compose_options(self, runtime_opts: Dict[str, Any]) -> Dict[str, Any]:
        """Merge pipeline defaults with runtime options."""
        merged = dict(self._pipeline_defaults)
        merged.update(runtime_opts or {})
        
        # Set defaults
        merged.setdefault("base_url", _DEFAULT_BASE_URL)
        merged.setdefault("model", _DEFAULT_MODEL)
        merged.setdefault("temperature", 0.7)
        merged.setdefault("timeout_sec", 30)
        merged.setdefault("stream", False)  # Non-streaming for simplicity
        merged.setdefault("max_tokens", 150)  # Keep responses concise for voice
        
        return merged

    async def start(self) -> None:
        """Initialize the adapter."""
        logger.info(
            "Free LLM adapter initialized (NO TOOL CALLING)",
            base_url=_DEFAULT_BASE_URL,
            model=_DEFAULT_MODEL,
            note="For demo/testing only - user must hang up manually",
        )

    async def stop(self) -> None:
        """Clean up resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._sessions.clear()
        logger.debug("Free LLM adapter stopped")

    async def open_call(self, call_id: str, options: Dict[str, Any]) -> None:
        """Initialize per-call state with conversation history."""
        self._sessions[call_id] = {
            "history": [],  # List of {"role": "user"|"assistant", "content": str}
            "options": self._compose_options(options),
        }
        logger.debug("Free LLM session opened", call_id=call_id)

    async def close_call(self, call_id: str) -> None:
        """Clean up per-call state."""
        if call_id in self._sessions:
            del self._sessions[call_id]
            logger.debug("Free LLM session closed", call_id=call_id)

    async def _ensure_session(self) -> None:
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    def _build_prompt(
        self,
        transcript: str,
        context: Dict[str, Any],
        history: list,
    ) -> str:
        """Build a prompt string from context, history, and current transcript."""
        parts = []
        
        # System prompt
        system_prompt = context.get("system_prompt", "")
        if system_prompt:
            parts.append(f"System: {system_prompt}")
        
        # Add note about no tool calling
        parts.append(
            "Note: You cannot perform actions like hanging up or transferring calls. "
            "Keep responses concise and conversational for voice interaction."
        )
        
        # Conversation history
        for msg in history[-6:]:  # Last 6 messages to keep context manageable
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role}: {msg['content']}")
        
        # Current user input
        parts.append(f"User: {transcript}")
        parts.append("Assistant:")
        
        return "\n\n".join(parts)

    async def generate(
        self,
        call_id: str,
        transcript: str,
        context: Dict[str, Any],
        options: Dict[str, Any],
    ) -> Union[str, LLMResponse]:
        """Generate a response using the Ollama-compatible API."""
        
        # Get or create session state
        if call_id not in self._sessions:
            await self.open_call(call_id, options)
        
        session_state = self._sessions[call_id]
        merged = self._compose_options(options)
        history = session_state["history"]
        
        # Add user message to history
        history.append({"role": "user", "content": transcript})
        
        # Build the prompt
        prompt = self._build_prompt(transcript, context, history)
        
        # Prepare API request
        await self._ensure_session()
        assert self._session
        
        url = f"{merged['base_url'].rstrip('/')}/api/generate"
        payload = {
            "model": merged["model"],
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": merged.get("temperature", 0.7),
                "num_predict": merged.get("max_tokens", 150),
            },
        }
        
        # Add system prompt if available
        system_prompt = context.get("system_prompt")
        if system_prompt:
            payload["system"] = system_prompt
        
        logger.debug(
            "Free LLM request",
            call_id=call_id,
            model=merged["model"],
            prompt_length=len(prompt),
        )
        
        try:
            timeout = aiohttp.ClientTimeout(total=merged["timeout_sec"])
            async with self._session.post(url, json=payload, timeout=timeout) as response:
                if response.status >= 400:
                    body = await response.text()
                    logger.error(
                        "Free LLM API error",
                        call_id=call_id,
                        status=response.status,
                        body_preview=body[:200],
                    )
                    return "I'm having trouble connecting right now. Please try again."
                
                data = await response.json()
                text = data.get("response", "").strip()
                
                # Clean up response - remove thinking tags if present (DeepSeek R1)
                if "<think>" in text:
                    # Extract only the final response after thinking
                    parts = text.split("</think>")
                    if len(parts) > 1:
                        text = parts[-1].strip()
                    else:
                        # Remove incomplete thinking
                        text = text.split("<think>")[0].strip()
                
                # Truncate if too long for voice
                if len(text) > 500:
                    # Find a good break point
                    text = text[:500]
                    last_period = text.rfind(".")
                    if last_period > 200:
                        text = text[:last_period + 1]
                
                logger.info(
                    "Free LLM response",
                    call_id=call_id,
                    model=merged["model"],
                    response_length=len(text),
                    preview=text[:80],
                )
                
                # Add assistant response to history
                history.append({"role": "assistant", "content": text})
                
                # Return as LLMResponse with no tool calls
                return LLMResponse(
                    text=text,
                    tool_calls=[],  # No tool calling support
                    metadata={"model": merged["model"], "done": data.get("done", True)},
                )
                
        except asyncio.TimeoutError:
            logger.warning("Free LLM request timeout", call_id=call_id)
            return "I'm taking too long to respond. Please try again."
        except Exception as e:
            logger.error("Free LLM request failed", call_id=call_id, error=str(e))
            return "I encountered an error. Please try again."

    async def validate_connectivity(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """Test connectivity to the free LLM API."""
        merged = self._compose_options(options)
        base_url = merged.get("base_url", _DEFAULT_BASE_URL)
        
        try:
            await self._ensure_session()
            assert self._session
            
            # Simple health check - try a minimal request
            url = f"{base_url.rstrip('/')}/api/generate"
            payload = {
                "model": merged.get("model", _DEFAULT_MODEL),
                "prompt": "Hi",
                "stream": False,
                "options": {"num_predict": 5},
            }
            
            timeout = aiohttp.ClientTimeout(total=10)
            async with self._session.post(url, json=payload, timeout=timeout) as response:
                if response.status == 200:
                    return {
                        "healthy": True,
                        "error": None,
                        "details": {
                            "endpoint": url,
                            "model": merged.get("model"),
                            "note": "Free API - no tool calling support",
                        },
                    }
                else:
                    body = await response.text()
                    return {
                        "healthy": False,
                        "error": f"API returned status {response.status}",
                        "details": {"endpoint": url, "response": body[:200]},
                    }
        except asyncio.TimeoutError:
            return {
                "healthy": False,
                "error": "Connection timeout - service may be busy",
                "details": {"endpoint": base_url},
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": f"Connection failed: {str(e)}",
                "details": {"endpoint": base_url},
            }
