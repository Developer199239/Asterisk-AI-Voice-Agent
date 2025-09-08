import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from services.llm_service.openai_client import OpenAIClient, LLMConfig, ModelType
from openai import APIConnectionError

@pytest.mark.asyncio
async def test_llm_api_retry_and_fallback():
    """Test that the OpenAI client retries on failure and then falls back."""
    # Arrange
    config = LLMConfig(api_key="test_key", primary_model=ModelType.GPT_4O, fallback_model=ModelType.GPT_3_5_TURBO)
    client = OpenAIClient(config)

    mock_create = AsyncMock()
    mock_create.side_effect = [
        APIConnectionError(message="Failed to connect", request=None),
        APIConnectionError(message="Failed to connect", request=None),
        APIConnectionError(message="Failed to connect", request=None),
        AsyncMock(choices=[AsyncMock(message=AsyncMock(content="Fallback response"))], usage=AsyncMock(total_tokens=10))
    ]

    with patch.object(client.client.chat.completions, 'create', mock_create):
        # Act
        response = await client.generate_response([{"role": "user", "content": "Hello"}])

        # Assert
        assert response.content == "Fallback response"
        assert response.model_used == ModelType.GPT_3_5_TURBO.value
        assert mock_create.call_count == 4  # 3 failures for primary, 1 success for fallback
