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

## Milestone 6 — OpenAI Realtime Voice Agent (Planned)
- **Goal**: Add an OpenAI Realtime provider so Deepgram ↔️ OpenAI switching happens via configuration alone. Milestone instructions: `docs/milestones/milestone-6-openai-realtime.md`.
- **Dependencies**: Milestone 5 complete; OpenAI API credentials configured.
- **Primary Tasks**:
  - Implement `src/providers/openai_realtime.py` with streaming audio events.
  - Extend configuration schema and env documentation (`README.md`, `docs/Architecture.md`).
- **Acceptance**:
  - Setting `default_provider: openai_realtime` results in a successful regression call.
  - Streaming telemetry mirrors Deepgram baseline; codec negotiation automatic.

## Milestone 7 — Configurable Pipelines & Hot Reload (Planned)
- **Goal**: Support multiple named pipelines (STT/LLM/TTS) defined in YAML, with hot reload for rapid iteration. See `docs/milestones/milestone-7-configurable-pipelines.md`.
- **Dependencies**: Milestones 5 and 6 complete; SessionStore authoritative for call state.
- **Primary Tasks**:
  - Extend configuration schema (pipelines + active_pipeline) and loader.
  - Implement pipeline factory interfaces; ensure streaming components obey common contracts.
  - Ensure config watcher reloads pipelines/logging levels safely.
- **Acceptance**:
  - Swapping `active_pipeline` applies on next call after reload.
  - Regression call succeeds using a custom pipeline defined in YAML only.

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
