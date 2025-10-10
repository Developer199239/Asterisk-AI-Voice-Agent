import time

import pytest

from src.config import OpenAIRealtimeProviderConfig
from src.providers.openai_realtime import (
    OpenAIRealtimeProvider,
    _OPENAI_ASSUMED_OUTPUT_RATE,
    _OPENAI_MEASURED_OUTPUT_RATE,
    _OPENAI_PROVIDER_OUTPUT_RATE,
    _OPENAI_SESSION_AUDIO_INFO,
)


@pytest.fixture
def openai_config():
    return OpenAIRealtimeProviderConfig(
        api_key="test-key",
        model="gpt-test",
        voice="alloy",
        base_url="wss://api.openai.com/v1/realtime",
        input_encoding="ulaw",
        input_sample_rate_hz=8000,
        provider_input_encoding="linear16",
        provider_input_sample_rate_hz=24000,
        output_encoding="linear16",
        output_sample_rate_hz=24000,
        target_encoding="mulaw",
        target_sample_rate_hz=8000,
        response_modalities=["audio"],
    )


def _cleanup_metrics(call_id: str) -> None:
    for metric in (
        _OPENAI_ASSUMED_OUTPUT_RATE,
        _OPENAI_MEASURED_OUTPUT_RATE,
        _OPENAI_PROVIDER_OUTPUT_RATE,
    ):
        try:
            metric.remove(call_id)
        except (KeyError, ValueError):
            pass
    try:
        _OPENAI_SESSION_AUDIO_INFO.remove(call_id)
    except (KeyError, ValueError):
        pass


def test_output_rate_drift_adjusts_active_rate(openai_config):
    provider = OpenAIRealtimeProvider(openai_config, on_event=None)
    call_id = "call-test"
    provider._call_id = call_id
    provider._reset_output_meter()

    # Simulate 2 seconds of runtime before first chunk is processed
    provider._output_meter_start_ts = time.monotonic() - 2.0
    provider._output_meter_last_log_ts = provider._output_meter_start_ts

    # Feed enough bytes to represent ~9 kHz PCM16 audio over the 2 second window.
    provider._update_output_meter(36000)

    try:
        assert provider._output_rate_warned is True
        assert provider._active_output_sample_rate_hz is not None
        # Drift adjustment should bring active rate close to the measured 9 kHz
        assert abs(provider._active_output_sample_rate_hz - 9000) < 500
    finally:
        _cleanup_metrics(call_id)
