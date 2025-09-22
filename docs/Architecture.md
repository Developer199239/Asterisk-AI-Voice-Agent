# Asterisk AI Voice Agent - Architecture Documentation

## System Overview

The Asterisk AI Voice Agent v3.0 is a **two-container, modular conversational AI system** that enables **real-time, two-way voice conversations** through Asterisk/FreePBX systems. It uses Asterisk's **ExternalMedia** feature with RTP for reliable real-time audio capture and **file-based playback** for robust media handling.

Note: In the current release, downstream audio is delivered via file-based playback for maximum robustness. A full‑duplex streaming TTS path is planned as a next phase and will be gated by feature flags.

## Architecture Overview

### Hybrid ARI + SessionStore + Conversation Coordinator

The production code still follows the **Hybrid ARI** call-control pattern and is in the process of migrating its state into the new `SessionStore` APIs:

- **Hybrid ARI**: `_handle_caller_stasis_start_hybrid()` answers the caller, creates a mixing bridge, and either originates a Local channel or spawns an ExternalMedia channel before handing media over to the rest of the engine.
- **SessionStore (in-progress)**: The engine now instantiates `SessionStore` and `PlaybackManager` (see `src/core/`), and new flows such as playback gating and RTP SSRC mapping query this shared store. Legacy dictionaries like `self.active_calls` and `self.caller_channels` still exist for backwards compatibility and will be phased out as handlers are rewritten to push/read data exclusively through `SessionStore`.
- **ConversationCoordinator (new)**: `ConversationCoordinator` subscribes to session changes, toggles audio capture, records barge-in attempts, schedules capture fallbacks, and keeps Prometheus gauges aligned with each call’s state. PlaybackManager delegates all gating changes to the coordinator.
- **Local Provider Tuning**: The local AI server now reads `LOCAL_LLM_*` and `LOCAL_STT/TTS_*` environment variables so operators can swap GGUF/ONNX assets or lower response latency without rebuilding images.

This staged architecture provides:
- **Improved State Consistency**: Critical paths (playback gating, RTP routing, TTS cleanup) now rely on a single store.
- **Type Safety for New Code**: New helpers work with dataclasses (`CallSession`, `PlaybackRef`) instead of ad-hoc dicts, while older handlers are refactored gradually.
- **Observability**: `/metrics` now exposes `ai_agent_tts_gating_active`, `ai_agent_audio_capture_enabled`, and `ai_agent_barge_in_events_total` counters, while `/health` includes a `conversation` block summarising gating and capture status.
- **Maintainability Path**: The separation between call control, state management, and observability is documented and enforced for new features, while older sections remain untouched until their migration tickets are completed.

## Recent Progress and Current State

- **✅ Production Ready**: Real calls run end-to-end using the Hybrid ARI flow with ExternalMedia capture.
- **✅ SessionStore Adoption Started**: Playback gating, RTP SSRC tracking, and health reporting use `SessionStore`, with remaining handlers scheduled for migration.
- **✅ ExternalMedia RTP Integration**: The engine accepts RTP (UDP) on port 18080, resamples to 16 kHz, and forwards frames through the VAD pipeline.
- **✅ Downstream Playback**: `PlaybackManager` writes μ-law files to `/mnt/asterisk_media/ai-generated` and triggers deterministic bridge playbacks with gating.
- **✅ Complete Pipeline**: RTP → VAD/Fallback → Provider WebSocket → LLM/TTS → File playback all operate in production.
- **⚠️ Ongoing Cleanup**: Legacy dict-based state and verbose logging remain until remaining handlers are refactored to the new core abstractions.
- **ℹ️ Fallback Audio Processing**: Configuration defaults to 4-second buffers (`fallback_interval_ms=4000`) to guarantee STT ingestion when VAD is silent.

### Health Endpoint

- A minimal health endpoint is available from the `ai-engine` (default `0.0.0.0:15000/health`). It reports:
  - `ari_connected`: ARI WebSocket/HTTP status
  - `rtp_server_running`: whether the RTP server is active
