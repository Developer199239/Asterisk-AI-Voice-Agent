# Milestone 7 — Configurable Pipelines & Hot Reload

## Objective
Allow operators to mix and match STT, LLM, and TTS components (local or cloud) using YAML configuration only, with safe hot-reload support so changes apply without a full restart.

## Success Criteria
- `config/ai-agent.yaml` can define multiple named pipelines (e.g., `pipelines.default`, `pipelines.sales`) with component references.
- `active_pipeline` switch applies after a reload (hot reload or `make engine-reload`) without code edits.
- Regression call succeeds using a custom pipeline composed entirely from configuration.

## Dependencies
- Milestones 5 and 6 complete (streaming defaults, OpenAI provider).
- SessionStore fully authoritative for call state (Milestone 1).

## Work Breakdown

### 7.1 Configuration Schema
- Extend YAML with:
  - `pipelines: { name: { stt: ..., llm: ..., tts: ..., options: {...} } }`
  - `active_pipeline: default`
- Update Pydantic models with validation and defaults.
- Document schema examples (Deepgram-only, mixed local/cloud) in `docs/Architecture.md`.

### 7.2 Pipeline Loader
- Create `src/pipelines/base.py` (if not already present) with factories for STT/LLM/TTS components.
- Update engine startup to instantiate providers/components based on `active_pipeline`.
- Ensure each component implements a common streaming interface so substitutions are seamless.

### 7.3 Hot Reload
- Reuse existing configuration watcher (Milestone 1) or implement `SIGHUP` handler to reload configuration safely.
- On reload:
  - Validate new config
  - Tear down idle pipelines
  - Apply new logging levels / streaming settings
  - Keep active calls untouched (new pipeline applies to next call)
- Log success/failure with clear guidance if reload is rejected.

### 7.4 Regression & Documentation
- Add section to `call-framework.md` describing how to run a call with a non-default pipeline.
- Create example pipeline configs under `examples/pipelines/` if helpful.
- Update `docs/ROADMAP.md` milestone status.

## Deliverables
- Pipeline loader implementation with tests.
- Updated configuration schema and documentation.
- Hot reload support confirmed in regression notes.

## Verification Checklist
- Editing `config/ai-agent.yaml` to point to a different `active_pipeline` followed by `make engine-reload` switches providers on the next call.
- INFO logs confirm pipeline composition (STT/LLM/TTS names) at call start.
- Regression log shows successful call using a non-default pipeline.

## Handover Notes
- Coordinate with Milestone 8 for monitoring hooks (record pipeline name in telemetry/metrics).
- Document any component-specific options required for third-party services so future contributors can add adapters.
