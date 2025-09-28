# GA Readiness Checklist

## Scope
This checklist confirms the Asterisk AI Voice Agent v3.0 is ready for public GA with OpenAI Realtime as the default provider and configurable pipelines for local/cloud mixes.

## Acceptance Gates
- [ ] Documentation validated and current (README, INSTALLATION, Deployment, FreePBX Guide, Architecture, Roadmap)
- [ ] Default provider set to OpenAI Realtime; smoke test passes on fresh install
- [ ] Example pipelines verified and referenced in docs
- [ ] Logging defaults to INFO; YAML-configurable via `logging.level`; local server supports `LOCAL_LOG_LEVEL`
- [ ] Quick Start path < 15 minutes, includes health check and 1 call
- [ ] Release bundle excludes logs and IDE rule files
- [ ] Community assets prepared (CONTRIBUTING, issue templates) and release notes drafted

## Quick GA Smoke Test (Fresh Environment)
1. Clone repo and configure:
   ```bash
   git clone <repo>
   cd Asterisk-AI-Voice-Agent
   cp config/ai-agent.example.yaml config/ai-agent.yaml  # if present; otherwise edit existing
   cp .env.example .env
   # set ASTERISK_*, OPENAI_API_KEY (and DEEPGRAM_API_KEY if testing TTS)
   ```
2. Start services:
   ```bash
   docker-compose up --build -d
   make test-health
   ```
3. Place a call via AudioSocket-first dialplan (see FreePBX guide). Expect:
   - Greeting
   - STT partials/finals
   - OpenAI response
   - TTS playback and clean finish

## Required Docs
- README: 15‑minute Quick Start, pipelines overview, logging snippet
- INSTALLATION: prerequisites + references to Quick Start and AudioSocket dialplan
- Deployment_Process: safe deploy, verify, health
- FreePBX-Integration-Guide: minimal AudioSocket context and pipeline selection
- Architecture: pipeline orchestrator, adapters, defaults
- Roadmap: Milestone 7 marked complete, Milestone 8 planned

## Examples to Verify
- `examples/pipelines/local_only.yaml`
- `examples/pipelines/hybrid_deepgram_openai.yaml`
- `examples/pipelines/cloud_only_openai.yaml` (optional to add if missing)
- `examples/pipelines/cloud_only_google.yaml`

## Logging Controls
- YAML:
  ```yaml
  logging:
    level: info  # debug|info|warning|error|critical
  ```
- Local server:
  - `LOCAL_LOG_LEVEL=INFO` (default) or `DEBUG` when troubleshooting.

## Release Packaging
- Exclude logs and IDE rule files: `logs/**`, `*.log`, `.cursor/**`, `.windsurf/**`
- Provide release notes with highlights, defaults, upgrade steps

## Community & Support
- Enable GitHub Discussions; add issue templates
- Link to FreePBX/Asterisk forum thread
- Provide a basic troubleshooting section with common errors and fixes
