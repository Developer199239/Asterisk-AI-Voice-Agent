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

## 2025-09-27 21:40 PDT — Utterance aggregation enabled for local-only pipeline

- **Fixes applied**
  - Local AI server default idle finalizer bumped to 1200 ms (still overrideable via `LOCAL_STT_IDLE_MS`) so callers can finish multi-word phrases before a final is emitted.
  - Engine `dialog_worker` now accumulates consecutive STT finals until they reach ≥ 3 words or ≥ 12 characters, flushing sooner only after 2 s of silence. Short fragments are logged as “Accumulating transcript before LLM” instead of triggering an immediate request.
  - Aggregated prompts reuse the existing LLM/TTS path; no adapter or pipeline schema changes required.
- **Validation plan**
  - Place a local-only regression call (e.g., “hello what is your name”) and confirm a single aggregated prompt drives the LLM/TTS turn.
  - Ensure ai-engine logs show the new aggregation debug message and no longer emit `Skipping LLM for short transcript` unless callers genuinely stop at a fragment.

## 2025-09-26 17:56 PDT — Greeting OK; STT minimal; LLM timed out; no two-way conversation

- **Outcome**
- Greeting played successfully. After greeting, the caller’s speech resulted in minimal STT content (mostly empty partials and a single token "the").
- Engine attempted an LLM request on the tiny transcript, but the local LLM timed out; no reply TTS was produced. Net effect: no two-way dialog.

- **Key Evidence**
- ai-engine (`logs/ai-engine-20250926-175818.log`):
  - Playback path OK:
    - `Local TTS audio chunk received ... 12632 bytes` → audio file created → `🔊 AUDIO PLAYBACK - Started` → `PlaybackFinished ... gating_cleared=true`.
  - STT and ingest:
    - `Sending STT audio chunk bytes=5742 rate=16000` repeated; `Local STT partial received transcript_preview=` (empty) often.
    - `Local STT transcript received ... transcript_preview=the` once, indicating a minimal token recognized.
    - Frequent `Pipeline audio buffer overflow; dropping oldest frame` while LLM/TTS work blocked; expected from bounded buffer backpressure.
  - LLM attempt and timeout:
    - `Sending LLM request ... transcript_preview=the` → `LLM generate failed` with `TimeoutError` in `pipelines/local.py::_recv_any()`; engine timed out waiting on the server’s LLM response.
- local-ai-server (`logs/local-ai-server-20250926-175821.log`):
  - Startup and sockets OK (`server listening on 0.0.0.0:8765`; connections for stt/llm/tts; `TTS RESULT - ... 12632 bytes`).
  - Idle finalizer firing repeatedly:
    - Many `📝 STT IDLE FINALIZER - Triggering final after 1000 ms silence ... preview=` lines, often empty; one shows `preview=the`.
    - Corresponding `📝 STT FINAL - Emitting transcript ...` lines indicate promotion of short partials to finals.
  - Slow LLM:
    - `🤖 LLM RESULT - Completed in 65533.73 ms tokens=2` — the local LLM took ~65.5 s to complete, far exceeding the engine adapter’s ~5 s response timeout.

- **Diagnosis**
- The local LLM is too slow for real-time turn-taking; the engine times out its LLM request before a response arrives, so no reply TTS is generated.
- STT yielded mostly empty partials, with only a single token (`the`) finalized via idle promotion. Triggering LLM on such minimal text further increases the chance of timeouts and unhelpful responses.
- The repeated `Pipeline audio buffer overflow` messages show the engine’s bounded queues doing their job during the LLM stall; this is protective but doesn’t affect the core issue (LLM latency/timeout).

- **Root Cause**
- Mismatch between the local LLM’s compute time (~65 s) and the engine’s LLM response timeout (~5 s). The engine aborts the LLM leg, so the TTS leg never runs.
- STT idle promotion currently elevates very short partials to finals; with chunked audio this can lead to premature LLM requests on insufficient content.

- **Proposed Fixes**
- Engine (high priority):
  - Introduce a dedicated `llm_response_timeout_sec` for the local provider (separate from `response_timeout_sec` used by STT). Default 30–60 s for local-only testing; keep STT at 5–8 s.
  - Add a "minimum transcript length" gate before calling LLM (e.g., ≥ 3 words or ≥ 12 characters) to avoid firing LLM on fragments like "the".
  - Optionally, on LLM timeout, synthesize a brief fallback response (e.g., "Sorry, I didn’t catch that. Could you repeat?") so the call remains interactive while logging the timeout.
- Server (supporting):
  - Keep LLM off the event loop (already done). Add a soft deadline (e.g., 5–8 s) in `process_llm()` and return a fallback if exceeded; log that the background compute exceeded the deadline.
  - Idle finalizer: emit finals only when `last_partial` has meaningful content (≥ N characters/tokens). Empty partials should not be promoted to finals; continue waiting for more audio.
  - Optionally lower `buffer_timeout_ms` from 1000 ms to 750 ms to encourage quicker finals once meaningful speech stops; make it configurable via `LOCAL_STT_IDLE_MS`.
- Tuning:
  - Consider increasing `chunk_ms` to 480–640 ms during experiments to gather more speech per commit and reduce tiny partials.
  - Keep buffer overflow logs at DEBUG; they indicate backpressure working as designed.

- **Validation Plan**
- After the above changes:
  - Expect `Sending LLM request ...` followed by a timely `LLM response` (either a real response within extended timeout or a fallback).
  - Expect `Local TTS audio chunk received` to follow the LLM response, with `Bridge playback started` for the reply.
  - Reduced or no finals on empty content; fewer `Pipeline audio buffer overflow` messages during normal turn-taking.
