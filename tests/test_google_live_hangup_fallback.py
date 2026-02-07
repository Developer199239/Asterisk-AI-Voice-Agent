import pytest

from src.config import GoogleProviderConfig
from src.providers.google_live import GoogleLiveProvider


class _DummySession:
    def __init__(self):
        self.conversation_history = []


class _DummySessionStore:
    def __init__(self):
        self.session = _DummySession()

    async def get_by_call_id(self, _call_id):
        return self.session

    async def upsert_call(self, _session):
        return None


@pytest.mark.unit
def test_google_live_turn_complete_fallback_wait_gate():
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(hangup_fallback_turn_complete_timeout_sec=2.5),
        on_event=lambda e: None,
    )

    provider._hangup_fallback_turn_complete_seen = False
    assert provider._should_wait_for_turn_complete_before_fallback(10.0, 8.0) is True
    assert provider._should_wait_for_turn_complete_before_fallback(11.0, 8.0) is False

    provider._hangup_fallback_turn_complete_seen = True
    assert provider._should_wait_for_turn_complete_before_fallback(10.0, 8.0) is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_google_live_flushes_pending_user_transcription_before_fallback():
    provider = GoogleLiveProvider(config=GoogleProviderConfig(), on_event=lambda e: None)
    provider._call_id = "call-1"
    provider._session_store = _DummySessionStore()
    provider._input_transcription_buffer = "I don't want the transcript"

    flushed = await provider._flush_pending_user_transcription(reason="test")

    assert flushed is True
    assert provider._input_transcription_buffer == ""
    assert provider._last_input_transcription_fragment == ""
    assert provider._last_final_user_text == "I don't want the transcript"
    assert provider._session_store.session.conversation_history[-1]["role"] == "user"
    assert provider._session_store.session.conversation_history[-1]["content"] == "I don't want the transcript"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_google_live_flush_skips_duplicate_pending_user_text():
    provider = GoogleLiveProvider(config=GoogleProviderConfig(), on_event=lambda e: None)
    provider._input_transcription_buffer = "No transcript"
    provider._last_final_user_text = "No transcript"

    flushed = await provider._flush_pending_user_transcription(reason="duplicate")

    assert flushed is False
    assert provider._input_transcription_buffer == ""
    assert provider._last_input_transcription_fragment == ""
