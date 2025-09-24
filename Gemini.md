# Gemini.md — GA Build & Ops Guide

This playbook summarizes how Gemini should operate on the Asterisk AI Voice Agent project. It mirrors `Agents.md`, the Windsurf rules, and the milestone instruction files under `docs/milestones/`.

## Mission & Scope
- **Primary objective**: Deliver the GA roadmap (Milestones 5–8) so the agent streams clean audio by default, supports both Deepgram and OpenAI Realtime, allows configurable pipelines, and exposes an optional monitoring stack.
- Always verify that `audio_transport=audiosocket` remains the default, with file playback as fallback when streaming pauses.
- Reference milestone instruction files before starting work:
  - `docs/milestones/milestone-5-streaming-transport.md`
  - `docs/milestones/milestone-6-openai-realtime.md`
  - `docs/milestones/milestone-7-configurable-pipelines.md`
  - `docs/milestones/milestone-8-monitoring-stack.md`

## Architectural Snapshot
- Two containers: `ai-engine` (Hybrid ARI controller + AudioSocket server) and `local-ai-server` (local STT/LLM/TTS).
- Upstream audio: Asterisk AudioSocket → `ai-engine` → provider (Deepgram/OpenAI/local).
- Downstream audio: Streaming transport managed by `StreamingPlaybackManager`; automatic fallback to tmpfs-based file playback.
- State: `SessionStore` + `ConversationCoordinator` orchestrate capture gating, playback, and metrics.

## Configuration Keys to Watch
- `audio_transport`, `downstream_mode`, `audiosocket.format`.
- Streaming defaults (`streaming.min_start_ms`, `low_watermark_ms`, `fallback_timeout_ms`, `provider_grace_ms`).
- Pipeline definitions (`pipelines`, `active_pipeline`) once Milestone 7 lands.
- Logging levels per component (set via YAML when hot reload is implemented).

## Development Workflow
1. Work on the `develop` branch locally.
2. Use Makefile targets for builds/deploys (`make deploy`, `make deploy-force`, `make server-logs`, etc.).
3. Before touching the server, **commit and push** your changes; the server must `git pull` the exact commit you just pushed prior to any `docker-compose up --build`.
4. Never use `docker-compose restart` for code updates—always rebuild.

### Deployment Environment
- Server: `root@voiprnd.nemtclouddispatch.com`
- Repo: `/root/Asterisk-Agent-Develop`
- Shared media: `/mnt/asterisk_media`

### Key Commands (local or server)
- `make deploy` / `make deploy-force`
- `make server-logs`, `make server-clear-logs`
- `make monitor-up` / `make monitor-down` (Milestone 8)
- `docker-compose logs -f ai-engine`, `docker-compose logs -f local-ai-server`

## GA Milestones — Gemini Focus
- **Milestone 5**: Implement streaming pacing config, telemetry, and documentation updates.
- **Milestone 6**: Add OpenAI Realtime provider with codec-aware streaming.
- **Milestone 7**: Support YAML-defined pipelines with hot reload.
- **Milestone 8**: Ship optional Prometheus + Grafana monitoring stack.
- After completion, assist with GA regression runs and documentation polish.

## Regression & Troubleshooting Workflow
1. Clear logs (`make server-clear-logs`).
2. Tail `ai-engine`, `local-ai-server`, and Asterisk logs during calls.
3. Record call ID, streaming metrics, and tuning hints in `docs/regressions/*.md` and `call-framework.md`.
4. For streaming issues, inspect buffer depth logs and fallback counters; adjust YAML settings accordingly.

## Hot Reload Expectations
- Configuration watcher (or `make engine-reload`) refreshes streaming defaults, logging levels, and pipeline definitions without dropping active calls.
- Always validate config changes (`docs/milestones/milestone-7-configurable-pipelines.md`) before reloading.

## Monitoring Stack Notes
- Optional services added in Milestone 8 expose dashboards at the configured HTTP port.
- Ensure `/metrics` is reachable and that Grafana dashboards load streaming and latency panels.
- Document sentiment/transcript hooks for future enhancements.

## Logging & Metrics Etiquette
- Run at INFO in GA mode; enable DEBUG only when instructed and remember to revert.
- Capture `/metrics` snapshots after regression calls to populate dashboards.

## Deliverables Checklist Before Hand-off
- Updated documentation (`docs/Architecture.md`, `docs/ROADMAP.md`, milestone files, rule files).
- Regression notes logged with call IDs and audio quality assessment.
- Telemetry hints reviewed; YAML defaults adjusted if streaming restarts persist.

## Troubleshooting Steps (Recap)
1. Clear logs.
2. Reproduce call while tailing `ai-engine`, `local-ai-server`, and `/var/log/asterisk/full`.
3. Build a timeline; identify streaming restarts, buffer drops, or provider disconnects.
4. Apply fixes guided by milestone docs, then rerun regression.

---
*Keep this file aligned with `Agents.md` and `.windsurf/rules/asterisk_ai_voice_agent.md`. Update it whenever milestone scope or workflow changes.*
