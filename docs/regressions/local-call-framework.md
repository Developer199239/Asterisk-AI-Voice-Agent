# Call Framework Analysis — Local Provider

## 2025-09-25 20:53 PDT — No audio heard; server sent JSON TTS; engine didn’t play (pre-fix)

- **Outcome**
- No initial greeting heard.
- No two-way audio; caller heard silence.

- **Key Evidence (server logs)**
- ai-engine (03:51:51Z):
  - "Sent greeting TTS request to Local AI Server" (call_id=1758858703.1281)
  - "AudioSocket inbound first audio bytes=320" and provider input with `input_mode=pcm16_8k`.
  - No `AgentAudio` or `AUDIO PLAYBACK - Started` lines for this call.
- local-ai-server (03:51:51Z):
  - "🔊 TTS REQUEST - Call 1758858703.1281: 'Hello! I'm your AI assistant...'"
  - "🔊 TTS RESULT - Generated uLaw 8kHz audio: 27214 bytes"
  - "📤 TTS RESPONSE - Sent 27214 bytes"
  - Many "🎵 AUDIO INPUT - Received audio: ... at 16000 Hz" lines afterward.

- **Diagnosis**
- Local AI Server replied with a JSON `tts_response` containing base64 audio (`audio_data`).
- `LocalProvider._receive_loop()` only emitted `AgentAudio` for binary frames, not for JSON `tts_response` payloads.
- Result: engine never received `AgentAudio`/`AgentAudioDone`, so no playback occurred despite greeting being generated server-side.

- **Remediation Applied**
- `src/providers/local.py::_receive_loop()` updated to:
  - On `tts_response`, if `audio_data` exists, decode base64 and emit `AgentAudio` then `AgentAudioDone` with the correct `call_id`.
- Engine already triggers greeting at session start: `src/engine.py::_start_provider_session()` calls `provider.play_initial_greeting(call_id)`.

- **Next Steps (Verification on next call)**
- Expect in ai-engine logs:
  - `Sent greeting TTS request to Local AI Server`
  - `Provider control event` may show JSON, then `AgentAudio`/`AgentAudioDone`
  - `🔊 AUDIO PLAYBACK - Started` → `🔊 PlaybackFinished ... gating_cleared=true`

- **Status**
- Config tuned locally; server deploy pending (resolve server repo local changes to apply config).
