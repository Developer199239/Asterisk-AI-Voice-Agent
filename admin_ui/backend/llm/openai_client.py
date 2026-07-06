"""
OpenAI API client for LLM inference.

Handles the raw HTTP call to OpenAI chat completions and returns
the parsed JSON response. All prompt/message construction is done
by the caller (see prompts/).
"""

import json
import logging
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TIMEOUT = 30.0


async def chat_completion_json(
    messages: List[Dict[str, str]],
    openai_key: str,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """
    Call OpenAI chat completions with JSON response mode.

    Args:
        messages:    OpenAI messages array (system + user turns).
        openai_key:  OpenAI API key.
        model:       Model name (default gpt-4o-mini).
        temperature: Sampling temperature (default 0.1 for deterministic output).
        timeout:     HTTP timeout in seconds.

    Returns:
        Parsed JSON dict from the model's response content.

    Raises:
        HTTPException 502 if OpenAI returns a non-200 status.
        HTTPException 500 if the response cannot be parsed as JSON.
    """
    payload = {
        "model": model,
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "messages": messages,
    }

    logger.debug("OpenAI request — model=%s messages=%d", model, len(messages))

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            OPENAI_CHAT_URL,
            headers={
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code != 200:
        logger.error(
            "OpenAI API error — status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API returned HTTP {response.status_code}",
        )

    try:
        data = response.json()
        raw = data["choices"][0]["message"]["content"]
        return json.loads(raw)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.error("Failed to parse OpenAI response — %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse OpenAI response: {exc}",
        )
