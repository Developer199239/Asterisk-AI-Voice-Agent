from src.tools.telephony.hangup_policy import (
    resolve_hangup_policy,
    text_contains_marker,
    text_contains_end_call_intent,
)


def test_default_end_call_markers_include_natural_closing_phrases():
    policy = resolve_hangup_policy({})
    markers = (policy.get("markers") or {}).get("end_call", [])

    assert "thank you" in markers
    assert "thanks" in markers
    assert "have a good day" in markers


def test_end_call_detection_matches_polite_goodbye_phrase():
    policy = resolve_hangup_policy({})
    markers = (policy.get("markers") or {}).get("end_call", [])

    assert text_contains_marker("Okay. Thank you. Have a good day.", markers)


def test_end_call_detection_does_not_trigger_on_unrelated_text():
    policy = resolve_hangup_policy({})
    markers = (policy.get("markers") or {}).get("end_call", [])

    assert not text_contains_marker("Can you explain setup pricing again?", markers)


def test_end_call_detection_handles_common_stt_misrecognitions():
    policy = resolve_hangup_policy({})
    markers = (policy.get("markers") or {}).get("end_call", [])

    assert text_contains_end_call_intent("Okay, hand up the call.", markers)
    assert text_contains_end_call_intent("Please and the call now.", markers)
