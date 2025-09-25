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

## Template for Future Regression Entries

- **Outcome**
- **Key Evidence**
- **Diagnosis**
- **Remediation Applied**
- **Next Steps**
- **Status**
