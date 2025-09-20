# Asterisk AI Voice Agent - Architecture Documentation

## System Overview

The Asterisk AI Voice Agent v3.0 is a **two-container, modular conversational AI system** that enables **real-time, two-way voice conversations** through Asterisk/FreePBX systems. It uses Asterisk's **ExternalMedia** feature with RTP for reliable real-time audio capture and **file-based playback** for robust media handling.

Note: In the current release, downstream audio is delivered via file-based playback for maximum robustness. A full‑duplex streaming TTS path is planned as a next phase and will be gated by feature flags.

## Recent Progress and Current State

- **✅ PRODUCTION READY**: Full two-way conversation system working end-to-end
- **✅ ExternalMedia RTP Integration**: Working perfectly with automatic SSRC mapping
  - Dialplan originates `Local/<uuid_ext>@ai-agent-media-fork/n` for ExternalMedia
  - RTP server receives audio on port 18080 with ulaw codec
  - Automatic SSRC to caller channel mapping on first RTP packet
- **✅ Downstream Playback**: Stable using bridge file playback with TTS gating
- **✅ Complete Pipeline**: RTP → STT → LLM → TTS → Playback working perfectly
- **✅ Fallback Audio Processing**: 2-second fallback intervals providing reliable audio processing
- **✅ TTS Gating System**: Perfect feedback prevention during TTS playback
- **✅ Resource Management**: Complete cleanup and memory management

### Health Endpoint

- A minimal health endpoint is available from the `ai-engine` (default `0.0.0.0:15000/health`). It reports:
  - `ari_connected`: ARI WebSocket/HTTP status
  - `rtp_server_running`: whether the RTP server is active
  - `active_calls`: number of tracked calls
  - `providers`: readiness flags per provider
  - `audio_transport`: current transport mode (externalmedia)
  
Configure via env:
- `HEALTH_HOST` (default `0.0.0.0`), `HEALTH_PORT` (default `15000`).

### Known Constraints

