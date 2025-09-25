# AI Voice Agent Roadmap

This roadmap tracks the open-source enablement work for the Asterisk AI Voice Agent. Each milestone includes scope, primary tasks, and quick verification steps that should take less than a minute after deployment.

## Milestone 1 — SessionStore-Only State (✅ Completed)
- **Goal**: Remove remaining legacy dictionaries from `engine.py` and rely exclusively on `SessionStore` / `PlaybackManager` for call state.
- **Tasks**:
  - Replace reads/writes to `active_calls`, `caller_channels`, etc. with SessionStore helpers.
  - Update cleanup paths so `/health` reflects zero active sessions after hangup.
  - Add lightweight logging when SessionStore migrations hit unknown fields.
- **Acceptance**:
  - Single test call shows: ExternalMedia channel created, RTP frames logged, gating tokens add/remove, `/health` returns `active_calls: 0` within 5s of hangup.
  - No `active_calls[...]` or similar dict mutations remain in the codebase.

## Milestone 2 — Provider Switch CLI (✅ Completed)
- **Goal**: Provide one command to switch the active provider, restart the engine, and confirm readiness.
- **What We Shipped**:
  - Added `scripts/switch_provider.py` and Makefile targets `provider-switch`, `provider-switch-remote`, and `provider-reload` for local + server workflows.
  - Health endpoint now reports the active provider readiness so the change can be validated at a glance.
- **Verification**:
  - `make provider=<name> provider-reload` updates `config/ai-agent.yaml`, restarts `ai-engine`, and the next call uses the requested provider. Logged on 2025-09-22 during regression.

## Milestone 3 — Model Auto-Fetch (✅ Completed)
- **Goal**: Automatically download and cache local AI models based on the host architecture.
- **What We Shipped**:
  - Added `models/registry.json` and the `scripts/model_setup.py` utility to detect hardware tier, download the right STT/LLM/TTS bundles, and verify integrity.
  - Makefile task `make model-setup` (documented in Agents/Architecture) calls the script and skips work when models are already cached.
- **Verification**:
  - First-run downloads populate `models/` on both laptops and the server; subsequent runs detect cached artifacts and exit quickly. Local provider boots cleanly after `make model-setup`.

## Milestone 4 — Conversation Coordinator & Metrics (✅ Completed)
- **Goal**: Centralize gating/barge-in decisions and expose observability.
- **What We Shipped**:
  - Introduced `ConversationCoordinator` (SessionStore-integrated) plus Prometheus gauges/counters for capture state and barge-in attempts.
  - Health endpoint now exposes a `conversation` summary and `/metrics` serves Prometheus data.
- **Verification**:
  - 2025-09-22 regression call shows coordinator toggling capture around playback, `ai_agent_tts_gating_active` returning to zero post-call, and `/metrics` scrape succeeding from the server.

## Milestone 5 — Streaming Transport Production Readiness (✅ Completed)
- **Goal**: Promote the AudioSocket streaming path to production quality with adaptive pacing, configurable defaults, and telemetry. Details and task breakdown live in `docs/milestones/milestone-5-streaming-transport.md`.
- **What We Shipped**:
  - Configurable streaming defaults in `config/ai-agent.yaml` (`min_start_ms`, `low_watermark_ms`, `fallback_timeout_ms`, `provider_grace_ms`, `jitter_buffer_ms`).
  - Post‑TTS end protection window (`barge_in.post_tts_end_protection_ms`) to prevent agent self‑echo when capture resumes.
  - Deepgram input alignment to 8 kHz (`providers.deepgram.input_sample_rate_hz: 8000`) to match AudioSocket frames.
  - Expanded YAML comments with tuning guidance for operators.
  - Regression docs updated with findings and resolutions.
- **Verification (2025‑09‑24 13:17 PDT)**:
  - Two-way telephonic conversation acceptable end‑to‑end; no echo‑loop in follow‑on turns.
  - Gating toggles around playback as expected; post‑TTS guard drops residual frames.
  - Operators can fine‑tune behaviour via YAML without code changes.

## Milestone 6 — OpenAI Realtime Voice Agent (✅ Completed)
- **Goal**: Add an OpenAI Realtime provider so Deepgram ↔️ OpenAI switching happens via configuration alone. Milestone instructions: `docs/milestones/milestone-6-openai-realtime.md`.
- **Dependencies**: Milestone 5 complete; OpenAI API credentials configured.
- **Primary Tasks**:
  - Implement `src/providers/openai_realtime.py` with streaming audio events.
  - Extend configuration schema and env documentation (`README.md`, `docs/Architecture.md`).
  - Align provider payloads with the latest OpenAI Realtime guide:
    - Use `session.update` with nested `audio` schema and `output_modalities` (e.g., `session.audio.input.format`, `session.audio.input.turn_detection`, `session.audio.output.format`, `session.audio.output.voice`).
    - Remove deprecated/unknown fields (e.g., `session.input_audio_sample_rate_hz`).
    - Use `response.create` without `response.audio`; rely on session audio settings. For greeting, send explicit `response.instructions`.
    - Add `event_id` on client events and handle `response.done`, `response.output_audio.delta`, `response.output_audio_transcript.*`.
  - Greeting behavior: send `response.create` immediately on connect with explicit directive (e.g., “Please greet the user with the following: …”).
  - VAD/commit policy:
    - When server VAD is enabled (`session.audio.input.turn_detection`), stream with `input_audio_buffer.append` only; do not `commit`.
    - When VAD is disabled, serialize commits and aggregate ≥160 ms per commit.
