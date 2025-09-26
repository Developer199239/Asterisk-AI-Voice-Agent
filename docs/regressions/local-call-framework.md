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

## 2025-09-26 13:07 PDT — Post-handshake deploy, still no greeting or conversation

- **Outcome**
- No initial greeting; caller hears silence.
- Continuous inbound audio dropped due to "initial TTS protection" because greeting never starts.

- **Key Evidence (deployment `e4b4e72` + `deploy-full`)**
- ai-engine (`logs/ai-engine-20250926-130926.log`):
  - `Pipeline STT/LLM/TTS adapter session opened` logged, but immediately `Pipeline greeting retry after session error`.
  - Both greeting attempts raise `RuntimeError: Local adapter session not available for call 1758917211.1343` from `src/pipelines/local.py::_ensure_session`.
  - No `Local adapter handshake complete` or `mode_ready` messages ever logged.
  - After greeting failure, inbound AudioSocket frames logged as "Dropping inbound during initial TTS protection window"; pipeline loop never runs.
- local-ai-server (`logs/local-ai-server-20250926-130928.log`):
  - Server restarts and accepts new connection (`New connection established: ('127.0.0.1', 38940)`).
  - No `mode_ready` response or handshake logs emitted; connection later closes with `ConnectionClosedError`.

- **Diagnosis**
- The local server still does not send the expected `{"type": "mode_ready"}` after `set_mode`; clients never mark `handshake_complete=True`.
- `_ensure_session()` therefore tears down and retries, but repeated `open_call()` attempts also hang until the connection drops, yielding "session not available".
- Greeting playback never begins, so TTS guard logic keeps dropping caller audio and the conversation never progresses.

- **Next Steps**
- Instrument server to log `set_mode` requests vs responses to confirm execution in `local_ai_server/main.py::_handle_json_message`.
- Verify the deployed `local-ai-server` image includes the ack patch (look for `mode_ready` in container logs or run `docker inspect` to confirm image hash).
- Once ack emission is confirmed, retest local_only pipeline; expect to see `Local adapter handshake complete` logs followed by greeting playback.
