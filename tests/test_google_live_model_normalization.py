from src.providers.google_live import GoogleLiveProvider


def test_google_live_model_normalization_defaults_to_supported_preview_model():
    assert GoogleLiveProvider._normalize_model_name(None) == "gemini-2.5-flash-native-audio-preview-12-2025"
    assert GoogleLiveProvider._normalize_model_name("") == "gemini-2.5-flash-native-audio-preview-12-2025"


def test_google_live_model_normalization_maps_legacy_models():
    assert (
        GoogleLiveProvider._normalize_model_name("gemini-2.5-flash-native-audio-latest")
        == "gemini-2.5-flash-native-audio-preview-12-2025"
    )
    assert (
        GoogleLiveProvider._normalize_model_name("gemini-live-2.5-flash-preview")
        == "gemini-2.5-flash-native-audio-preview-12-2025"
    )


def test_google_live_model_normalization_keeps_supported_native_audio_models():
    assert (
        GoogleLiveProvider._normalize_model_name("gemini-2.5-flash-native-audio-preview-09-2025")
        == "gemini-2.5-flash-native-audio-preview-09-2025"
    )
    assert (
        GoogleLiveProvider._normalize_model_name("gemini-2.5-flash-exp-native-audio-thinking-dialog")
        == "gemini-2.5-flash-exp-native-audio-thinking-dialog"
    )


def test_google_live_model_normalization_rejects_non_live_model_values():
    assert (
        GoogleLiveProvider._normalize_model_name("models/gemini-1.5-pro-latest")
        == "gemini-2.5-flash-native-audio-preview-12-2025"
    )


def test_google_live_model_normalization_keeps_non_native_audio_live_models():
    assert (
        GoogleLiveProvider._normalize_model_name("gemini-2.0-flash-live-001")
        == "gemini-2.0-flash-live-001"
    )
