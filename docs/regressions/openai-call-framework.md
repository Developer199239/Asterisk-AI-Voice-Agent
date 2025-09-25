# Call Framework Analysis — OpenAI Realtime Provider

## 2025-09-24 16:36 PDT — No Greeting; No Two-Way; Pipeline Blocked (Invalid Realtime URL + Capture Gating)

- **Outcome**
- No initial greeting heard.
- No two-way conversation; caller audio was dropped.
- Provider session failed to connect.

- **Key Evidence (from ai-engine logs)**
- Connecting to OpenAI Realtime uses a literal, non-expanded URL string:
  - `Connecting to OpenAI Realtime ... url=${OPENAI_REALTIME_BASE_URL:-wss://api.openai.com/v1/realtime}?model=gpt-4o-realtime-preview-2024-12-17`
- WebSocket client rejects the URL (not ws/wss):
  - `InvalidURI: ${OPENAI_REALTIME_BASE_URL:-wss://api.openai.com/v1/realtime}?model=... isn't a valid URI: scheme isn't ws or wss`
- Immediately after, upstream inbound frames are repeatedly dropped under a TTS protection window:
  - `Dropping inbound during initial TTS protection window ... protect_ms=400 tts_elapsed_ms=0` (many times)

- **Diagnosis**
- **[Root Cause 1] Invalid `base_url` for Realtime:**
  - `config/ai-agent.yaml` used a Bash-style default substitution (`${OPENAI_REALTIME_BASE_URL:-wss://...}`) which is not supported by `os.path.expandvars` in our loader. The literal `${...:-...}` string flowed into `OpenAIRealtimeProvider._build_ws_url()` and produced an invalid WebSocket URI.
  - Result: OpenAI WebSocket never connected; no provider audio or transcript events.
- **[Root Cause 2] Upstream capture disabled → false TTS gating:**
  - New `CallSession` defaults to `audio_capture_enabled=False`. When provider start fails, engine never flips capture back on.
  - `_audiosocket_handle_audio(...)` treats `audio_capture_enabled=False` as "TTS playback active" and applies the initial protection window, so all inbound frames get dropped. This explains the repeating `Dropping inbound during initial TTS protection window ... tts_elapsed_ms=0` lines and the lack of two-way.
- **[Contributing Factor] No automatic greeting for OpenAI:**
  - Unlike Deepgram (which can greet via its agent config), our OpenAI provider only requests a response (`response.create`) after caller audio arrives (via `send_audio() → _ensure_response_request()`). With connection failure and capture disabled, OpenAI never had a chance to emit audio.

- **Remediation Applied (this commit)**
- **Fix Realtime base URL (config):**
  - `config/ai-agent.yaml`: set `providers.openai_realtime.base_url: "wss://api.openai.com/v1/realtime"` (literal).
  - Set `providers.openai_realtime.target_encoding: "ulaw"` explicitly to avoid env-var pitfalls during file playback.
- **Enable upstream capture after provider start (engine):**
  - `src/engine.py::_start_provider_session(...)`: after `await provider.start_session(call_id)`, set `session.audio_capture_enabled=True` when not gated, and sync gauges. This ensures OpenAI receives caller audio immediately after connect.
- **Container refreshed:**
  - Pulled latest code on server and restarted `ai-engine`. `/ready` confirms `ari_connected=true`, `transport_ok=true`, `provider_ok=true`, `ready=true`.

- **Next Steps (Verification on next call)**
- Expect to see:
  - `Connecting to OpenAI Realtime ... url=wss://api.openai.com/v1/realtime?model=...`
  - `OpenAI Realtime session established`
  - `AudioSocket inbound first audio bytes=320` without repeated early protection drops.
  - Provider output sequence: `AgentAudio` chunks → `AgentAudioDone` → `🔊 AUDIO PLAYBACK - Started` and `🔊 PlaybackFinished ... gating_cleared=true`.
- If there is still no greeting at call start:
  - Consider sending an initial `response.create` at connect time (provider-side) or synthesizing a small greeting using our engine’s file-playback path with `llm.initial_greeting`.

- **Improvement Items (not required for next call)**
- **Auto-response at connect:**
  - `src/providers/openai_realtime.py::start_session()`: call `_ensure_response_request()` immediately after `session.update` to ask OpenAI to speak based on `instructions`, even before any caller audio.
- **Handle provider start failures more gracefully:**
  - If `start_session()` raises, flip `session.audio_capture_enabled=True` to avoid repeated protection-window drops, and optionally play a generic "we’re having trouble" prompt.
- **Streamed playback (future):**
  - Wire `downstream_mode=stream` to `StreamingPlaybackManager` for OpenAI provider outputs (PCM16). For this regression, file playback remains the intended path.

---

## 2025-09-24 19:32 PDT — Commits stable (160ms, acked); still no output audio (no greeting)

