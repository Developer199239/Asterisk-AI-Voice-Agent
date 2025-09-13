# Asterisk AI Voice Agent - Architecture Documentation

## System Overview

The Asterisk AI Voice Agent v3.0 is a single-container, multi-provider architecture that supports both cloud-based (Deepgram) and local AI models for real-time voice conversations.

## Architecture Diagrams

### 1. DEEPGRAM PROVIDER CALL FLOW 🌐

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ASTERISK      │    │   AI AGENT      │    │   DEEPGRAM      │    │   OPENAI        │
│   (PJSIP/SIP)   │    │   ENGINE        │    │   CLOUD         │    │   CLOUD         │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │                       │
         │ 1. Incoming Call     │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 2. StasisStart Event │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │                       │ 3. Create DeepgramProvider                    │
         │                       ├──────────────────────►│                       │
         │                       │                       │                       │
         │                       │ 4. WebSocket Connect  │                       │
         │                       ├──────────────────────►│                       │
         │                       │                       │                       │
         │ 5. Answer Channel     │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 6. Create Snoop Channel                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 7. Audio Frame Events │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │                       │ 8. Forward to Deepgram                       │
         │                       ├──────────────────────►│                       │
         │                       │                       │                       │
         │                       │                       │ 9. STT + LLM + TTS   │
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

### 2. LOCAL PROVIDER CALL FLOW 🏠

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ASTERISK      │    │   AI AGENT      │    │   LOCAL AI      │    │   SHARED MEDIA  │
│   (PJSIP/SIP)   │    │   ENGINE        │    │   SERVER        │    │   DIRECTORY     │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │                       │
         │ 1. Incoming Call     │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │ 2. StasisStart Event │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │                       │ 3. Create LocalProvider                       │
         │                       ├──────────────────────►│                       │
         │                       │                       │                       │
         │                       │ 4. Connect to Local AI Server                 │
         │                       ├──────────────────────►│                       │
         │                       │                       │                       │
         │ 5. Answer Channel     │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 6. Create Snoop Channel                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 7. Audio Frame Events │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
         │                       │ 8. Forward Audio to Local AI Server           │
         │                       ├──────────────────────►│                       │
         │                       │                       │                       │
         │                       │                       │ 9. STT Processing    │
         │                       │                       ├──────────────────────►│
         │                       │                       │                       │
         │                       │                       │ 10. LLM Processing   │
         │                       │                       ├──────────────────────►│
         │                       │                       │                       │
         │                       │                       │ 11. TTS Synthesis    │
         │                       │                       ├──────────────────────►│
         │                       │                       │                       │
         │                       │ 12. Audio Response    │                       │
         │                       │◄──────────────────────┤                       │
         │                       │                       │                       │
         │ 13. Save Audio File   │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 14. Play Audio File   │                       │                       │
         │◄──────────────────────┤                       │                       │
         │                       │                       │                       │
         │ 15. Call Complete     │                       │                       │
         ├──────────────────────►│                       │                       │
         │                       │                       │                       │
```

### 3. RING MECHANISM FLOW 🔔

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   ASTERISK      │    │   AI AGENT      │    │   LOCAL MODELS  │
│   (PJSIP/SIP)   │    │   ENGINE        │    │   (Loading)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │ 1. Incoming Call     │                       │
         ├──────────────────────►│                       │
         │                       │                       │
         │ 2. StasisStart Event │                       │
         ├──────────────────────►│                       │
         │                       │                       │
         │ 3. Answer Immediately│                       │
         │◄──────────────────────┤                       │
         │                       │                       │
         │ 4. Start Ring Tone   │                       │
         │◄──────────────────────┤                       │
         │                       │                       │
         │ 5. Load Models (Background)                   │
         │                       ├──────────────────────►│
         │                       │                       │
         │ 6. Ring Continues... │                       │
         │◄──────────────────────┤                       │
         │                       │                       │
         │ 7. Models Ready       │                       │
         │                       │◄──────────────────────┤
         │                       │                       │
         │ 8. Stop Ring          │                       │
         │◄──────────────────────┤                       │
         │                       │                       │
         │ 9. Play Greeting      │                       │
         │◄──────────────────────┤                       │
         │                       │                       │
```

## Key File Architecture

```
src/
├── engine.py                    # 🎯 MAIN ORCHESTRATOR
│   ├── _handle_stasis_start()   # Entry point for all calls
│   ├── _create_provider()       # Factory for Deepgram/Local providers
│   ├── on_provider_event()      # ⚠️ CRITICAL: Handles AgentAudio events
│   ├── _play_ring_tone()        # 🔔 NEW: Ring mechanism
│   └── _play_ai_audio()         # Legacy method (unused)
│
├── providers/
│   ├── base.py                  # AIProviderInterface abstract class
│   ├── deepgram.py              # 🌐 CLOUD PROVIDER
│   │   ├── start_session()      # WebSocket connection to Deepgram
│   │   ├── send_audio()         # Forward RTP → WebSocket
│   │   ├── _receive_loop()      # WebSocket → AgentAudio events
│   │   └── speak()              # Inject text to Deepgram
│   │
│   └── local.py                 # 🏠 LOCAL PROVIDER
│       ├── start_session()      # Load STT/LLM/TTS models
│       ├── send_audio()         # RTP → STT processing
│       ├── speak()              # Text → TTS → AgentAudio events
│       └── _synthesize_tts_audio() # TTS synthesis
│
├── ari_client.py                # Asterisk REST Interface client with Snoop/Playback
└── config.py                    # Configuration management
```

## Critical Differences

| **Aspect** | **Deepgram Provider** | **Local Provider** |
|------------|----------------------|-------------------|
| **Audio Direction** | Bidirectional WebSocket | WebSocket to Local AI Server |
| **STT Processing** | Cloud-based | Local Vosk model |
| **LLM Processing** | Cloud OpenAI | Local Llama model |
| **TTS Processing** | Cloud Deepgram | Local LightweightTTS (espeak-ng) |
| **Audio Format** | Pre-packetized from cloud | Raw ulaw → WAV conversion |
| **Event Flow** | WebSocket → on_event() | WebSocket → STT/LLM/TTS → on_event() |
| **Dependencies** | Internet + API keys | Local model files |
| **Loading Time** | ~1-2 seconds | ~5-10 seconds |
| **Ring Mechanism** | Not needed | Required for UX |

## Ring Mechanism Implementation

The ring mechanism addresses the delay in local model loading by:

1. **Immediate Answer**: Answer the call immediately to prevent timeout
2. **Ring Tone**: Play a standard ring tone while models load in background
3. **Model Loading**: Load STT/LLM/TTS models asynchronously
4. **Seamless Transition**: Stop ring and play greeting when models are ready
5. **Provider Detection**: Only apply to Local provider, skip for Deepgram

## Unified Provider Interface

Both providers implement the same interface:
```python
class AIProviderInterface:
    async def start_session()     # Initialize provider
    async def send_audio()        # Process incoming audio
    async def speak()             # Generate outgoing audio
    async def stop_session()      # Cleanup resources
    async def is_ready()          # Check if provider is ready
```

The beauty of this architecture: The engine doesn't need to know whether it's talking to Deepgram or Local - it just calls the same methods and handles the same `AgentAudio` events!