- `active_calls`: number of tracked calls (via `SessionStore.get_session_stats()`)
  - `providers`: readiness flags per provider
  - `audio_transport`: current transport mode (externalmedia)
  
Configure via env:
- `HEALTH_HOST` (default `0.0.0.0`), `HEALTH_PORT` (default `15000`).

### Known Constraints

- RTP server requires port 18080 to be available for ExternalMedia integration
- ExternalMedia channels must be properly bridged with caller channels for audio flow
- SSRC mapping is critical for audio routing - first RTP packet automatically maps SSRC to caller
- TTS gating requires proper PlaybackFinished event handling for feedback prevention
- Fallback audio processing uses 4-second intervals (`fallback_interval_ms=4000`) for reliable STT processing

## Next Steps

- **Performance Optimization**
  - Optimize LLM response speed (currently 30-60 seconds, target <5 seconds)
  - Switch to faster models (Phi-3-mini, Qwen2-0.5B) or reduce max_tokens
  - Implement response caching for common queries
- **Enhanced Observability**
  - Add detailed logging for RTP packet processing and SSRC mapping
  - Monitor fallback audio processing performance
  - Track TTS gating effectiveness and PlaybackFinished events
- **Streaming TTS (feature‑flagged)**
  - Implement `downstream_mode=stream` for full-duplex streaming
  - Add jitter buffer and barge-in support
  - Keep file fallback for reliability
- **Production Enhancements**
  - Add comprehensive error monitoring and alerting
  - Implement call quality metrics and reporting
  - Add support for multiple concurrent calls

### Roadmap Tracking
Ongoing milestones and their acceptance criteria live in `docs/ROADMAP.md`. Update that file after each deliverable so any collaborator—or tool-specific assistant—can resume work without manual hand-off.

## Architecture Diagrams

### 1. EXTERNALMEDIA CALL FLOW 🎯

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ASTERISK      │    │   AI ENGINE     │    │   LOCAL AI      │    │   SHARED MEDIA  │
│   (PJSIP/SIP)   │    │   CONTAINER     │    │   SERVER        │    │   DIRECTORY     │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │                       │
         │ 1. Incoming Call     │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 2. ExternalMedia Stream│                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 3. StasisStart Event │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 4. Answer Channel     │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 5. Real-time Audio    │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │                       │ 6. Forward to Local AI Server                 │
         │                       ├──────────────────────►│                       │
         │                       │                       │                       │
         │                       │                       │ 7. STT Processing    │
         │                       │                       ├──────────────────────►│
         │                       │                       │                       │
         │                       │                       │ 8. LLM Processing    │
         │                       │                       ├──────────────────────►│
         │                       │                       │                       │
         │                       │                       │ 9. TTS Synthesis     │
         │                       │                       ├──────────────────────►│
         │                       │                       │                       │
         │                       │ 10. Audio Response    │                       │
         │                       │◄──────────────────────┤                       │
         │                       │                       │                       │
         │ 11. Save Audio File   │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 12. Play Audio File   │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 13. Call Complete     │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
```

### 2. DEEPGRAM PROVIDER CALL FLOW 🌐

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ASTERISK      │    │   AI ENGINE     │    │   DEEPGRAM      │    │   OPENAI        │
│   (PJSIP/SIP)   │    │   CONTAINER     │    │   CLOUD         │    │   CLOUD         │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │                       │
         │ 1. Incoming Call     │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 2. ExternalMedia Stream│                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 3. StasisStart Event │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 4. Answer Channel     │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 5. Real-time Audio    │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │                       │ 6. Forward to Deepgram                       │
         │                       ├──────────────────────►│                       │
         │                       │                       │                       │
         │                       │                       │ 7. STT + LLM + TTS   │
         │                       │                       ├──────────────────────►│
         │                       │                       │                       │
         │                       │ 8. Audio Response    │                       │
         │                       │◄──────────────────────┤                       │
         │                       │                       │                       │
         │ 9. Save Audio File   │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 10. Play Audio File  │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 11. Call Complete    │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
```

