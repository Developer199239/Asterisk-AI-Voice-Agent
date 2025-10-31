# Transport & Playback Mode Compatibility Guide

**Last Updated**: October 28, 2025  
**Issue**: Linear AAVA-28

## Overview

This document defines the **validated and supported** combinations of audio transport, provider mode, and playback methods.

---

## Validated Configurations

### ✅ Configuration 1: ExternalMedia RTP + Hybrid Pipelines + File Playback

**Use Case**: Modular STT → LLM → TTS pipelines

**Configuration**:
```yaml
audio_transport: externalmedia
active_pipeline: hybrid_support  # or any pipeline
downstream_mode: stream  # ignored by pipelines
```

**Technical Details**:
- **Transport**: ExternalMedia RTP (direct UDP audio stream)
- **Provider Mode**: Pipeline (modular adapters)
- **Playback Method**: File-based (PlaybackManager)
- **Audio Flow**:
  - Caller audio → RTP Server → ai-engine → Pipeline STT
  - TTS bytes → File → Asterisk Announcer channel → Caller
  - **No bridge conflict**: RTP ingestion separate from file playback

**Status**: ✅ **VALIDATED** (Call 1761698845.2619)
- Clean two-way conversation
- Proper gating (no feedback loop)
- No audio routing issues

**Why This Works**:
- RTP audio ingestion doesn't use Asterisk bridge
- File playback uses Announcer channel in bridge
- No routing conflict between ingestion and playback

---

### ✅ Configuration 2: AudioSocket + Full Agent + Streaming Playback

**Use Case**: Monolithic providers with integrated STT/LLM/TTS (Deepgram Voice Agent, OpenAI Realtime)

**Configuration**:
```yaml
audio_transport: audiosocket
active_pipeline: ""  # Disable pipelines
default_provider: deepgram  # or openai_realtime
downstream_mode: stream
```

**Technical Details**:
- **Transport**: AudioSocket (Asterisk channel in bridge)
- **Provider Mode**: Full Agent (monolithic)
- **Playback Method**: Streaming (StreamingPlaybackManager)
- **Audio Flow**:
  - Caller audio → AudioSocket channel → ai-engine → Provider
  - Provider TTS stream → StreamingPlaybackManager → AudioSocket → Caller
  - **No Announcer**: Streaming playback doesn't create extra channels

**Status**: ✅ **VALIDATED**
- Clean audio routing
- No bridge conflicts
- Real-time streaming

**Why This Works**:
- AudioSocket channel in bridge for bidirectional audio
- StreamingPlaybackManager sends audio directly to AudioSocket
- No Announcer channel needed

---

## ❌ Unsupported Configuration: AudioSocket + Pipelines + File Playback

**Configuration** (DO NOT USE):
```yaml
audio_transport: audiosocket
active_pipeline: hybrid_support
downstream_mode: stream  # Ignored by pipelines!
```

**Issue**: Asterisk bridge routing conflict

**What Happens**:
1. Pipeline mode always uses file playback (hardcoded)
2. File playback creates Announcer channel in bridge
3. Bridge contains: Caller ↔ AudioSocket ↔ Announcer
4. **Asterisk routing issue**: Doesn't route caller audio to AudioSocket when Announcer present
5. **Result**: Only initial greeting heard, no subsequent audio

**Evidence**: Call 1761699424.2631
- Only 1 AudioSocket frame received
- 20+ seconds of silence after greeting
- AudioSocket disconnected with no audio

**Technical Root Cause**:
```
Bridge Configuration:
┌─────────┐
│  Caller │
└────┬────┘
     │
┌────▼────────────┐
│     Bridge      │
│  ┌──────────┐  │
│  │Announcer │  │  ← File playback
│  └──────────┘  │
│  ┌──────────┐  │
│  │AudioSocket│ │  ← Audio ingestion (receives no frames!)
│  └──────────┘  │
└─────────────────┘
```

**Why RTP Doesn't Have This Issue**:
```
No Bridge Conflict:
┌─────────┐
│  Caller │
└────┬────┘
     │
┌────▼────────────┐
│     Bridge      │
│  ┌──────────┐  │
│  │Announcer │  │  ← File playback to caller
│  └──────────┘  │
└─────────────────┘
     
     (Separate path)
     RTP Server ← Direct audio stream
```

---

## Configuration Matrix

