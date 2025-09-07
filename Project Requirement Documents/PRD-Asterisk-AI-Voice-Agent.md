<context>
## Overview
An open-source AI Voice Agent that registers as a SIP extension on Asterisk/FreePBX and answers calls using configurable AI providers. Designed for small and medium businesses across all expertise levels, with a simple Docker-based deployment and CLI-driven configuration.

## Core Features
- SIP extension registration against Asterisk/FreePBX (Asterisk 16+)
- Multi-provider AI support (MVP: OpenAI; Next: Azure, Deepgram; Future: local via Ollama)
- Multi-language conversations (auto-detect/switch; provider-dependent)
- Single, consistent voice per engine instance (provider-specific)
- User-defined prompts/instructions; per-call session context
- Optional MCP tool integrations (e.g., calendar, web automation) via configuration
- Basic health checks and comprehensive Docker-aggregated logs
- CLI-only configuration for MVP (no UI)

## User Experience
- Clone → configure → run → register extension in FreePBX → route calls → AI answers
- Everyday user guide included; examples and diagrams; defaults that work out of the box
</context>

<PRD>
## Technical Architecture

### System Components
- SIP Client: registers with Asterisk and manages SIP dialogs (REGISTER/INVITE/BYE)
- RTP Audio Handler: handles media (G.711 µ-law/A-law, G.722) and buffering
- AI Engine Core: conversation loop, context, provider selection, tool calling
- Provider Integrations: OpenAI (MVP), Azure, Deepgram; future: Ollama (local)
- MCP Integration: optional tool layer exposed to AI (generic, pluggable)
- Config Manager: JSON + environment variables; sensible defaults
- Logging & Health: structured logs to Docker; simple readiness/liveness checks

### High-Level Flow
1) Admin creates a PJSIP extension in FreePBX/Asterisk
2) Engine container starts and registers to that extension
3) Calls routed to the extension are answered by the engine
4) Audio flows via RTP; engine performs STT → LLM → TTS via chosen provider
5) Conversation continues with per-call context; call ends on BYE or timeout

### Data Models
- Configuration: SIP creds, provider name, API key, voice, prompt/instructions, logging toggles
- Call Session: call-id, caller-id, language, conversation context, timestamps
- Logs: SIP events, provider calls, transcripts (optional), errors

### APIs & Protocols
- SIP (RFC 3261): REGISTER, INVITE/200/ACK, BYE; Digest auth
- RTP: audio streams; codec negotiation via SDP
- Provider APIs: OpenAI Realtime/Chat, Azure Speech, Deepgram
- MCP: generic tool invocation if enabled

### Infrastructure
- Docker container (host networking recommended on PBX host)
- Asterisk 16+ / FreePBX compatible routing
- No database required for MVP; filesystem logs only

## Development Roadmap

### MVP (Phase 1)
- SIP registration and basic call handling
- OpenAI provider (multi-language, single configurable voice)
- JSON config + env vars; defaults that work
- Logs in Docker; optional transcription toggle
- Basic health endpoints (readiness/liveness) and CLI help

### Phase 2
- Azure & Deepgram providers
- MCP tool integrations (calendar, web automation) with safe defaults
- Better error handling & provider fallback

### Future
- Local model support via Ollama
- Multi-instance and load balancing guidance
- Optional web UI for configuration

## Logical Dependency Chain
1) SIP Client & RTP handling → 2) Config system → 3) OpenAI provider → 4) Call loop → 5) Logging/health → 6) Additional providers → 7) MCP tools → 8) Local models

## Risks and Mitigations
- SIP/RTP complexity: reuse reliable libraries; limit codecs to G.711/G.722 initially
- Provider variability: clear errors; env-based toggles; default to OpenAI
- User setup errors: opinionated defaults; validation; concise docs with examples
- Privacy of transcripts: opt-in via env; clear retention behavior

## Appendix

### Code Reuse From Existing Project
- `docker-setup/engine/src/config.py`: configuration loading patterns (adapt to JSON + env)
- `docker-setup/engine/src/engine.py`: conversation loop and provider selection logic
- `docker-setup/engine/src/call.py`: call/session state management patterns
- `docker-setup/engine/src/utils.py`: parsing helpers and logging patterns
- `docker-setup/engine/src/openai_api.py`, `azure_api.py`, `deepgram_api.py`: provider request/response patterns (map to SIP-first flow)
- `docker-setup/engine/src/rtp.py`, `codec.py`, `opus.py`: audio handling references (limit MVP to G.711/G.722,ulaw,alaw)

### New Components To Build
- SIP Client (REGISTER/INVITE/BYE, SDP): `src/sip_client.py`
- RTP Handler (decode/encode G.711/G.722): `src/audio_handler.py`
- Provider interface abstraction: `src/providers/base.py`; adapters for OpenAI/Azure/Deepgram
- MCP integration layer (optional, generic): `src/mcp_client.py`
- JSON config schema and validator: `config/engine.json` + `src/config_schema.py`

### Configuration (JSON + Env)
- Required env vars: `SIP_EXTENSION`, `SIP_PASSWORD`, `ASTERISK_HOST`, `PROVIDER`, provider API key env (`OPENAI_API_KEY`/`AZURE_SPEECH_KEY`/`DEEPGRAM_API_KEY`)
- Optional env vars: `VOICE`, `PROMPT`, `INSTRUCTIONS`, `TRANSCRIPTION_ENABLED=true|false`, `LOG_LEVEL=info`
- Defaults: OpenAI provider, English auto-detect, safe voice default, transcription off

### Setup Steps (Everyday User)
1) Create PJSIP extension in FreePBX (note extension & secret)
2) Clone repo and copy example config; set env vars (extension, password, provider key)
3) Start Docker container; confirm it registers (shows online in FreePBX)
4) Route a test call to the extension; verify AI answers
5) Inspect logs (`docker logs`) for troubleshooting; enable transcripts if needed

### Diagrams

Call flow (SIP/RTP):
Caller → Asterisk/FreePBX → (SIP INVITE) → AI Engine → Provider (STT/LLM/TTS) → AI Engine → (RTP audio) → Asterisk → Caller

### Success Criteria (MVP)
- Engine registers as defined extension
- A call routed to the extension is answered by the AI and can be ended cleanly
- Works with OpenAI provider using defaults

</PRD>