### 3. EXTERNALMEDIA SERVER ARCHITECTURE 🎧

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ASTERISK      │    │   AI ENGINE     │    │   PROVIDER      │
│   ExternalMedia   │    │   ExternalMedia   │    │   SYSTEM        │
│   (Port 18080)   │    │   Server        │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │ 1. TCP Connection     │                       │
         ├──────────────────────►│                       │
         │                       │                       │
         │ 2. Raw Audio Stream   │                       │
         ├──────────────────────►│                       │
         │                       │                       │
         │                       │ 3. Process Audio      │
         │                       ├──────────────────────►│
         │                       │                       │
         │                       │ 4. AI Response        │
         │                       │◄──────────────────────┤
         │                       │                       │
         │ 5. File Playback      │                       │
         │◄──────────────────────┤                       │
         │                       │                       │
```

## Key File Architecture

```
src/
├── engine.py                    # 🎯 Hybrid ARI orchestrator (legacy dicts + SessionStore bridge)
│   ├── _handle_stasis_start()   # Entry point for caller/local/external-media channels
│   ├── _on_rtp_audio()          # Routes RTP frames through VAD/fallback and to providers
│   └── on_provider_event()      # Handles AgentAudio events from providers
│
├── core/
│   ├── models.py                # Typed dataclasses (CallSession, PlaybackRef, ProviderSession)
│   ├── session_store.py         # Central store for call/session/playback state
│   └── playback_manager.py      # Deterministic playback + gating logic
│
├── rtp_server.py               # 🎧 ExternalMedia RTP server (UDP listener on port 18080)
│   ├── start()                  # Bind UDP socket and launch receiver loop
│   ├── _rtp_receiver()          # Parse RTP headers, resample μ-law → PCM16 16 kHz
│   └── engine_callback          # Dispatches SSRC-tagged audio back to engine
│
├── providers/
│   ├── base.py                  # AIProviderInterface abstract class
│   ├── deepgram.py              # 🌐 Cloud provider (WebSocket streaming)
│   └── local.py                 # 🏠 Local provider (bridges to local AI server via WebSocket)
│
├── ari_client.py                # Asterisk REST Interface client
└── config.py                    # Pydantic configuration models + loader
```

## Critical Differences

| **Aspect** | **ExternalMedia Architecture** | **Previous Snoop Architecture** |
|------------|------------------------------|----------------------------------|
| **Audio Input** | RTP (UDP) via ExternalMedia | ARI ChannelAudioFrame events |
| **Reliability** | Guaranteed real-time stream | Unreliable event-based system |
| **Asterisk Config** | Requires dialplan modification | No dialplan changes needed |
| **Connection Type** | UDP media stream + ARI control | WebSocket event subscription |
| **Audio Format** | Raw ulaw stream | Base64 encoded frames |
| **Error Handling** | Connection-based recovery | Event-based error handling |
| **Performance** | Lower latency, higher throughput | Higher latency, event overhead |

## ExternalMedia Integration

### Call Flow: ExternalMedia Model

The current implementation keeps Asterisk in control of the media pipe while the engine coordinates call state and audio processing.

1. **Call Initiation**: A new call hits the Stasis dialplan context (`from-ai-agent` or similar), handing control to `engine.py`.
2. **ExternalMedia Origination**: `_handle_caller_stasis_start_hybrid()` answers the caller, creates a mixing bridge, and originates an ExternalMedia channel via ARI (`_start_external_media_channel`). When that channel enters Stasis, the engine bridges it with the caller and records the mapping in `SessionStore`.
3. **Audio Stream Starts**: Once bridged, Asterisk streams μ-law RTP packets to the engine’s `RTPServer` (default `0.0.0.0:18080`). `RTPServer` parses RTP headers, resamples audio to 16 kHz, and calls `_on_rtp_audio(ssrc, pcm_16k)`.
4. **Real-time Conversation**:
   - `_on_rtp_audio` tracks the SSRC→call association in `SessionStore`, applies VAD / fallback buffering, and forwards PCM frames to the active provider through `provider.send_audio`.
   - The provider (Deepgram or Local WebSocket server) performs STT → LLM → TTS and emits AgentAudio events back to the engine.
5. **Media Playback**:
   - `PlaybackManager.play_audio` writes the synthesized μ-law bytes to `/mnt/asterisk_media/ai-generated`, registers a gating token in `SessionStore`, and instructs ARI to play the file on the bridge with a deterministic playback ID.
6. **Cleanup**:
   - `PlaybackManager.on_playback_finished` handles the `PlaybackFinished` event, clears the gating token, and removes the temporary audio file.

This orchestration leverages ExternalMedia for reliable inbound audio while keeping outbound playback file-based until streaming TTS is released.

## FreePBX Dialplan Configuration

### Working Dialplan Implementation

The system uses a simple, effective dialplan that directly hands calls to the Stasis application:

```asterisk
[from-ai-agent]
exten => s,1,NoOp(Handing call directly to Stasis for AI processing)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[ai-externalmedia]
exten => s,1,NoOp(ExternalMedia + RTP AI Voice Agent)
 same => n,Answer()
 same => n,Wait(1)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### Dialplan Contexts Explained