- **Outcome**
- No initial greeting; no agent audio playback.

- **Key Evidence (server logs)**
- Repeated input conversions: `OpenAI input frame sizes ... dst_bytes=640 src_bytes=320`
- Stable commits: `OpenAI committed input audio ms=160 bytes=5120`
- Acks received: `OpenAI input_audio_buffer ack ... input_audio_buffer.committed`
- Realtime events: `Unhandled ... conversation.item.created`
- No `error` events; no `response.output_audio.delta` or `response.audio.delta` seen; no “first audio chunk” log.

- **Diagnosis**
- Input buffer sizing is fixed and accepted by OpenAI (>=100ms satisfied). However, the model is not emitting audio deltas. Likely causes:
  - Initial `response.create` lacks an explicit greeting directive; generic `instructions` do not compel a first utterance.
  - Session may benefit from server turn detection (`server_vad`) to structure input/output turns.
  - Event variants have been broadened in code, but no output audio events were sent by server in this run.

- **Remediation Plan**
- For greeting: send a targeted `response.create` with a greeting directive, e.g., `response.instructions: "Say to the user '<greeting>'"`.
  - Short-term: set `providers.openai_realtime.instructions` in YAML to an explicit greeting phrase (for the first run).
  - Longer-term: add `providers.openai_realtime.greeting` and wire to `response.create` (fallback to `llm.initial_greeting`).
- Add optional server turn detection in `session.update` controlled via YAML: `providers.openai_realtime.turn_detection.*`.
- Keep input commit threshold at 160ms for stability; refine later.

- **Next Steps**
- Update YAML to provide an explicit greeting instruction for OpenAI and redeploy.
- Optionally enable `turn_detection: server_vad` with sensible thresholds.
- Place a short call; expect: audio commits acknowledged, `response.*audio*.delta` events, “first audio chunk …” log, and playback.

---

## 2025-09-24 18:56 PDT — OpenAI error: input_audio_buffer_commit_empty (no audio heard)

- **Outcome**
- No initial greeting; no audio playback.

- **Key Evidence (server logs)**
- `OpenAI input frame sizes call_id=... src_bytes=320 dst_bytes=640` (8k PCM16 → 16k PCM16 conversion per 20 ms)
- `OpenAI Realtime error event ... code='input_audio_buffer_commit_empty' ... 'Expected at least 100ms of audio, but buffer only has 96.00ms'`

- **Diagnosis**
- We were committing too-fine audio buffers to OpenAI Realtime (sub‑100 ms). The API requires ≥100 ms per commit; our cadence produced ~96 ms sometimes, triggering `input_audio_buffer_commit_empty` and preventing response generation.

- **Remediation Applied**
- `src/providers/openai_realtime.py::send_audio()` now buffers converted 16 kHz PCM16 into `_pending_audio_16k` and only commits when ≥120 ms is accumulated (satisfies ≥100 ms requirement with margin). Commit events are logged:
  - `OpenAI committed input audio ms=... bytes=...`

- **Next Steps**
- With fix deployed, place a short call and expect:
  - `OpenAI committed input audio ms>=120` lines (one every ~6 input frames at 20 ms each).
  - `input_audio_buffer.*` ack logs (append/commit accepted).
  - `response.delta` with `output_audio.delta` followed by `OpenAI Realtime first audio chunk ...` and playback start/finish logs.
- If we still see commit size errors, increase commit threshold to 160–200 ms temporarily and re‑test.

---

## 2025-09-24 17:04 PDT — No Greeting; No Audio (pre-fix run showed invalid URL again)

- **Outcome**
- No initial greeting; no two-way audio; call cleaned up normally.

- **Key Evidence (server logs)**
- `Connecting to OpenAI Realtime  url=${OPENAI_REALTIME_BASE_URL:-wss://api.openai.com/v1/realtime}?model=gpt-4o-realtime-preview-2024-12-17`
- `InvalidURI: ${OPENAI_REALTIME_BASE_URL:-wss://api.openai.com/v1/realtime}?model=... isn't a valid URI: scheme isn't ws or wss`
- `AudioSocket inbound first audio bytes=320` (uplink frames arrived but were not forwarded due to capture gating)

- **Diagnosis**
- This call occurred before the latest config/provider fixes were activated on the server. The OpenAI URL still contained the `${...:-...}` placeholder syntax, so the provider never connected and upstream capture stayed disabled, leading to repeated protection-window drops.

- **Remediation Applied Immediately After This Call**
- YAML set to literal `base_url: "wss://api.openai.com/v1/realtime"`; `voice: "alloy"`; `organization: ""`.
- Provider hardened `_build_ws_url()` to fall back to the default wss endpoint if placeholders or wrong scheme are detected.
- Provider now requests an initial `response.create` at connect to produce a greeting.
- Engine enables `audio_capture_enabled=True` after provider start when not gated.
- Container restarted at 00:10:01Z with providers loaded and readiness green.