- RTP server requires port 18080 to be available for ExternalMedia integration
- ExternalMedia channels must be properly bridged with caller channels for audio flow
- SSRC mapping is critical for audio routing - first RTP packet automatically maps SSRC to caller
- TTS gating requires proper PlaybackFinished event handling for feedback prevention
- Fallback audio processing uses 2-second intervals for reliable STT processing

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
├── engine.py                    # 🎯 MAIN ORCHESTRATOR
│   ├── _handle_stasis_start()   # Entry point for all calls
│   ├── _create_provider()       # Factory for Deepgram/Local providers
│   ├── on_provider_event()      # Handles AgentAudio events
│   └── _play_ai_audio()         # File-based audio playback
│
├── rtp_server.py               # 🎧 ExternalMedia RTP Server
│   ├── start_server()           # Start TCP server on port 8090
│   ├── handle_connection()      # Handle per-call TCP connections
│   ├── process_audio_stream()   # Real-time audio processing
│   └── forward_to_provider()    # Send audio to AI providers
│
├── providers/
│   ├── base.py                  # AIProviderInterface abstract class
│   ├── deepgram.py              # 🌐 CLOUD PROVIDER
│   │   ├── start_session()      # WebSocket connection to Deepgram
│   │   ├── send_audio()         # Forward ExternalMedia → WebSocket
│   │   ├── _receive_loop()      # WebSocket → AgentAudio events
│   │   └── speak()              # Inject text to Deepgram
│   │
│   └── local.py                 # 🏠 LOCAL PROVIDER
│       ├── start_session()      # Load STT/LLM/TTS models
│       ├── send_audio()         # ExternalMedia → STT processing
│       ├── speak()              # Text → TTS → AgentAudio events
│       └── _synthesize_tts_audio() # TTS synthesis
│
├── ari_client.py                # Asterisk REST Interface client
└── config.py                    # Configuration management
```

## Critical Differences

| **Aspect** | **ExternalMedia Architecture** | **Previous Snoop Architecture** |
|------------|------------------------------|----------------------------------|
| **Audio Input** | TCP stream via ExternalMedia | ARI ChannelAudioFrame events |
| **Reliability** | Guaranteed real-time stream | Unreliable event-based system |
| **Asterisk Config** | Requires dialplan modification | No dialplan changes needed |
| **Connection Type** | Persistent TCP per call | WebSocket event subscription |
| **Audio Format** | Raw ulaw stream | Base64 encoded frames |
| **Error Handling** | Connection-based recovery | Event-based error handling |
| **Performance** | Lower latency, higher throughput | Higher latency, event overhead |

## ExternalMedia Integration

### Call Flow: ExternalMedia Model

The new architecture provides a guaranteed media path by leveraging Asterisk's ExternalMedia feature, treating our application as a pure controller.

1. **Call Initiation**: A new call enters a dialplan context that first calls the `ExternalMedia()` application, then the `Stasis()` application.
2. **Audio Stream Starts**: Asterisk establishes a TCP connection to the `ExternalMediaServer` running inside the `ai-engine` and immediately begins streaming raw audio.
3. **StasisStart**: The `Engine` receives the `StasisStart` event via ARI, determines the provider, and answers the call.
4. **Real-time Conversation**:
   - The `ExternalMediaServer` receives raw audio chunks and forwards them to the active AI provider.
   - The provider processes the audio (STT -> LLM -> TTS).
5. **Media Playback**:
   - The provider sends the synthesized TTS audio back to the `ai-engine`.
   - The `AriClient` writes this audio to a unique file in the shared directory.
   - It sends a `channels.play` command to Asterisk, telling it to play the sound file.
6. **Cleanup**:
   - The `AriClient` listens for the `PlaybackFinished` event from Asterisk.
   - The event handler immediately deletes the audio file from the shared directory.

This model is the most robust and performant, avoiding the unreliable `ChannelAudioFrame` events and the complexity of manual RTP handling.

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

### ExternalMedia Server Pattern
The core of two-way audio functionality is the `ExternalMediaServer` class that manages the TCP connection and audio streaming:

```python
class ExternalMediaServer:
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
- **Connecting**: Establishing ExternalMedia TCP connection
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
- **Audio Latency**: < 200ms (ExternalMedia advantage)
- **End-to-End Response**: < 2 seconds
- **Streaming STT**: Partial results for faster response
- **Parallel Processing**: Overlap LLM and TTS stages where possible

## Testing and Verification

### ExternalMedia Testing
- **Connection Testing**: Verify TCP server starts and accepts connections
- **Audio Stream Testing**: Test real-time audio processing
- **Provider Integration**: Test audio forwarding to AI providers
- **Error Handling**: Test connection loss and recovery scenarios

### Critical Testing Points
- **ExternalMedia Server**: Must start and accept connections on port 8090
- **TCP Connection Management**: Must handle multiple concurrent calls
- **Audio Format Handling**: Must process ulaw audio correctly
- **Provider Integration**: Must forward audio to correct provider
- **File Playback**: Must successfully play generated audio to callers
- **Connection Cleanup**: Must properly close connections on call end

## Troubleshooting Guide

### ExternalMedia-Specific Issues

**Connection Refused**:
- Check if ExternalMedia server is running on port 8090
- Verify Asterisk dialplan has correct ExternalMedia configuration
- Check firewall settings for port 8090

**Audio Not Received**:
- Verify ExternalMedia connection is established
- Check audio format compatibility (ulaw)
- Monitor ExternalMedia server logs for errors

**Connection Drops**:
- Implement connection retry logic
- Check network stability between Asterisk and container
- Monitor connection pool management

**Performance Issues**:
- Monitor TCP connection overhead
- Check audio buffer management
- Verify provider processing speed

When issues arise:
1. Check ExternalMedia server logs for connection status
2. Verify Asterisk dialplan configuration
3. Test TCP connectivity to port 8090
4. Monitor audio stream processing
5. Check provider integration and response times
6. Verify file-based playback functionality
