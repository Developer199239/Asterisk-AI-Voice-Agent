"""Tests for the MiniMax LLM pipeline adapter."""

import json

import pytest

from src.config import AppConfig, MiniMaxLLMProviderConfig
from src.pipelines.minimax import MiniMaxLLMAdapter, _clamp_temperature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app_config() -> AppConfig:
    providers = {
        "minimax_llm": {
            "api_key": "test-minimax-key",
            "chat_base_url": "https://api.minimax.io/v1",
            "chat_model": "MiniMax-M2.5",
            "temperature": 1.0,
            "response_timeout_sec": 10.0,
            "type": "minimax",
        }
    }
    pipelines = {
        "minimax_stack": {
            "stt": "openai_stt",
            "llm": "minimax_llm",
            "tts": "openai_tts",
            "options": {
                "llm": {"temperature": 0.8},
            },
        }
    }
    return AppConfig(
        default_provider="minimax",
        providers=providers,
        asterisk={"host": "127.0.0.1", "username": "ari", "password": "secret"},
        llm={"initial_greeting": "hi", "prompt": "You are a helpful assistant.", "model": "MiniMax-M2.5"},
        audio_transport="audiosocket",
        downstream_mode="stream",
        pipelines=pipelines,
        active_pipeline="minimax_stack",
    )


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self):
        return self._body

    async def text(self):
        return self._body.decode("utf-8", errors="ignore")


class _FakeSession:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self._status = status
        self.requests = []
        self.closed = False

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.requests.append({"url": url, "json": json, "data": data, "headers": headers, "timeout": timeout})
        return _FakeResponse(self._body, status=self._status)

    def get(self, url, headers=None, timeout=None):
        return _FakeResponse(self._body, status=self._status)

    async def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestClampTemperature:
    def test_zero_clamped(self):
        assert _clamp_temperature(0) == 0.01

    def test_negative_clamped(self):
        assert _clamp_temperature(-1.0) == 0.01

    def test_over_one_clamped(self):
        assert _clamp_temperature(1.5) == 1.0

    def test_valid_value_passthrough(self):
        assert _clamp_temperature(0.7) == 0.7

    def test_one_passthrough(self):
        assert _clamp_temperature(1.0) == 1.0

    def test_none_defaults(self):
        assert _clamp_temperature(None) == 1.0


@pytest.mark.asyncio
async def test_minimax_llm_chat_completion():
    """MiniMax adapter returns correct text from chat completion response."""
    app_config = _build_app_config()
    provider_config = MiniMaxLLMProviderConfig(**app_config.providers["minimax_llm"])
    body = json.dumps({
        "choices": [{"message": {"content": "Hello! How can I help?"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8},
    }).encode("utf-8")
    fake_session = _FakeSession(body)

    adapter = MiniMaxLLMAdapter(
        "minimax_llm",
        app_config,
        provider_config,
        {},
        session_factory=lambda: fake_session,
    )

    await adapter.start()
    response = await adapter.generate("call-1", "hello", {"system_prompt": "Be helpful."}, {})
    assert response.text == "Hello! How can I help?"
    assert response.tool_calls == []

    request = fake_session.requests[0]
    assert request["json"]["model"] == "MiniMax-M2.5"
    assert request["url"] == "https://api.minimax.io/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-minimax-key"


@pytest.mark.asyncio
async def test_minimax_llm_temperature_clamped():
    """Temperature is clamped to (0, 1] for MiniMax API."""
    app_config = _build_app_config()
    provider_config = MiniMaxLLMProviderConfig(**app_config.providers["minimax_llm"])
    body = json.dumps({
        "choices": [{"message": {"content": "ok"}}],
    }).encode("utf-8")
    fake_session = _FakeSession(body)

    adapter = MiniMaxLLMAdapter(
        "minimax_llm",
        app_config,
        provider_config,
        {"temperature": 0},  # Should be clamped to 0.01
        session_factory=lambda: fake_session,
    )
    await adapter.start()
    await adapter.generate("call-1", "test", {}, {})
    payload = fake_session.requests[0]["json"]
    assert payload["temperature"] == 0.01


@pytest.mark.asyncio
async def test_minimax_llm_tool_calls():
    """Adapter parses tool calls from MiniMax response."""
    app_config = _build_app_config()
    provider_config = MiniMaxLLMProviderConfig(**app_config.providers["minimax_llm"])
    body = json.dumps({
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Tokyo"}',
                    },
                }],
            },
        }],
    }).encode("utf-8")
    fake_session = _FakeSession(body)

    adapter = MiniMaxLLMAdapter(
        "minimax_llm",
        app_config,
        provider_config,
        {},
        session_factory=lambda: fake_session,
    )
    await adapter.start()
    response = await adapter.generate("call-1", "weather in Tokyo", {}, {})
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["name"] == "get_weather"
    assert response.tool_calls[0]["parameters"] == {"city": "Tokyo"}


@pytest.mark.asyncio
async def test_minimax_llm_strips_thinking():
    """Adapter strips <think> blocks from response content."""
    app_config = _build_app_config()
    provider_config = MiniMaxLLMProviderConfig(**app_config.providers["minimax_llm"])
    body = json.dumps({
        "choices": [{
            "message": {"content": "<think>some reasoning</think>The answer is 42."},
        }],
    }).encode("utf-8")
    fake_session = _FakeSession(body)

    adapter = MiniMaxLLMAdapter(
        "minimax_llm",
        app_config,
        provider_config,
        {},
        session_factory=lambda: fake_session,
    )
    await adapter.start()
    response = await adapter.generate("call-1", "what is 6*7?", {}, {})
    assert response.text == "The answer is 42."


@pytest.mark.asyncio
async def test_minimax_llm_highspeed_model():
    """Adapter works with the MiniMax-M2.5-highspeed model."""
    app_config = _build_app_config()
    config_data = dict(app_config.providers["minimax_llm"])
    config_data["chat_model"] = "MiniMax-M2.5-highspeed"
    provider_config = MiniMaxLLMProviderConfig(**config_data)
    body = json.dumps({
        "choices": [{"message": {"content": "fast response"}}],
    }).encode("utf-8")
    fake_session = _FakeSession(body)

    adapter = MiniMaxLLMAdapter(
        "minimax_llm",
        app_config,
        provider_config,
        {},
        session_factory=lambda: fake_session,
    )
    await adapter.start()
    response = await adapter.generate("call-1", "hi", {}, {})
    assert response.text == "fast response"
    assert fake_session.requests[0]["json"]["model"] == "MiniMax-M2.5-highspeed"


@pytest.mark.asyncio
async def test_minimax_llm_no_api_key_raises():
    """Adapter raises when MINIMAX_API_KEY is not set."""
    app_config = _build_app_config()
    config_data = dict(app_config.providers["minimax_llm"])
    config_data["api_key"] = None
    provider_config = MiniMaxLLMProviderConfig(**config_data)
    fake_session = _FakeSession(b"{}")

    adapter = MiniMaxLLMAdapter(
        "minimax_llm",
        app_config,
        provider_config,
        {},
        session_factory=lambda: fake_session,
    )
    await adapter.start()
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        await adapter.generate("call-1", "hi", {}, {})
