import pytest
from unittest.mock import patch

from services.llm_service.llm_service import LLMService, LLMServiceConfig
from shared.fallback_responses import FallbackResponseManager

@pytest.mark.asyncio
async def test_llm_service_uses_fallback_on_error():
    """Test that the LLMService uses a scripted fallback response on OpenAI failure."""
    # Arrange
    config = LLMServiceConfig(openai_api_key="test_key")
    service = LLMService(config)

    # Mock the OpenAI client to always raise an exception
    with patch.object(service.openai_client, 'generate_response', side_effect=Exception("API unavailable")):
        # Mock the redis publish method
        with patch.object(service, '_publish_response', new_callable=pytest.AsyncMock) as mock_publish:
            # Act
            await service._generate_response_for_channel("test_channel")

            # Assert
            mock_publish.assert_called_once()
            args, _ = mock_publish.call_args
            channel_id, response_data = args
            
            assert channel_id == "test_channel"
            assert response_data['model_used'] == 'fallback'
            assert response_data['content'] in FallbackResponseManager()._get_default_templates()['ERROR_GENERIC']