- **What We Shipped**:
  - Implemented `src/providers/openai_realtime.py` with robust event handling and transcript parsing.
  - Fixed keepalive to use native WebSocket `ping()` frames (no invalid `{"type":"ping"}` payloads).
  - μ-law alignment: requested `g711_ulaw` from OpenAI and passed μ-law bytes directly to Asterisk (file playback path), eliminating conversion artifacts.
  - Greeting on connect using `response.create` with explicit instructions.
  - Hardened error logging to avoid structlog conflicts; added correlation and visibility of `input_audio_buffer.*` acks.
  - Added YAML streaming tuning knobs (`min_start_ms`, `low_watermark_ms`, `jitter_buffer_ms`, `provider_grace_ms`) and wired them into `StreamingPlaybackManager`.

- **Verification (2025‑09‑25 08:59 PDT)**:
  - Successful regression call with initial greeting; two-way conversation sustained.
  - Multiple agent turns played cleanly (e.g., 16000B ≈2.0s and 40000B ≈5.0s μ-law files) with proper gating and `PlaybackFinished`.
  - No OpenAI `invalid_request_error` on keepalive; ping fix validated.

- **Acceptance**:
  - Setting `default_provider: openai_realtime` results in a successful regression call with greeting and two-way audio.
  - Logs show `response.created` → output audio chunks → playback start/finish with gating clear; no `unknown_parameter` errors.

## Milestone 7 — Configurable Pipelines & Hot Reload (Planned)
- **Goal**: Support multiple named pipelines (STT/LLM/TTS) defined in YAML, with hot reload for rapid iteration. See `docs/milestones/milestone-7-configurable-pipelines.md`.
- **Dependencies**: Milestones 5 and 6 complete; SessionStore authoritative for call state.
- **Primary Tasks**:
  - Extend configuration schema (pipelines + active_pipeline) and loader.
  - Implement pipeline factory interfaces; ensure streaming components obey common contracts.
  - Ensure config watcher reloads pipelines/logging levels safely.
  - Expose provider endpoints and runtime knobs via YAML (`config/ai-agent.yaml`):
    - `providers.deepgram.ws_url` (default: `wss://agent.deepgram.com/v1/agent/converse`)
    - `providers.openai_realtime.base_url` (already supported)
    - Models/voices/greeting/instructions and logging levels
    - Document defaults and allow hot reload for these fields
  - Incorporate enhancements inspired by OpenSIPS AI Voice Connector:
    - OpenAI server turn detection in `session.update` with YAML: `providers.openai_realtime.turn_detection.{type,silence_duration_ms,threshold,prefix_padding_ms}` (default `server_vad`).
    - Serialize OpenAI input commits with an audio lock; expose `providers.openai_realtime.commit_threshold_ms` (default 160–200 ms) to avoid `input_audio_buffer_commit_empty`.
    - Expand Realtime event compatibility: handle `response.output_audio.delta` and `response.audio.delta` variants, plus transcript events (`response.audio_transcript.*`).
    - Optional tool/function-calling bridge: map `response.function_call_arguments.done` to engine actions (`terminate_call`, `transfer_call`); YAML: `providers.openai_realtime.tools`.
    - Optional server-side transcription toggle: `providers.openai_realtime.input_audio_transcription.model` (e.g., `whisper-1`); surface transcript logs when enabled.
    - Playback polish: optionally pad final 20 ms with silence to avoid end-of-utterance clicks.
- **Acceptance**:
  - Swapping `active_pipeline` applies on next call after reload.
  - Regression call succeeds using a custom pipeline defined in YAML only.
  - Changing Deepgram/OpenAI endpoints or voice/model via YAML takes effect on next call after reload.
  - For OpenAI: greeting is heard on connect via `response.create` using `llm.initial_greeting`; no `input_audio_buffer_commit_empty` errors; outbound audio handled for both `response.output_audio.delta` and `response.audio.delta`; transcripts logged when enabled; tool calls (if enabled) trigger mapped actions.

## Milestone 8 — Optional Monitoring & Analytics Stack (Planned)
- **Goal**: Provide an opt-in Prometheus + Grafana stack for streaming metrics and future analytics. Instructions: `docs/milestones/milestone-8-monitoring-stack.md`.
- **Dependencies**: Milestones 5–7 expose required telemetry.
- **Primary Tasks**:
  - Add monitoring services to `docker-compose.yml` and Make targets (`monitor-up`, `monitor-down`).
  - Ship starter dashboards visualising streaming health and latency.
  - Document setup in `docs/Monitoring.md` (or equivalent section in Architecture).
- **Acceptance**:
  - `make monitor-up` brings stack online; dashboards show live call metrics.
  - Monitoring stack remains optional and does not impact base deployment when disabled.

## GA Release Readiness
- **Goal**: Tag the GA release once Milestones 5–8 are complete.
- **Tasks**:
  - Run regression suite for Deepgram and OpenAI providers with default config.
  - Publish telemetry-backed tuning guide and finalise documentation (README, Architecture, Monitoring).
  - Create release notes summarising milestone deliverables and upgrade steps.
- **Acceptance**:
  - GA tag published; quick-start instructions verified on clean environment.
  - IDE rule files updated to reflect final workflow.

## Quick Regression Checklist
1. Clear logs: `make logs --tail=0 ai-engine` (or `make server-clear-logs` remotely).
2. Call into the AI context.
3. Confirm logs for: ExternalMedia channel creation, RTP audio, provider input, playback start/finish, cleanup.
4. Run `make test-health` (or `curl $HEALTH_URL`) to ensure `active_calls: 0`.
5. Archive findings in `call-framework.md`.

Keep this roadmap updated after each milestone to help any collaborator—or future AI assistant—pick up where we left off.
