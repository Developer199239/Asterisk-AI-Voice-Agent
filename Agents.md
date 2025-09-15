# Agents.md — Build & Ops Guide for Codex Agent

This document captures how I (the agent) work most effectively on this repo. It distills the project rules, adds hands‑on runbooks, and lists what I still need from you to build, deploy, and test quickly.

## Mission & Scope
- Primary: Implement AudioSocket‑first upstream capture with file‑based playback downstream; stabilize for testing on the server.
- Next phase (feature‑flagged): Streaming TTS over AudioSocket with barge‑in, jitter buffers, keepalives, telemetry.

## Architecture Snapshot (Current) — Runtime Contexts (Always Current)
- Two containers: `ai-engine` (ARI + AudioSocket) and `local-ai-server` (models).
- Upstream (caller → engine): AudioSocket TCP into the engine.
- Downstream (engine → caller): ARI file playback via tmpfs for low I/O latency.
- Providers: pluggable via `src/providers/*` (local, deepgram, etc.).

Active contexts and call path (server):
- `ivr-3` (example) → `from-ai-agent` → Stasis(asterisk-ai-voice-agent)
- Engine originates `Local/<exten>@ai-agent-media-fork/n` to start AudioSocket
- `ai-agent-media-fork` generates canonical UUID, calls `AudioSocket(UUID, host:port)`, sets `AUDIOSOCKET_UUID=${EXTEN}` for binder
- Engine binds socket to caller channel; sets upstream input mode `pcm16_8k`; provider greets immediately (no demo tone)

## Feature Flags & Config
- `audio_transport`: `audiosocket` (default) | `legacy` (fallback to ARI snoop).
- `downstream_mode`: `file` (default) | `stream` (next phase, not active yet).
- Streaming knobs (`config/ai-agent.yaml`): `streaming.sample_rate_hz`, `chunk_duration_ms`, `jitter_buffer_ms`, `keepalive_ms`, `timeouts`, `barge_in.*`.
- Env overrides: `AUDIO_TRANSPORT`, `DOWNSTREAM_MODE`.

## Pre‑flight Checklist (Local or Server)
- Asterisk:
  - `app_audiosocket.so` loaded: `module show like audiosocket`.
  - Dialplan context uses AudioSocket + Stasis.
  - ARI enabled (http.conf, ari.conf) and user has permissions.
- System:
  - Docker + docker‑compose installed.
  - `/mnt/asterisk_media` mounted as tmpfs (or fast storage) and mapped for the engine.
- Secrets:
  - `.env` present with `ASTERISK_HOST`, `ASTERISK_ARI_USERNAME`, `ASTERISK_ARI_PASSWORD`, provider API keys.

## Dialplan Example (AudioSocket + Stasis)
```
[ai-voice-agent]
exten => s,1,NoOp(Starting AI Voice Agent with AudioSocket)
 same => n,Set(AUDIOSOCKET_HOST=127.0.0.1)
 same => n,Set(AUDIOSOCKET_PORT=8090)
 same => n,Set(AUDIOSOCKET_UUID=${UNIQUEID})
 same => n,AudioSocket(${AUDIOSOCKET_UUID},${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT},ulaw)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

## Active Contexts & Usage (Server)
- Entry context (`from-ai-agent`): hands call directly to `Stasis(asterisk-ai-voice-agent)`.
- Media-fork context (`ai-agent-media-fork`): originated by the engine to start AudioSocket.
  - Generates canonical UUID and calls `AudioSocket(UUID, host:port)`
  - Sets `AUDIOSOCKET_UUID=${EXTEN}` to trigger engine binder to map the socket to the original caller channel.
  - Minimal `s` extension keeps the Local ;1 leg alive.

Current server snippet (working):
```
[from-ai-agent]
exten => s,1,NoOp(Handing call directly to Stasis for AI processing)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[ai-agent-media-fork]
exten => _X.,1,NoOp(Local channel starting AudioSocket for ${EXTEN})
 same => n,Answer()
 same => n,Set(AUDIOSOCKET_HOST=127.0.0.1)
 same => n,Set(AUDIOSOCKET_PORT=8090)
 same => n,Set(AUDIOSOCKET_UUID=${EXTEN})
 same => n,Set(AS_UUID_RAW=${SHELL(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen 2>/dev/null)})
 same => n,Set(AS_UUID=${TOUPPER(${FILTER(0-9A-Fa-f-,${AS_UUID_RAW})})})
 same => n,ExecIf($[${LEN(${AS_UUID})} != 36]?Set(AS_UUID=${TOUPPER(${FILTER(0-9A-Fa-f-,${SHELL(uuidgen 2>/dev/null)})})}))
 same => n,NoOp(AS_UUID=${AS_UUID} LEN=${LEN(${AS_UUID})})
 same => n,AudioSocket(${AS_UUID},${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT})
 same => n,Hangup()

; keep ;1 leg alive
exten => s,1,NoOp(Local)
 same => n,Wait(60)
 same => n,Hangup()
```

## Runtime Context — Quick Checks Before Each Test
- Health: `curl http://127.0.0.1:15000/health` → `ari_connected`, `audiosocket_listening`, `active_calls`, providers’ readiness.
- Engine logs (tail): `docker-compose logs -f ai-engine`
  - Expect: `AudioSocket server listening`, `AudioSocket connection bound to channel`, `Set provider upstream input mode ... pcm16_8k`.
  - First inbound chunks: `AudioSocket inbound chunk bytes=... first8=...`.