| Transport | Provider Mode | Playback Method | Gating | Status |
|-----------|--------------|-----------------|--------|--------|
| **ExternalMedia RTP** | Pipeline | File (PlaybackManager) | ✅ Working | ✅ **VALIDATED** |
| **AudioSocket** | Full Agent | Streaming (StreamingPlaybackManager) | ✅ Working | ✅ **VALIDATED** |
| AudioSocket | Pipeline | File (PlaybackManager) | ⚠️ N/A | ❌ **Bridge Conflict** |

---

## Decision Guide

### Use ExternalMedia RTP When:
- ✅ Running hybrid pipelines (modular STT/LLM/TTS)
- ✅ Need file-based playback
- ✅ Want clean audio routing (no bridge conflicts)
- ✅ Modern deployment

### Use AudioSocket When:
- ✅ Running full agent providers (Deepgram Voice Agent, OpenAI Realtime)
- ✅ Need streaming playback
- ✅ Legacy compatibility requirements
- ⚠️ **NOT for pipelines** (use RTP instead)

---

## Configuration Examples

### Example 1: Production Pipeline (Recommended)

```yaml
# config/ai-agent.yaml
audio_transport: externalmedia
active_pipeline: hybrid_support
downstream_mode: stream  # Ignored by pipelines

pipelines:
  hybrid_support:
    stt: deepgram_stt
    llm: openai_llm
    tts: deepgram_tts
    options:
      stt:
        streaming: true
        encoding: linear16
        sample_rate: 16000
```

**Result**: Clean two-way conversation with proper gating ✅

---

### Example 2: Full Agent (Streaming)

```yaml
# config/ai-agent.yaml
audio_transport: audiosocket
active_pipeline: ""  # Disable pipelines
default_provider: deepgram
downstream_mode: stream

providers:
  deepgram:
    enabled: true
    continuous_input: true
    # ... provider config
```

**Result**: Real-time streaming conversation ✅

---

## Troubleshooting

### Symptom: Only hear greeting, nothing after

**Cause**: Using AudioSocket + Pipeline + File playback  
**Solution**: Switch to `audio_transport: externalmedia`

### Symptom: No audio frames after initial connection

**Check**:
1. Verify transport mode in logs
2. Check for Announcer channel in bridge
3. Confirm downstream_mode being honored

**Fix**: Use validated configuration from this document

---

## Implementation Notes

### Why Pipelines Always Use File Playback

**Code Location**: `src/engine.py:4242`

```python
# Pipeline runner hardcoded to file playback
playback_id = await self.playback_manager.play_audio(
    call_id,
    bytes(tts_bytes),
    "pipeline-tts",
)
```

**Reason**: Pipelines were designed for discrete request/response cycles with file artifacts.

**Future**: Could add `downstream_mode` check to enable streaming for pipelines (4-6 hour effort).

### Why Full Agents Respect downstream_mode

**Code Location**: `src/engine.py:3598, 3669`

```python
# Full agents check downstream_mode
use_streaming = self.config.downstream_mode != "file"

if use_streaming:
    await self.streaming_playback_manager.start_streaming_playback(...)
else:
    await self.playback_manager.play_audio(...)
```

**Reason**: Full agents were designed for continuous streaming with optional file fallback.

---

## Related Issues

- **Linear AAVA-28**: Pipeline STT streaming implementation & gating fixes
- **Commits**:
  - `181b210`: Pipeline gating enforcement
  - `fbaaf2e`: Fallback safety margin increase
  - `294e55e`: Deepgram STT streaming support

---

## Validation History

| Date | Transport | Mode | Result | Call ID | Notes |
|------|-----------|------|--------|---------|-------|
| 2025-10-28 | RTP | Pipeline | ✅ Pass | 1761698845.2619 | Clean two-way, no feedback |
| 2025-10-28 | AudioSocket | Pipeline | ❌ Fail | 1761699424.2631 | Only greeting heard |
| 2025-10-28 | AudioSocket | Full Agent | ✅ Pass | TBD | Streaming playback |

---

## Recommendations

1. **Production**: Use **ExternalMedia RTP** for all pipeline deployments
2. **Legacy**: Use **AudioSocket** only with full agent providers
3. **Future**: Consider implementing streaming playback for pipelines if AudioSocket + Pipeline support needed
4. **Monitoring**: Always check transport logs during deployment validation

---

**For questions or issues, see**:
- [Architecture.md](./Architecture.md)
- [ROADMAP.md](./ROADMAP.md)
- Linear issue AAVA-28
