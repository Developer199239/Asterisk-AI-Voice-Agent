import pytest

from src.core.models import CallSession
from src.core.session_store import SessionStore
from src.engine import Engine


@pytest.mark.asyncio
async def test_transcript_event_stamps_latency_timestamps():
    engine = Engine.__new__(Engine)
    engine.session_store = SessionStore()

    session = CallSession(call_id="call-latency", caller_channel_id="call-latency")
    await engine.session_store.upsert_call(session)

    await engine.on_provider_event(
        {
            "type": "transcript",
            "call_id": "call-latency",
            "text": "thank you",
        }
    )

    updated = await engine.session_store.get_by_call_id("call-latency")
    assert updated is not None
    assert updated.last_transcription_ts > 0.0
    assert updated.last_user_speech_end_ts > 0.0
    assert updated.conversation_history[-1]["role"] == "user"
