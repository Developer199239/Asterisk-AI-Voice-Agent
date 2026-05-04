import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "admin_ui" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from services.google_live_validation import (  # noqa: E402
    GOOGLE_LIVE_DEFAULT_MODEL,
    build_google_key_validation_result,
    extract_google_live_models,
    select_google_live_model,
)


def test_google_live_validation_accepts_key_when_live_models_are_not_advertised():
    result = build_google_key_validation_result(
        [
            {
                "name": "models/gemini-2.5-flash",
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            }
        ]
    )

    assert result["valid"] is True
    assert result["selected_model"] == GOOGLE_LIVE_DEFAULT_MODEL
    assert result["available_models"] == []
    assert "warning" in result
    assert "did not advertise Live-capable models" in result["warning"]


def test_google_live_validation_selects_preferred_live_model():
    result = build_google_key_validation_result(
        [
            {
                "name": "models/gemini-3.1-flash-live-preview",
                "supportedGenerationMethods": ["bidiGenerateContent"],
            },
            {
                "name": "models/gemini-2.5-flash-native-audio-preview-12-2025",
                "supportedGenerationMethods": ["generateContent", "bidiGenerateContent"],
            },
        ]
    )

    assert result["valid"] is True
    assert result["selected_model"] == "gemini-2.5-flash-native-audio-preview-12-2025"
    assert "warning" not in result


def test_google_live_model_extraction_strips_models_prefix():
    live_models = extract_google_live_models(
        [
            {
                "name": "models/gemini-3.1-flash-live-preview",
                "supportedGenerationMethods": ["bidiGenerateContent"],
            },
            {
                "name": "models/gemini-2.5-flash",
                "supportedGenerationMethods": ["generateContent"],
            },
        ]
    )

    assert live_models == ["gemini-3.1-flash-live-preview"]
    assert select_google_live_model(live_models) == "gemini-3.1-flash-live-preview"
