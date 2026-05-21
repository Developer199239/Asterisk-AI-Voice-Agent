# Asterisk AI Voice Agent — Project Context

## What This Project Is

An open-source (MIT) AI Voice Agent framework that integrates with **Asterisk / FreePBX** using **AudioSocket (TLV/TCP)** and **ARI (Asterisk REST Interface)**. The Python engine runs alongside Asterisk as a Stasis application, streaming raw audio bidirectionally and routing it through configurable STT → LLM → TTS pipelines.

Current version: **v6.5.1**  
Live demo number: **(925) 736-6718** (US only)

---

## Repository Layout

```
main.py                    # Entry point — calls src.engine.main()
src/
  engine.py                # Main orchestrator (monolithic, ~14k lines)
  ari_client.py            # ARI WebSocket client
  config.py / config/      # Pydantic config models + loaders
  audio/
    audiosocket_server.py  # AudioSocket TLV/TCP server
    resampler.py           # µ-law ↔ PCM16, sample-rate conversion
  core/
    session_store.py       # Per-call session state (SessionStore / CallSession)
    conversation_coordinator.py  # Per-turn STT→LLM→TTS orchestration
    vad_manager.py         # EnhancedVADManager (WebRTC VAD + energy)
    streaming_playback_manager.py  # 20ms chunk streaming over AudioSocket/RTP
    playback_manager.py    # File playback via ARI
    call_history.py        # SQLite call log
    transport_orchestrator.py
    adaptive_streaming.py  # Dynamic jitter buffer
  providers/               # Full-agent providers (monolithic STT+LLM+TTS)
    openai_realtime.py     # OpenAI Realtime API (WSS)
    google_live.py         # Google Gemini Live (WSS/gRPC)
    deepgram.py            # Deepgram Voice Agent (WSS)
    elevenlabs_agent.py    # ElevenLabs Conversational AI
    local.py               # Local AI server bridge
  pipelines/               # Modular STT / LLM / TTS adapters
    orchestrator.py        # Resolves adapters per call
    openai.py / google.py / deepgram.py / azure.py / groq.py
    ollama.py / telnyx.py / minimax.py / cambai.py / local.py
  tools/
    base.py                # ToolDefinition, ToolPhase
    registry.py            # Tool lookup
    telephony/             # transfer, hangup, voicemail, attended_transfer
    business/              # email, Google/MS calendar
    http/                  # pre/in/post-call HTTP webhooks
    adapters/              # Provider-specific tool serializers (OpenAI, Google, etc.)
    mcp_tool.py            # MCP tool integration
  mcp/                     # MCP stdio client + manager
  rtp_server.py            # ExternalMedia RTP server (legacy transport)
local_ai_server/
  server.py                # Local AI WebSocket server (~6k lines)
  backends/stt/            # Vosk, Faster-Whisper, Sherpa-ONNX, Whisper.cpp, Kroko
  backends/tts/            # Piper, Kokoro, MeloTTS, Silero
admin_ui/
  backend/main.py          # FastAPI backend
  frontend/                # React TypeScript dashboard
cli/                       # Go CLI tools (15 commands)
config/
  ai-agent.yaml            # Base config (version 6, git-tracked, 6 golden baselines)
  ai-agent.local.yaml      # Operator overrides (git-ignored, written by Admin UI)
data/                      # SQLite call history DB
asterisk_media/            # Generated audio files served by Asterisk
models/                    # AI model cache
```

---

## Asterisk / FreePBX Integration

### How a Call Flows

1. Call hits FreePBX → dialplan context `[from-ai-agent]` → `Stasis(asterisk-ai-voice-agent)`
2. ARI fires `StasisStart` event → engine creates a `CallSession`
3. AudioSocket TCP connection on `:8090` → engine reads UUID handshake (TLV type `0x01`) → ties stream to ARI channel
4. Bidirectional audio: Asterisk sends PCM frames (type `0x10`), engine sends synthesized audio back
5. On `StasisEnd` → engine tears down session, closes provider

### Dialplan Template (FreePBX Custom Contexts)

