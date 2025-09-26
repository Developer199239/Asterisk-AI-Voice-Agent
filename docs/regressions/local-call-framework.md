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

## 2025-09-26 14:25 PDT — Greeting succeeded, STT not receiving; inbound dropped then timeouts

- **Outcome**
- Initial greeting played successfully to caller (TTS path working end-to-end).
- After greeting, caller audio did not reach STT processing; no two-way conversation.

- **Key Evidence**
- ai-engine (`logs/ai-engine-20250926-142800.log`):
  - Adapters connected with handshake acks:
    - `Opening local adapter session` → `Local adapter set_mode sent` → `Local adapter handshake complete` for `local_stt`, `local_llm`, `local_tts`.
  - TTS greeting path:
    - `Sending TTS request` → `Local TTS audio chunk received bytes=13282 latency_ms=518.71`
    - File created at `/mnt/asterisk_media/ai-generated/audio-pipeline-tts-greeting-<call>.ulaw`
    - `🔊 AUDIO PLAYBACK - Started` and later `PlaybackFinished ... gating_cleared=true`
  - AudioSocket inbound during greeting:
    - Multiple `Dropping inbound AudioSocket audio during TTS playback (barge-in disabled)` as expected.
  - After gating cleared:
    - `Sending STT audio chunk bytes=5742 rate=16000` (repeated)
    - Each followed by `STT transcribe failed` with `TimeoutError` waiting for `stt_result`.
    - `Pipeline queue full; dropping AudioSocket frame` repeated (STT not consuming → backpressure and drops).
- local-ai-server (`logs/local-ai-server-20250926-142802.log`):
  - Multiple `New connection established` + `Session mode updated to stt/llm/tts`.
  - `🔊 TTS RESULT - Generated uLaw 8kHz audio: 13282 bytes`.
  - Immediately after, `Connection closed` for the new sockets. No `AUDIO INPUT` or `stt_result` logs seen.

- **Diagnosis**
- Client-side adapters now function (WS connect + handshake + TTS request/receive worked), but the STT leg returns no responses, timing out repeatedly.
- The server appears to close the newly opened sockets soon after the TTS result. Given the `Session mode updated to ...` logs lack a `call_id` and appear global, it’s likely the server maintains a single global session state instead of per-connection state. This would cause new connections (e.g., LLM/TTS) to overwrite mode and disrupt the STT socket.
- Additionally, the STT `response_timeout_sec` is 2.0s (from `providers.local.response_timeout_sec: ${LOCAL_WS_RESPONSE_TIMEOUT:=2.0}`), which may be tight under load. However, the absence of any STT logs on server strongly suggests the server didn’t process the STT audio at all.

- **Next Steps**
- Server (priority):
  - Maintain per-connection session state keyed by the websocket (store `call_id`/`mode` per connection). Do not treat `mode` as global.
  - Keep STT/LLM/TTS connections open for the lifetime of the call or until client close; don’t auto-close after TTS result.
  - Instrument STT handler to log each inbound `audio` message with `call_id`, `len(data)`, `rate`, and emit `stt_result` promptly.
  - Confirm that multiple `audio` messages are accepted and processed sequentially for streaming STT.
- Client (secondary):
  - Consider increasing local `response_timeout_sec` (e.g., to 5–8s) to avoid premature timeouts.
  - Add reconnect-on-close for adapter sockets if the server unexpectedly closes them during a call.
  - Keep barge-in disabled until STT path is verified stable, then re-enable and tune thresholds.

### 2025-09-27 10:10 PDT — Local streaming STT aligned with cloud providers

- **Fixes applied**
  - Local AI server now maintains a persistent Vosk recognizer per WebSocket session and emits `stt_result` updates with `is_partial`/`is_final` markers, matching the Deepgram/OpenAI contract.
  - Partial results, including empty keep-alives, prevent the engine from timing out while audio accumulates; final transcripts reset recognizer state for the next utterance.
  - Local STT adapter consumes the new contract, resetting its timeout on partials and returning once a final transcript arrives. Default `response_timeout_sec` increased to 5 s to accommodate longer turns.
- **Validation**
  - Unit coverage extends to partial+final flows (`tests/test_pipeline_local_adapters.py`) ensuring adapters honor the streaming contract.
  - Pending: re-run end-to-end call regression to confirm AudioSocket frames now advance beyond STT and drive LLM/TTS responses.
