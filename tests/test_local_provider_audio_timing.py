import asyncio
import base64
import json

import pytest

from src.config import LocalProviderConfig
from src.providers.local import LocalProvider


class _FakeWebSocket:
    def __init__(self, messages):
        self._messages = list(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


@pytest.mark.asyncio
async def test_binary_audio_emits_metadata_and_delayed_done():
    events = []

    async def on_event(event):
        events.append(event)

    provider = LocalProvider(LocalProviderConfig(), on_event=on_event)
    provider._active_call_id = "call-1"
    provider.websocket = _FakeWebSocket(
        [
            json.dumps(
                {
                    "type": "tts_audio",
                    "call_id": "call-1",
                    "encoding": "mulaw",
                    "sample_rate_hz": 8000,
                    "byte_length": 800,
                }
            ),
            b"\x00" * 800,
        ]
    )

    await provider._receive_loop()

    agent_events = [e for e in events if e.get("type") == "AgentAudio"]
    done_events = [e for e in events if e.get("type") == "AgentAudioDone"]
    assert len(agent_events) == 1
    assert agent_events[0]["encoding"] == "mulaw"
    assert agent_events[0]["sample_rate"] == 8000
    assert done_events == []

    await asyncio.sleep(0.18)
    done_events = [e for e in events if e.get("type") == "AgentAudioDone"]
    assert len(done_events) == 1
    await provider.clear_active_call_id()


@pytest.mark.asyncio
async def test_tts_response_uses_payload_audio_format():
    events = []

    async def on_event(event):
        events.append(event)

    provider = LocalProvider(LocalProviderConfig(), on_event=on_event)
    provider._active_call_id = "call-2"
    audio_bytes = b"\x01\x02" * 400  # 800 bytes of linear16
    provider.websocket = _FakeWebSocket(
        [
            json.dumps(
                {
                    "type": "tts_response",
                    "text": "hello",
                    "call_id": "call-2",
                    "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
                    "encoding": "linear16",
                    "sample_rate_hz": 16000,
                }
            )
        ]
    )

    await provider._receive_loop()
    await asyncio.sleep(0.10)

    agent_events = [e for e in events if e.get("type") == "AgentAudio"]
    done_events = [e for e in events if e.get("type") == "AgentAudioDone"]
    assert len(agent_events) == 1
    assert agent_events[0]["encoding"] == "linear16"
    assert agent_events[0]["sample_rate"] == 16000
    assert len(done_events) == 1
    await provider.clear_active_call_id()


@pytest.mark.asyncio
async def test_binary_audio_defaults_to_mulaw_when_metadata_missing():
    events = []

    async def on_event(event):
        events.append(event)

    provider = LocalProvider(LocalProviderConfig(), on_event=on_event)
    provider._active_call_id = "call-3"
    provider.websocket = _FakeWebSocket([b"\x7f" * 80])

    await provider._receive_loop()
    await asyncio.sleep(0.12)

    agent_events = [e for e in events if e.get("type") == "AgentAudio"]
    done_events = [e for e in events if e.get("type") == "AgentAudioDone"]
    assert len(agent_events) == 1
    assert agent_events[0]["encoding"] == "mulaw"
    assert agent_events[0]["sample_rate"] == 8000
    assert len(done_events) == 1
    await provider.clear_active_call_id()


@pytest.mark.asyncio
async def test_stt_result_updates_runtime_backend_for_whisper():
    events = []

    async def on_event(event):
        events.append(event)

    provider = LocalProvider(LocalProviderConfig(stt_backend="vosk"), on_event=on_event)
    provider._active_call_id = "call-whisper"
    provider.websocket = _FakeWebSocket(
        [
            json.dumps(
                {
                    "type": "stt_result",
                    "call_id": "call-whisper",
                    "text": "hello",
                    "is_final": True,
                    "stt_backend": "faster_whisper",
                }
            )
        ]
    )

    await provider._receive_loop()

    assert provider.get_active_stt_backend() == "faster_whisper"
    assert provider.is_whisper_stt_active() is True


@pytest.mark.asyncio
async def test_status_response_updates_runtime_backend():
    events = []

    async def on_event(event):
        events.append(event)

    provider = LocalProvider(LocalProviderConfig(stt_backend="vosk"), on_event=on_event)
    provider._active_call_id = "call-status"
    provider.websocket = _FakeWebSocket(
        [
            json.dumps(
                {
                    "type": "status_response",
                    "status": "ok",
                    "stt_backend": "whisper_cpp",
                    "tts_backend": "piper",
                    "models": {},
                }
            )
        ]
    )

    await provider._receive_loop()
    assert provider.get_active_stt_backend() == "whisper_cpp"
    assert provider.is_whisper_stt_active() is True


def test_stt_backend_falls_back_to_config_when_runtime_unknown():
    async def on_event(_event):
        return None

    provider = LocalProvider(LocalProviderConfig(stt_backend="sherpa"), on_event=on_event)
    assert provider.get_active_stt_backend() == "sherpa"
    assert provider.is_whisper_stt_active() is False
