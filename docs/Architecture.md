# Asterisk AI Voice Agent - Architecture Documentation

## System Overview

The Asterisk AI Voice Agent v3.0 is a **two-container, modular conversational AI system** that enables **real-time, two-way voice conversations** through Asterisk/FreePBX systems. It uses Asterisk's **AudioSocket** feature for reliable real-time audio capture and **file-based playback** for robust media handling.

Note: In the current release, downstream audio is delivered via file-based playback for maximum robustness. A full‑duplex streaming TTS path is planned as a next phase and will be gated by feature flags.

## Recent Progress and Current State

- AudioSocket capture via Local media‑fork is working end‑to‑end:
  - Dialplan originates `Local/<uuid_ext>@ai-agent-media-fork/n`.
  - Dialplan generates a canonical hyphenated UUID for the AudioSocket app and passes only `host:port` (no codec arg) to avoid port parsing issues on Asterisk 18.
  - The Stasis app binds the accepted AudioSocket connection to the original caller channel using the `AUDIOSOCKET_UUID` varset from the dialplan.
- Downstream playback is stable using bridge file playback; initial “demo‑congrats” and provider greeting confirmed audible.
- Upstream codec alignment fixed:
  - Asterisk delivers PCM16@8k over AudioSocket for this build.
  - Engine now sets the Local provider upstream input mode to `pcm16_8k` on bind (and on headless accept), ensuring STT receives valid PCM16 and transcripts are produced.
  - Added lightweight inbound audio diagnostics (first chunk sizes/preview) to validate flow during bring‑up and troubleshooting.

### Health Endpoint

- A minimal health endpoint is available from the `ai-engine` (default `0.0.0.0:15000/health`). It reports:
  - `ari_connected`: ARI WebSocket/HTTP status
  - `audiosocket_listening`: whether the AudioSocket TCP server is active
  - `active_calls`: number of tracked calls
  - `providers`: readiness flags per provider
  
Configure via env:
- `HEALTH_HOST` (default `0.0.0.0`), `HEALTH_PORT` (default `15000`).

### Known Constraints

- AudioSocket app on this Asterisk requires canonical UUID (36‑char with hyphens). Non‑canonical or newline‑tainted values are rejected.
- The AudioSocket app on this build expects two arguments only: `UUID, host:port`. Supplying a third codec argument causes service resolution to fail.
- A stale Stasis app (`standalone-local-test`) generates noisy “missed message” logs; removal/disable recommended.

## Next Steps

- Observability
  - Add concise logging around inbound AudioSocket TLV framing (first chunk sizes, inferred format) and provider input mode decisions.
  - Optional health endpoint from `ai-engine` reporting ARI status, AudioSocket listener, and provider readiness.
- Robustness
  - Guard binder path with additional sanity checks and timeouts; surface bind success/fail in logs.
  - Handle websocket reconnects to `local-ai-server` with backoff; propagate status to engine logs.
- Streaming TTS (feature‑flagged)
  - Implement `downstream_mode=stream` to return agent audio over AudioSocket, with jitter buffer and barge‑in.
  - Keep file fallback for reliability.
- Cleanup
  - Remove/disable the stale `standalone-local-test` Stasis app in Asterisk to reduce log clutter.

## Architecture Diagrams

### 1. AUDIOSOCKET CALL FLOW 🎯

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ASTERISK      │    │   AI ENGINE     │    │   LOCAL AI      │    │   SHARED MEDIA  │
│   (PJSIP/SIP)   │    │   CONTAINER     │    │   SERVER        │    │   DIRECTORY     │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │                       │
         │ 1. Incoming Call     │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 2. AudioSocket Stream│                       │                       │
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
         │ 2. AudioSocket Stream│                       │                       │
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