```asterisk
[from-ai-agent]
exten => s,1,NoOp(Asterisk AI Voice Agent)
 same => n,Set(AI_PROVIDER=google_live)      ; optional per-call override
 same => n,Set(AI_CONTEXT=sales-agent)       ; optional context selection
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

Channel variables `AI_PROVIDER`, `AI_CONTEXT`, `CALLERID(name)`, `CALLERID(num)`, `DIALED_NUMBER` are read by the engine at `StasisStart`.

### ARI Setup (FreePBX UI)

- **Settings → Asterisk REST Interface Users** — create an ARI user
- App name in `config/ai-agent.yaml` → `asterisk.app_name` (default: `asterisk-ai-voice-agent`)
- No native FreePBX module exists — integration is dialplan + ARI config only

### Audio Transports

| Transport | Protocol | Port | Notes |
|---|---|---|---|
| AudioSocket (default) | TLV/TCP | 8090 | Streaming-first, frame-accurate |
| ExternalMedia RTP | UDP | 18080+ | Legacy fallback |

AudioSocket TLV message types:
- `0x01` UUID handshake
- `0x10` Audio frame (bidirectional)
- `0x03` DTMF digit
- `0x00` Terminate
- `0xFF` Error

---

## Configuration System

Three-layer merge (applied in order):

1. `config/ai-agent.yaml` — upstream base (git-tracked, do not edit directly)
2. `config/ai-agent.local.yaml` — operator overrides (git-ignored, Admin UI writes here)
3. `.env` — secrets (API keys, Asterisk credentials)

Key config sections: `asterisk`, `audiosocket`, `external_media`, `barge_in`, `contexts`, `pipelines`, `tools`

### Contexts

Each context in `ai-agent.yaml` defines: `greeting`, `prompt`, `provider`, `profile`, `tools`, `pre_call_tools`, `post_call_tools`. Callers land in `default` unless `AI_CONTEXT` channel variable overrides it.

---

## Provider Architecture

### Full-Agent Providers (monolithic, lowest latency)

| Provider | Transport | Audio In | Audio Out |
|---|---|---|---|
| OpenAI Realtime | WSS | PCM16 24kHz | PCM16 24kHz |
| Google Gemini Live | WSS/gRPC | PCM16 16kHz | PCM16 16kHz |
| Deepgram Voice Agent | WSS | µ-law/PCM16 8kHz | PCM16 24kHz |
| ElevenLabs Agent | WSS | PCM16 | PCM16 |
| Local (local_ai_server) | WS localhost | PCM16 | PCM16 |

### Modular Pipeline Adapters

STT: Google, OpenAI Whisper, Deepgram, Azure (realtime + fast), Vosk, Faster-Whisper, Sherpa-ONNX, Whisper.cpp, Kroko  
LLM: OpenAI GPT, Google Vertex, Ollama, llama.cpp, MiniMax, Telnyx (53+ models)  
TTS: Google, OpenAI, ElevenLabs, Azure, Piper (2000+ voices), Kokoro, MeloTTS, Silero

`PipelineOrchestrator` (`src/pipelines/orchestrator.py`) resolves which adapters to use per call.

---

## Audio Processing

**Inbound:** AudioSocket frame → µ-law→PCM16 decode → resample → WebRTC VAD → STT  
**Outbound:** TTS PCM16 → resample → µ-law encode → 20ms chunk streaming over AudioSocket

Key components:
- `Resampler` (`src/audio/resampler.py`) — NumPy linear interpolation (known quality limitation at telephony rates)
- `EnhancedVADManager` — WebRTC VAD + energy threshold + barge-in gating
- `StreamingPlaybackManager` — 20ms paced chunks, jitter buffer, keepalive watchdog, fallback to ARI file playback
- `AdaptiveBufferController` — dynamic buffer sizing based on network characteristics

---

## Tools System

Tools are defined in `config/ai-agent.yaml` → `tools:` and registered in `src/tools/registry.py`.

**Telephony tools:** `transfer_call`, `hangup_call`, `send_to_voicemail`, `queue_transfer`, `attended_transfer`, `check_extension_status`  
**Business tools:** `send_email`, `google_calendar_*`, `microsoft_calendar_*`, `request_transcript`  
**HTTP tools:** `generic_lookup` (pre-call), `in_call_lookup`, `generic_webhook` (post-call)  
**MCP tools:** via `src/mcp/` — connects to external MCP stdio servers

Tool phases: `pre_call`, `in_call`, `post_call` — defined in `ToolPhase` enum.

---

## Running the Project

```bash
# First time
cp .env.example .env
bash preflight.sh          # generates .env, checks deps

# Start all services
docker compose up -d

# Or with GPU support
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

**Admin UI:** `http://localhost:3003` (JWT auth — `JWT_SECRET` in `.env`)  
**Prometheus metrics:** `http://localhost:15000/metrics`  
**Engine logs:** `docker compose logs -f ai_engine`

### Key Environment Variables (`.env`)

```
ASTERISK_HOST=127.0.0.1
ASTERISK_ARI_PORT=8088
ASTERISK_ARI_USERNAME=
ASTERISK_ARI_PASSWORD=
OPENAI_API_KEY=
DEEPGRAM_API_KEY=
GOOGLE_API_KEY=
ELEVENLABS_API_KEY=
JWT_SECRET=
```

---

## Known Architectural Issues (from expert review)

1. **`src/engine.py` is ~14k lines** — God Object, hard to test, merge conflict risk
2. **No AudioSocket reconnect logic** — TCP drop mid-call = dropped call, no recovery
3. **NumPy linear resampler** — audible artifacts at telephony bit rates; `soxr` would be better
4. **Docker socket mount in admin_ui** — container escape vector; needs socket proxy
5. **No dialplan fallback** — if engine is down, calls drop silent with no audio
6. **SQLite call history** — WAL mode, single-server only; no PostgreSQL migration path
7. **No AMI integration** — can't monitor peer/trunk status or queue stats
8. **No SRTP/SIPS** — media is unencrypted
9. **No native FreePBX module** — operators must edit dialplan manually in Custom Contexts
10. **`local_ai_server/server.py` is ~6k lines** — same monolith problem as engine

---

## Documentation Map

| Topic | File |
|---|---|
| Installation | `docs/INSTALLATION.md` |
| Configuration reference | `docs/Configuration-Reference.md` |
| FreePBX integration | `docs/FreePBX-Integration-Guide.md` |
| Transport comparison | `docs/Transport-Mode-Compatibility.md` |
| Local/offline setup | `docs/LOCAL_ONLY_SETUP.md` |
| Hardware requirements | `docs/HARDWARE_REQUIREMENTS.md` |
| Monitoring / Prometheus | `docs/MONITORING_GUIDE.md` |
| CLI tools | `docs/CLI_TOOLS_GUIDE.md` |
| Admin UI | `docs/ADMIN_UI_GUIDE.md` |
| Tool calling | `docs/TOOL_CALLING_GUIDE.md` |
| Architecture deep-dive | `docs/contributing/architecture-deep-dive.md` |
| Troubleshooting | `docs/TROUBLESHOOTING_GUIDE.md` |
| Provider setup guides | `docs/Provider-*.md` |
| Outbound calling | `docs/OUTBOUND_CALLING.md` |
| MCP integration | `docs/MCP_INTEGRATION.md` |
| Changelog | `CHANGELOG.md` |
| Roadmap | `docs/ROADMAP.md` |
