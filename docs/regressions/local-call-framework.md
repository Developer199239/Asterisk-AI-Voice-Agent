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

- **What Failed**
- STT did not produce a final transcript for the caller’s first turn.
- Audio pipeline suffered backpressure, dropping AudioSocket frames while waiting for STT.

- **Key Evidence**
- `logs/ai-engine-20250926-162558.log`:
  - Post-greeting: `Sending STT audio chunk bytes=5742 rate=16000 component=local_stt` (~line 390)
  - `Local STT partial received transcript_preview=` (empty) (~line 391)
  - Many `Pipeline queue full; dropping AudioSocket frame` for several seconds (~392–448+)
  - `STT transcribe failed TimeoutError` (~449–479); then another send (~480) with more backpressure lines.
- `logs/local-ai-server-20250926-162601.log`:
  - Server initialized; models loaded; `Session mode updated to stt/llm/tts`; `🔊 TTS RESULT` logged.
  - Connections then closed; no INFO-level STT partial/final logs present.

- **Diagnosis**
- The engine sent a very short (~200 ms) audio chunk to STT and then blocked, awaiting a final. Vosk yielded a partial but not a final; absent additional audio or an explicit flush, no final was produced. While waiting, inbound AudioSocket frames queued up and were dropped; the STT adapter timed out (5 s).

- **Root Cause**
- Contract mismatch: engine behavior approximated "single-chunk, wait-for-final," whereas the local server’s streaming STT expects continuous audio or a flush/end-of-utterance signal to finalize.
- Missing idle-finalizer server-side to promote partial → final after a period of silence.
- Possible premature WS closures further reduce robustness.

- **Proposed Fixes**
- Server (high):
  - Implement idle finalizer (~600–800 ms silence) to emit `stt_result` with `is_final=true`, then reset recognizer.
  - Keep per-connection WS sessions open for the full call; do not auto-close STT/LLM/TTS sockets after greeting.
  - Elevate STT logging to INFO: log inbound `audio` (bytes, rate, call/session id) and each partial/final.
- Engine (near-term):
  - Stream audio continuously while awaiting STT; on partial, reset the timeout; on final, proceed to LLM/TTS.
  - Optionally send explicit `flush`/`end_utterance` when VAD detects speech end.
  - Improve backpressure handling (bounded buffer/coalescing) and add reconnect-on-close.

- **Validation Plan**
- Re-run regression; expect multiple partials then a final, no sustained `Pipeline queue full` spam, and LLM/TTS response turn-taking.

## 2025-09-27 10:10 PDT — Local streaming STT aligned with cloud providers

- **Fixes applied**
  - Local AI server maintains a persistent Vosk recognizer per WebSocket session and emits `stt_result` updates with `is_partial`/`is_final` markers so the engine mirrors Deepgram/OpenAI behavior.
  - Partial keep-alives prevent the engine from timing out while speech accumulates; finals reset recognizer state for the next utterance.
  - Local STT adapter honors the streaming contract, resetting its timeout on partials and returning immediately once a final transcript arrives. Default `response_timeout_sec` raised to 5 s for longer turns.
- **Validation**
  - Adapter unit coverage exercises partial→final flows (`tests/test_pipeline_local_adapters.py`), confirming the client consumes the new events.
  - Pending: capture fresh call logs with successful partial/final hand-off end-to-end.

## 2025-09-27 18:30 PDT — Local-only pipeline stable with slow LLM responses

- **Fixes applied**
  - Local AI server now idle-promotes partial transcripts to finals after ~750 ms of silence and runs TinyLlama via `asyncio.to_thread`, keeping the WebSocket handler responsive even when LLM latency exceeds 30 s.
  - Engine pipeline drains AudioSocket frames in a dedicated ingest task and feeds transcripts through a bounded queue so LLM/TTS work no longer starves STT; `Pipeline queue full` drops disappeared in post-fix smoke tests.
  - Local configuration raises `chunk_ms` to 320 ms and tightens LLM defaults (temperature/max tokens) to gather more speech per chunk while keeping replies concise.
- **Next steps**
  - Re-run the regression call in `local_only` mode with a deliberately slow LLM build; attach the resulting `ai-engine`/`local-ai-server` logs to this record.
  - Watch for `Pipeline audio buffer overflow` warnings during load; tune queue sizes if they appear frequently under production traffic.
