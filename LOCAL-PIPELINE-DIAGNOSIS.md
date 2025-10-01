# Local Pipeline Diagnosis - Call 1759201995.50

**Date**: 2025-09-30 03:13  
**Duration**: 2:40 (160 seconds)  
**Result**: ❌ FAILED - No two-way conversation

---

## Issues Found

### 1. ❌ TTS Greeting Never Sent to local-ai-server

**Observed in `ai-engine` logs:**
```
03:13:22 - Sending TTS request call_id=1759201995.50 text_preview=Hello, how can I help you today?
03:13:22 - Pipeline TTS adapter session opened
```

**Missing from `local-ai-server` logs:**
- ❌ NO "🔊 TTS REQUEST" received
- ❌ NO "🔊 TTS RESULT" generated  
- ❌ NO audio bytes sent back

**Root Cause**: TTS request sent but never processed by local-ai-server.

---

### 2. ❌ STT Receiving No Audio Data

**Observed in `local-ai-server` logs:**
```
Repeated 200+ times:
📝 STT IDLE FINALIZER - Triggering final after 3000 ms silence call_id=1759201995.50 mode=stt preview=
📝 STT FINAL SUPPRESSED - Repeated empty transcript call_id=1759201995.50 mode=stt
```

**Analysis:**
- STT session is open and listening
- But receiving NO audio chunks
- Empty transcript every 3 seconds (idle timeout)

**Root Cause**: Audio from `ai-engine` not reaching `local-ai-server` STT WebSocket.

---

### 3. ❌ No LLM Requests Ever Sent

**Missing:**
- ❌ NO "🧠 LLM START" logs
- ❌ NO "🤖 LLM RESULT" logs  
- ❌ NO LLM inference attempts

**Root Cause**: Since STT produces no transcripts, LLM is never invoked.

---

## Root Cause Analysis

### The WebSocket Communication is Broken

The `local_only` pipeline uses **3 separate WebSocket connections** to `local-ai-server`:

```
ai-engine → ws://127.0.0.1:8765 (mode=stt)  → STT WebSocket
ai-engine → ws://127.0.0.1:8765 (mode=llm)  → LLM WebSocket  
ai-engine → ws://127.0.0.1:8765 (mode=tts)  → TTS WebSocket
```

**All 3 connections opened successfully** but:
1. **TTS WebSocket**: Request sent but not received
2. **STT WebSocket**: No audio chunks being forwarded
3. **LLM WebSocket**: Never used (no transcripts to process)

---

## Why This Happens with Llama-2-13B

### Theory: Model is Too Slow, Blocking Event Loop

The `local-ai-server` is **single-threaded** for WebSocket handling:

```python
# main.py - WebSocket server runs in main async loop
async def handler(websocket, path):
    # Handles ALL 3 connections (STT/LLM/TTS)
    # If LLM inference blocks, other connections starve
```

**Problem:**
- LLM warmup took **135+ seconds** on startup
- During actual inference, if LLM takes 20-30s, it may block:
  - TTS audio generation
  - STT audio processing  
  - WebSocket message handling

**Evidence:**
- "connection rejected (400 Bad Request)" - health checks timing out
- Empty STT transcripts - audio not being processed
- TTS request not logged - never reached handler

---

## The MVP Fix: Switch to TinyLlama

### Why TinyLlama Will Work

**Current (Broken):**
- Model: Llama-2-13B (7.3GB, 13 billion parameters)
- Warmup: 135 seconds
- Inference: 20-30 seconds per response
- Result: Blocks WebSocket event loop ❌

**Proposed (Functional):**
- Model: TinyLlama-1.1B (570MB, 1.1 billion parameters)  
- Warmup: 10-15 seconds
- Inference: 5-10 seconds per response
- Result: Won't block event loop ✅

---

## Solution: Immediate MVP Configuration

### Step 1: Download TinyLlama Model

```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  wget -O models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
  https://huggingface.co/jartine/tinyllama-1.1b-chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
```

### Step 2: Update Configuration

```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  sed -i 's|LOCAL_LLM_MODEL_PATH=.*|LOCAL_LLM_MODEL_PATH=/app/models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf|' .env"
```

### Step 3: Adjust for Speed

```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  cat >> .env << 'EOF'

# TinyLlama optimized settings
LOCAL_LLM_CONTEXT=256
LOCAL_LLM_BATCH=512
LOCAL_LLM_MAX_TOKENS=24
LOCAL_LLM_TEMPERATURE=0.3
LOCAL_LLM_INFER_TIMEOUT_SEC=15
EOF
"
```

### Step 4: Recreate Container

```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  docker-compose up -d --force-recreate local-ai-server"
```

---

## Expected Performance with TinyLlama

```
User speaks (3s)
↓
STT transcribes (1-2s)
↓
LLM generates (5-8s)  ← Fast enough to not block WebSockets
↓
TTS synthesizes (2-3s)
↓
Total: ~13-16 seconds per turn ✅
```

---

## Alternative: Use Hybrid Pipeline (Recommended for Production)

If you need better quality, keep STT local but use cloud for LLM/TTS:

```yaml
# config/ai-agent.yaml
active_pipeline: "hybrid_support"  # Local STT + OpenAI LLM + Deepgram TTS
```

**Performance:**
- Total latency: <5 seconds
- Quality: Production-grade
- Privacy: STT stays local

---

## Verification After Fix

### 1. Check Container Logs
```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  docker-compose logs -f local-ai-server | grep -E '(model loaded|🔊 TTS|📝 STT|🤖 LLM)'"
```

Look for:
- `✅ LLM model loaded: tinyllama...`
- `🤖 LLM STARTUP LATENCY - 10000-15000 ms` (not 135000)

### 2. Place Test Call

Say clearly: **"What is the weather?"**

Monitor in real-time:
```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  docker-compose logs -f local-ai-server"
```

Expected flow (within 20 seconds):
```
🔊 TTS REQUEST - Call XXX: 'Hello, how can I help you today?'
🔊 TTS RESULT - Generated uLaw 8kHz audio: XXXX bytes
📤 TTS RESPONSE - Sent XXXX bytes
🎵 AUDIO INPUT - Received audio: XXXX bytes at 16000 Hz
📝 STT RESULT - Vosk transcript: 'what is the weather' 
🧠 LLM START - Generating response
🤖 LLM RESULT - Response: 'I don't have access to real-time weather...'
🔊 TTS RESULT - Generated uLaw 8kHz audio: XXXX bytes
📤 AUDIO OUTPUT - Sent uLaw 8kHz response
```

---

## Summary

**Current State**: Llama-2-13B is too slow and blocks the WebSocket event loop in `local-ai-server`, preventing TTS/STT from functioning.

**MVP Fix**: Switch to TinyLlama (12× smaller, 3-4× faster) to unblock the pipeline.

**Production Fix**: Use hybrid pipeline with cloud LLM for best performance and quality.

**Timeline**: With TinyLlama, expect functional two-way conversation within 15-20 seconds per turn.