### 3. AUDIOSOCKET SERVER ARCHITECTURE 🎧

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ASTERISK      │    │   AI ENGINE     │    │   PROVIDER      │
│   AudioSocket   │    │   AudioSocket   │    │   SYSTEM        │
│   (Port 8090)   │    │   Server        │    │                 │
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
├── engine.py                    # 🎯 MAIN ORCHESTRATOR
│   ├── _handle_stasis_start()   # Entry point for all calls
│   ├── _create_provider()       # Factory for Deepgram/Local providers
│   ├── on_provider_event()      # Handles AgentAudio events
│   └── _play_ai_audio()         # File-based audio playback
│
├── audiosocket_server.py        # 🎧 NEW: AudioSocket TCP Server
│   ├── start_server()           # Start TCP server on port 8090
│   ├── handle_connection()      # Handle per-call TCP connections
│   ├── process_audio_stream()   # Real-time audio processing
│   └── forward_to_provider()    # Send audio to AI providers
│
├── providers/
│   ├── base.py                  # AIProviderInterface abstract class
│   ├── deepgram.py              # 🌐 CLOUD PROVIDER
│   │   ├── start_session()      # WebSocket connection to Deepgram
│   │   ├── send_audio()         # Forward AudioSocket → WebSocket
│   │   ├── _receive_loop()      # WebSocket → AgentAudio events
│   │   └── speak()              # Inject text to Deepgram
│   │
│   └── local.py                 # 🏠 LOCAL PROVIDER
│       ├── start_session()      # Load STT/LLM/TTS models
│       ├── send_audio()         # AudioSocket → STT processing
│       ├── speak()              # Text → TTS → AgentAudio events
│       └── _synthesize_tts_audio() # TTS synthesis
│
├── ari_client.py                # Asterisk REST Interface client
└── config.py                    # Configuration management
```

## Critical Differences

| **Aspect** | **AudioSocket Architecture** | **Previous Snoop Architecture** |
|------------|------------------------------|----------------------------------|
| **Audio Input** | TCP stream via AudioSocket | ARI ChannelAudioFrame events |
| **Reliability** | Guaranteed real-time stream | Unreliable event-based system |
| **Asterisk Config** | Requires dialplan modification | No dialplan changes needed |
| **Connection Type** | Persistent TCP per call | WebSocket event subscription |
| **Audio Format** | Raw ulaw stream | Base64 encoded frames |
| **Error Handling** | Connection-based recovery | Event-based error handling |
| **Performance** | Lower latency, higher throughput | Higher latency, event overhead |

## AudioSocket Integration

### Call Flow: AudioSocket Model

The new architecture provides a guaranteed media path by leveraging Asterisk's AudioSocket feature, treating our application as a pure controller.

1. **Call Initiation**: A new call enters a dialplan context that first calls the `AudioSocket()` application, then the `Stasis()` application.
2. **Audio Stream Starts**: Asterisk establishes a TCP connection to the `AudioSocketServer` running inside the `ai-engine` and immediately begins streaming raw audio.
3. **StasisStart**: The `Engine` receives the `StasisStart` event via ARI, determines the provider, and answers the call.
4. **Real-time Conversation**:
   - The `AudioSocketServer` receives raw audio chunks and forwards them to the active AI provider.
   - The provider processes the audio (STT -> LLM -> TTS).
5. **Media Playback**:
   - The provider sends the synthesized TTS audio back to the `ai-engine`.
   - The `AriClient` writes this audio to a unique file in the shared directory.
   - It sends a `channels.play` command to Asterisk, telling it to play the sound file.
6. **Cleanup**:
   - The `AriClient` listens for the `PlaybackFinished` event from Asterisk.
   - The event handler immediately deletes the audio file from the shared directory.

This model is the most robust and performant, avoiding the unreliable `ChannelAudioFrame` events and the complexity of manual RTP handling.

### Optional: ExternalMedia RTP Bridging
In deployments that require RTP/SRTP interop, an optional path using Asterisk `ExternalMedia` may be enabled to bridge media via RTP. This is not required for the default AudioSocket architecture and should be considered only when standards-based RTP interop is necessary.

## Next Phase: Streaming TTS over AudioSocket Gateway
To further reduce latency and enable true barge‑in, the next phase will introduce downstream streaming back to Asterisk via the same AudioSocket gateway.

- Transport: full‑duplex streaming (ulaw/slinear ↔ PCM16) without file writes in steady state
- Barge‑in: detect inbound speech during playback and cancel/attenuate TTS
- Reliability: heartbeats, timeouts, reconnection with exponential backoff
- Observability: latency/jitter, queue depths, underruns/overruns, reconnect counters

This capability will be guarded by configuration flags so the system can fall back to the legacy file‑based playback path when needed.

## Real-Time Conversation Management

### AudioSocket Server Pattern
The core of two-way audio functionality is the `AudioSocketServer` class that manages the TCP connection and audio streaming:

```python
class AudioSocketServer:
    def __init__(self, port: int = 8090):
        self.port = port
        self.active_connections = {}  # Per-call connection management
        self.provider_manager = None
    
    async def start_server(self):
        # Start TCP server on specified port
        # Handle incoming connections from Asterisk
    
    async def handle_connection(self, reader, writer):
        # Process real-time audio stream
        # Forward to active AI provider
        # Manage connection lifecycle
```

### State Management
Each call maintains its own state with explicit transitions:
- **Connecting**: Establishing AudioSocket TCP connection
- **Streaming**: Receiving real-time audio from caller
- **Processing**: STT → LLM → TTS pipeline execution
- **Speaking**: Playing TTS audio to caller
- **Idle**: Waiting for next input

### Connection Management
- **Per-call Isolation**: Each call gets its own TCP connection
- **Connection Pooling**: Manage multiple concurrent connections
- **Error Recovery**: Automatic reconnection on connection loss
- **Resource Cleanup**: Ensure connections are closed on call end

### Performance Targets
- **Audio Latency**: < 200ms (AudioSocket advantage)
- **End-to-End Response**: < 2 seconds
- **Streaming STT**: Partial results for faster response
- **Parallel Processing**: Overlap LLM and TTS stages where possible

## Testing and Verification

### AudioSocket Testing
- **Connection Testing**: Verify TCP server starts and accepts connections
- **Audio Stream Testing**: Test real-time audio processing
- **Provider Integration**: Test audio forwarding to AI providers
- **Error Handling**: Test connection loss and recovery scenarios

### Critical Testing Points
- **AudioSocket Server**: Must start and accept connections on port 8090
- **TCP Connection Management**: Must handle multiple concurrent calls
- **Audio Format Handling**: Must process ulaw audio correctly
- **Provider Integration**: Must forward audio to correct provider
- **File Playback**: Must successfully play generated audio to callers
- **Connection Cleanup**: Must properly close connections on call end

## Troubleshooting Guide

### AudioSocket-Specific Issues

**Connection Refused**:
- Check if AudioSocket server is running on port 8090
- Verify Asterisk dialplan has correct AudioSocket configuration
- Check firewall settings for port 8090

**Audio Not Received**:
- Verify AudioSocket connection is established
- Check audio format compatibility (ulaw)
- Monitor AudioSocket server logs for errors

**Connection Drops**:
- Implement connection retry logic
- Check network stability between Asterisk and container
- Monitor connection pool management

**Performance Issues**:
- Monitor TCP connection overhead
- Check audio buffer management
- Verify provider processing speed

When issues arise:
1. Check AudioSocket server logs for connection status
2. Verify Asterisk dialplan configuration
3. Test TCP connectivity to port 8090
4. Monitor audio stream processing
5. Check provider integration and response times
6. Verify file-based playback functionality