- **Next Run (Expected)**
- Logs should show `url=wss://api.openai.com/v1/realtime?...`, followed by `OpenAI Realtime session established` and `OpenAI Realtime first audio chunk ...`.
- Caller should hear an initial greeting (provider-side `response.create`), then two-way turns.

---

## 2025-09-24 18:44 PDT — Session established, then OpenAI error; logging crashed (no audio heard)

- **Outcome**
- No initial greeting; no audio playback; call cleaned up.

- **Key Evidence (server logs)**
- `OpenAI send type=session.update` → `OpenAI send type=response.create` → `OpenAI Realtime session established`
- `Unhandled OpenAI Realtime event event_type=session.created`
- Immediately followed by receive loop exception:
  - `TypeError: ... logger.error(..., event=event) got multiple values for argument 'event'`
- Repeated early lines before session start:
  - `Dropping inbound during initial TTS protection window ... protect_ms=400 tts_elapsed_ms=0`

- **Diagnosis**
- We connected and began the session, but OpenAI emitted an `error` event right after `session.created`.
- Our new error logging used the reserved structlog key `event`, which crashed the receive loop before printing the error payload.
- With the receive loop down, no provider audio could be decoded/emitted; hence no greeting and silent pipeline.

- **Remediation Applied (code committed locally)**
- `src/providers/openai_realtime.py::_handle_event()`: log error payload under `error_event=` to avoid the structlog conflict.
- Additional instrumentation remains in place: control `send` logs, input audio config/first resample sizes, and `input_audio_buffer.*` acks.

- **Next Steps**
- Deploy latest changes to server (git pull) and restart ai-engine.
- Place a short call and capture the now-visible `error_event` payload from OpenAI.
- Patch payload shape accordingly (likely in `_send_session_update()` or `_ensure_response_request()`).

---

## Template for Future Regression Entries

- **Outcome**
- **Key Evidence**
- **Diagnosis**
- **Remediation Applied**
- **Next Steps**
- **Status**

---

## 2025-09-24 21:07 PDT — Server rejected session.audio; handler crash on transcript delta; still no audio

- **Outcome**
- No initial greeting; no agent audio playback.

- **Key Evidence (server logs)**
- Control path OK on connect:
  - `OpenAI send type=session.update` → `OpenAI send type=response.create` → `OpenAI Realtime session established`
- Server timeline items but no audio deltas:
  - `Unhandled ... session.created`, `response.output_item.added`, `conversation.item.created`, `response.content_part.added`
- Server rejected our session payload (unknown field):
  - `invalid_request_error ... Unknown parameter: 'session.audio'`
- Receive loop crashed on transcript delta variant:
  - `AttributeError: 'str' object has no attribute 'get'` at `_handle_event()` when processing `response.audio_transcript.delta` with a string `delta`.

- **Diagnosis**
- The nested `session.audio` schema is not accepted by the current Realtime server variant over WebSocket. This blocked the session configuration (voice/format) and likely prevented output audio generation.
- Our transcript handling assumed `delta` is an object (`{"text": "..."}`) but sometimes it arrives as a plain string. This crashed the receive loop before we could process subsequent events.

- **Remediation Applied (local code)**
- `src/providers/openai_realtime.py::_send_session_update()` now uses flat, accepted session fields:
  - `session.modalities` (e.g., `["audio"]`)
  - `session.input_audio_format: "pcm16"`
  - `session.output_audio_format: "g711_ulaw" | "g711_alaw" | "pcm16"` (mapped from YAML `target_encoding`)
  - `session.voice: "alloy"` (from YAML)
  - `session.turn_detection: {...}` at the session level when enabled
- `response.create` now uses `response.modalities` and explicit `response.instructions`; no `response.audio` object.
- Transcript handlers hardened to accept both string and object deltas for:
  - `response.audio_transcript.delta`
  - `response.output_audio_transcript.delta`

- **Next Steps**
- Deploy these fixes, clear logs, restart `ai_engine`, and place a short call while tailing logs.
- Expected logs (happy path):
  - Accepted control events (no `unknown_parameter`) for `session.update` and `response.create`
  - `response.created` → `response.output_item.added` → `response.output_audio.delta`
  - Playback lifecycle: `AgentAudio` → `AgentAudioDone` → `PlaybackFinished`
- If still silent:
  - Temporarily set `session.output_audio_format: "pcm16"` to rule out any G.711 negotiation issue.
  - Optionally add `session.input_audio_transcription: { model: "whisper-1" }` (if accepted) to surface input transcripts for additional confirmation.

- **Status**
- Code updated locally; deployment scheduled next. Will verify on the next regression call and update this doc with results.