**`[from-ai-agent]`**:
- **Purpose**: Direct call routing to AI processing
- **Usage**: Main entry point for incoming calls
- **Flow**: Call → Stasis → AI Engine → RTP Server
- **Benefits**: Simple, reliable, no complex audio handling

**`[ai-externalmedia]`**:
- **Purpose**: ExternalMedia context for RTP audio processing
- **Usage**: Alternative entry point with explicit ExternalMedia setup
- **Flow**: Call → Answer → Wait → Stasis → AI Engine
- **Benefits**: Explicit audio setup, better for complex scenarios

### Integration Steps

1. **Add to FreePBX**: Copy the dialplan contexts to your FreePBX dialplan
2. **Route Calls**: Configure your inbound routes to use `from-ai-agent` context
3. **Test**: Place test calls to verify Stasis application receives calls
4. **Monitor**: Check AI engine logs for successful call processing

### Optional: ExternalMedia RTP Bridging
In deployments that require RTP/SRTP interop, an optional path using Asterisk `ExternalMedia` may be enabled to bridge media via RTP. This is not required for the default ExternalMedia architecture and should be considered only when standards-based RTP interop is necessary.

## Next Phase: Streaming TTS over ExternalMedia Gateway
To further reduce latency and enable true barge‑in, the next phase will introduce downstream streaming back to Asterisk via the same ExternalMedia gateway.

- Transport: full‑duplex streaming (ulaw/slinear ↔ PCM16) without file writes in steady state
- Barge‑in: detect inbound speech during playback and cancel/attenuate TTS
- Reliability: heartbeats, timeouts, reconnection with exponential backoff
- Observability: latency/jitter, queue depths, underruns/overruns, reconnect counters

This capability will be guarded by configuration flags so the system can fall back to the legacy file‑based playback path when needed.

## Real-Time Conversation Management

### RTP Server Pattern
Two-way audio hinges on the `RTPServer` implementation in `src/rtp_server.py`:

- **Transport**: UDP socket bound to `0.0.0.0:18080` (configurable via YAML) – Asterisk’s `ExternalMedia()` application sends 20 ms μ-law frames to this port.
- **Packet Handling**: `_rtp_receiver()` parses RTP headers, tracks expected sequence numbers/packet loss, converts μ-law to PCM16, and resamples 8 kHz audio to 16 kHz using `audioop.ratecv`.
- **Engine Callback**: Every decoded frame is delivered back to `engine._on_rtp_audio(ssrc, pcm_16k)` where VAD, fallback buffering, and provider routing are performed. SSRCs are mapped to call sessions on the first packet through `SessionStore`.
- **Outbound Audio**: Downstream audio remains file-based (no RTP transmit path yet); playback continues to flow through ARI bridges managed by `PlaybackManager`.