- Asterisk logs:
  - Confirm Local originate and `AudioSocket(UUID,127.0.0.1:8090)` (no parse errors).
  - No `getaddrinfo(..., "8090,ulaw")` errors — use host:port only.

## Next Moves — At A Glance
- Two-way audio: Confirm transcripts appear in `local-ai-server` logs after you speak.
  - If empty, verify engine shows `pcm16_8k` set and inbound chunk sizes align (~320 bytes typical for 20ms PCM16@8k).
- Stability: Keepalive is enabled from engine to avoid AudioSocket idle timeouts.
- Streaming phase: When ready, enable `downstream_mode=stream` (feature-flag) to return TTS over AudioSocket; keep file fallback.

## Common Commands
- Build & run locally (both services): `docker-compose up -d --build`
- Logs (engine): `docker-compose logs -f ai-engine`
- Logs (local models): `docker-compose logs -f local-ai-server`
- Containers: `docker-compose ps`
- Asterisk CLI (host): `asterisk -rvvvvv`

## Development Workflow
1) Edit code on `develop`.
2) `docker-compose restart ai-engine` for code‑only changes.
3) Full rebuild only on dependency/image changes.
4) Keep `.env` out of git; configure providers via env and YAML.

## Testing Workflow
- Smoke test AudioSocket ingest:
  - Confirm: `AudioSocket server listening ...:8090` in engine logs.
  - Place a call into the AudioSocket + Stasis context, watch for:
    - `AudioSocket connection accepted` and `bound to channel` in logs.
    - Provider session started.
  - Verify file‑based playback (ensure sound URIs without file extensions).

## Observability & Troubleshooting
- Engine logs: ARI connection errors, AudioSocket binds, playback IDs.
- Asterisk logs: `/var/log/asterisk/full` — verify actual playback and errors.
- Known gotcha: Do not append `.ulaw` to `sound:` URIs (Asterisk adds extensions automatically).

## Ports & Paths
- AudioSocket: TCP 8090 (default; configurable via `AUDIOSOCKET_PORT`).
- ARI: default 8088 HTTP/WS (from Asterisk).
- Shared media dir: `/mnt/asterisk_media/ai-generated/`.

## Deploy (Server) — Runbook
Assumptions: server `root@voiprnd.nemtclouddispatch.com`, repo at `/root/Asterisk-Agent-Develop`, branch `develop`.
```
ssh root@voiprnd.nemtclouddispatch.com \
  'cd /root/Asterisk-Agent-Develop && \
   git checkout develop && git pull && \
   docker-compose up -d --build ai-engine local-ai-server && \
   docker-compose ps && \
   docker-compose logs -n 100 ai-engine'
```
Then place a test call. Expect:
- `AudioSocket connection accepted` → `bound to channel` → provider session → playback.
If no connection arrives in time, the engine will fall back to legacy snoop (logged warning).

## Acceptance (Current Release)
- Upstream audio via AudioSocket reaches provider (or snoop fallback).
- Downstream responses play via file‑based playback reliably.
- P95 response time ~≤ 2s under basic load; robust cleanup of temp audio files.

## Next Phase (Streaming TTS)
- Enable `downstream_mode=stream` (when implemented): full‑duplex streaming, barge‑in (<300ms cancel‑to‑listen), jitter buffer, keepalives, telemetry.
- Keep `file` path as fallback.

## TaskMaster (MCP) Utilities
- Tool client scripts: `scripts/tm_tools.mjs` (list/info/call tools) and `scripts/check_taskmaster_mcp.mjs`.
- Typical calls:
  - `node scripts/tm_tools.mjs list`
  - `node scripts/tm_tools.mjs info parse_prd`
  - `node scripts/tm_tools.mjs call update_task '{"id":"5","append":true,...}'`

## What I Still Need From You
1) Server details to deploy:
   - SSH host/user, repo path (confirm `/root/Asterisk-Agent-Develop`).
   - Whether to rebuild both `ai-engine` and `local-ai-server`, or only `ai-engine`.
2) Asterisk specifics:
   - Confirmation that `app_audiosocket` is available and dialplan context is in place.
   - ARI user creds are correct and reachable from the container.
3) Environment:
   - `.env` on server with required secrets and `ASTERISK_HOST`.
4) Test plan:
   - Extension/DID to dial for the test call.
   - Preferred provider (`default_provider`); confirm local vs deepgram.

## Nice‑to‑Haves to Work Faster
- Health endpoint in ai‑engine (optional) exposing ARI, AudioSocket, provider status.
- A Makefile or npm scripts for common ops (build, logs, ps, deploy).
- A dev compose override for mapping ports explicitly if host networking isn’t used.
- Sample `.env.example` entries for ARI and providers reflecting production usage.
- Pre‑baked dialplan snippet files in `docs/snippets/` for quick copy/paste.

## Rollback Plan
- Switch `audio_transport=legacy` to re‑enable snoop capture.
- Revert `downstream_mode` to `file` (default).
- `git checkout` previous commit on develop and rebuild `ai-engine` if needed.

## Security Notes
- Keep API keys and ARI credentials strictly in `.env` (never commit them).
- Restrict AudioSocket listener to `127.0.0.1` when engine and Asterisk are co‑located; otherwise secure the path appropriately.
