---
trigger: always_on
description: Development rules and guidelines for the Asterisk AI Voice Agent v3.0 project
globs: src/**/*.py, *.py, docker-compose.yml, Dockerfile, config/ai-agent.yaml
---

# Asterisk AI Voice Agent v3.0 — Windsurf Rules

## GA Scope & Architecture
- Maintain the two-container design (`ai-engine`, `local-ai-server`) with AudioSocket-first ingest and automatic fallback to file playback; ExternalMedia/RTP remains a safety path only.
- Preserve the Hybrid ARI lifecycle in `engine.py`; extend `_handle_caller_stasis_start_hybrid()` and related helpers rather than bypassing originate/bridge steps.
- Continue migrating state into `SessionStore`, `PlaybackManager`, and `ConversationCoordinator`; new logic should interact through these abstractions so `/health` and metrics stay trustworthy.

## Workflow Essentials
- Work on the `develop` branch, verify locally, then commit and push before touching the server. Production tests pull from `/root/Asterisk-Agent-Develop` and run `docker-compose up -d --build` (use `--no-cache` when behaviour looks stale).
- Makefile commands (`make deploy`, `make server-logs`, `make test-local`, etc.) are recommended but optional; regardless of tooling, never rely on `docker-compose restart` for code updates and never bypass git by copying files into containers.

## Streaming Transport Guardrails
- Treat `config/ai-agent.yaml` as the source of truth for streaming defaults (`streaming.min_start_ms`, `low_watermark_ms`, `fallback_timeout_ms`, `provider_grace_ms`, `jitter_buffer_ms`) and `barge_in.post_tts_end_protection_ms`.
- Keep `StreamingPlaybackManager` pacing provider frames in 20 ms slices, sustaining jitter buffer depth before playback and pausing when depth drops below the low watermark.
- Preserve post-TTS guard windows so the agent does not hear its own playback; ConversationCoordinator must stay responsible for gating toggles and metrics.

## Pipelines & Providers
- Register new STT/LLM/TTS adapters via `src/pipelines/orchestrator.py`, extend the YAML schema, update examples in `examples/pipelines/`, and refresh milestone docs.
- Providers must honour μ-law/8 kHz input from AudioSocket, emit events compatible with Prometheus metrics, and expose readiness through `/health`.
- Capture regression details (call IDs, tuning outcomes) in `docs/regressions/` and keep `call-framework.md` aligned.
- Local provider: rely on the new idle-finalized STT, async TinyLlama execution, and the engine’s ingest/transcript queues so slow local LLM responses never starve AudioSocket.

## Testing & Observability
- Regression loop: clear logs, place an AudioSocket call, watch streaming depth/fallback logs, scrape `/metrics` for latency histograms, then archive findings.
- Update `docs/Architecture.md`, `docs/ROADMAP.md`, and milestone instructions when architecture or workflow changes ship; rules across IDEs must stay synchronized.

## GPT-5 Prompting Guidance
- **Precision & consistency**: Align guidance with `Agents.md`, `Gemini.md`, and Cursor rules; avoid conflicts when editing prompts or workflows.
- **Structured prompts**: Use XML-style wrappers, for example:

  ```xml
  <code_editing_rules>
    <guiding_principles>
      - audio transport stays AudioSocket-first with file fallback
    </guiding_principles>
    <tool_budget max_calls="5"/>
  </code_editing_rules>
  ```

- **Reasoning effort**: Reserve `high` for milestone-level changes (streaming transport, pipeline orchestration); choose medium or low for incremental updates.
- **Tone calibration**: Keep language collaborative; avoid all-caps or overly forceful mandates that encourage overcorrection.
- **Planning & self-reflection**: For zero-to-one work, embed a `<self_reflection>` block prompting the agent to outline a brief plan before execution.
- **Eagerness control**: Bound exploration with explicit tool budgets or `<persistence>` directives, stating when to assume reasonable defaults versus re-checking.

Maintain parity between this file, `Agents.md`, `Gemini.md`, and `.cursor/rules/asterisk_ai_voice_agent.mdc`; update all of them together when guidance changes.
