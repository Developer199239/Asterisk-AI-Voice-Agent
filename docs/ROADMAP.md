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

## Milestone 5 — Streaming Transport Preview (Feature Flag) (Planned)
- **Goal**: Offer an experimental outbound streaming path to enable barge-in work.
- **Tasks**:
  - Add feature flag (e.g., `downstream_mode=stream`) with fall back to file playback.
  - Implement minimal streaming pipeline (AudioSocket send or RTP) behind the flag.
  - Document expected behaviour and how to revert to file mode.
- **Acceptance**:
  - Enabling the flag starts streaming transport and logs readiness; disabling reverts cleanly.
  - Regression call demonstrates that the pipeline either streams audio or falls back without error.

## Quick Regression Checklist
1. Clear logs: `make logs --tail=0 ai-engine` (or `make server-clear-logs` remotely).
2. Call into the AI context.
3. Confirm logs for: ExternalMedia channel creation, RTP audio, provider input, playback start/finish, cleanup.
4. Run `make test-health` (or `curl $HEALTH_URL`) to ensure `active_calls: 0`.
5. Archive findings in `call-framework.md`.

Keep this roadmap updated after each milestone to help any collaborator—or future AI assistant—pick up where we left off.