### State Management
Call lifecycle is tracked across both the legacy dictionaries and the new `SessionStore`:
- **Connecting**: Caller enters Stasis, bridge is created, and ExternalMedia channel is originated.
- **Streaming**: ExternalMedia RTP arrives; SSRC mapping enables per-call routing into the VAD pipeline.
- **Processing**: Providers receive buffered frames via `send_audio`; responses transition conversation state to `processing` until playback completes.
- **Speaking**: `PlaybackManager` writes μ-law files, toggles gating tokens, and awaits `PlaybackFinished` events.
- **Cleanup**: `_cleanup_call()` tears down bridges/channels and removes sessions from both legacy maps and `SessionStore`.

### Connection & Error Handling
- **Per-call Isolation**: Each SSRC maps to a single call; `RTPServer` maintains lightweight `RTPSession` stats (packet loss, jitter buffer state).
- **Resilience**: Packet loss and out-of-order packets are logged; fallback buffering ensures speech still reaches STT if VAD misses it.
- **Resource Cleanup**: `engine.stop()` stops the RTP server and `SessionStore.cleanup_expired_sessions()` removes stale entries.

### Performance Targets
- **Audio Latency**: Maintain <200 ms decode/dispatch for inbound RTP frames.
- **End-to-End Response**: Aim for <2 s voice response; provider timeout watchdogs reset conversations after 30 s.
- **Streaming STT**: Fallback sends 4 s audio chunks (configurable) when VAD is silent to keep transcripts flowing.
- **Parallel Processing**: Greeting playback gates AudioSocket capture until TTS completes to avoid echo.

## Testing and Verification

### ExternalMedia Testing
- **Socket Availability**: Confirm the RTP server binds to UDP port 18080 (default) without collisions.
- **Audio Stream Testing**: Stream μ-law audio over ExternalMedia and verify RTP frames reach `_on_rtp_audio`.
- **Provider Integration**: Ensure buffered audio reaches the active provider WebSocket session.
- **Error Handling**: Simulate packet loss / SSRC churn and monitor recovery logging.

### Critical Testing Points
- **RTP Server**: Must be listening on UDP port 18080 (or configured override)
- **SSRC Mapping**: Must associate the first packet on each SSRC with the active call
- **Audio Format Handling**: Must process μ-law audio correctly
- **Provider Integration**: Must forward audio to correct provider
- **File Playback**: Must successfully play generated audio to callers
- **Connection Cleanup**: Must properly close connections on call end

## Troubleshooting Guide

### ExternalMedia-Specific Issues

**No RTP Packets Observed**:
- Check that the RTP server is running on UDP port 18080 (or configured port)
- Verify the dialplan invokes `ExternalMedia()` with the correct host/port
- Confirm firewall rules allow UDP traffic on the configured port

**Audio Not Received**:
- Verify the ExternalMedia channel is established (confirm `StasisStart` for the caller and ExternalMedia entries)
- Check audio format compatibility (μ-law when `external_media.codec=ulaw`)
- Monitor RTP server logs for packet receipt and decoder errors

**Connection Drops**:
- Confirm Asterisk keeps the ExternalMedia channel bridged; unbridged channels stop media immediately
- Check network stability between Asterisk and the container hosting the RTP server
- Review RTP server logs for timeouts (`last_packet_at`) and packet-loss counters

**Performance Issues**:
- Monitor RTP packet loss and jitter metrics emitted by `RTPServer`
- Check VAD/fallback buffer sizes in engine logs for overflows
- Verify provider processing speed (watch WebSocket send queue depth)

When issues arise:
1. Check RTP server logs for packet activity and SSRC mapping events
2. Verify Asterisk dialplan configuration
3. Send test RTP packets (e.g., `rtpplay`, `pjsip send media`) to UDP port 18080
4. Monitor audio stream processing
5. Check provider integration and response times
6. Verify file-based playback functionality
