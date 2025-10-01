# Local Pipeline Performance Tuning

**Date**: 2025-09-29  
**Server**: voiprnd.nemtclouddispatch.com  
**Hardware**: 39GB RAM, 16 cores (Intel Xeon E5-2660 v3 @ 2.60GHz)

---

## Optimized Configuration Applied

### Target: <30 Second Response Times

The following parameters have been configured to achieve sub-30-second LLM responses with the Llama-2-13B model:

```bash
# Performance-Critical Settings
LOCAL_LLM_INFER_TIMEOUT_SEC=30      # Was: 12s → Now: 30s
LOCAL_LLM_MAX_TOKENS=16             # Was: 32 → Now: 16 (faster generation)
LOCAL_LLM_CONTEXT=512               # Was: 4096 → Now: 512 (faster processing)
LOCAL_LLM_BATCH=512                 # Was: 256 → Now: 512 (better throughput)
LOCAL_LLM_THREADS=16                # Matches CPU cores
LOCAL_LLM_TEMPERATURE=0.1           # Was: 0.2 → More deterministic
LOCAL_LLM_TOP_P=0.75                # Was: 0.85 → More restrictive
LOCAL_LLM_REPEAT_PENALTY=1.02       # Was: 1.05 → Less processing
LOCAL_LLM_USE_MLOCK=1               # Pin model to RAM (prevent swapping)
```

---

## Expected Performance

### With Llama-2-13B (Current)
- **LLM Load Time**: ~90-120 seconds (one-time startup)
- **Per-Token Generation**: ~1-2 seconds
- **Total Response Time**: 16-32 seconds (16 tokens × 1-2s)
- **Quality**: Good conversational responses

### Performance Breakdown
```
User speaks (3s) → STT (1-2s) → LLM (20-25s) → TTS (2-3s) → Total: ~30s
```

---

## Verification Steps

### 1. Check Container Status
```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && docker-compose ps"
```
Both containers should show `Up` and `healthy`.

### 2. Monitor LLM Performance
```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  docker-compose logs -f local-ai-server | grep -E '(LLM|🤖)'"
```

Look for:
- `✅ LLM model loaded` - Confirms startup
- `🤖 LLM RESULT` - Successful generation
- `🤖 LLM STARTUP LATENCY` - Track timing

### 3. Test Call
1. Place a test call to your AI agent
2. After greeting, say: **"What is your name?"** (short query)
3. Wait for response (should come within 30 seconds)
4. Check logs:
```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  docker-compose logs ai-engine | grep -E '(LLM|generate)' | tail -20"
```

---

## Troubleshooting

### If Still Timing Out (>30s)

#### Option A: Further reduce tokens
```bash
# Edit on server: /root/Asterisk-AI-Voice-Agent/.env
LOCAL_LLM_MAX_TOKENS=8              # Minimal response (8-16s)
LOCAL_LLM_CONTEXT=256               # Even faster processing

# Restart
docker-compose restart local-ai-server
```

#### Option B: Switch to TinyLlama (LIGHT tier)
```bash
# On server
cd /root/Asterisk-AI-Voice-Agent

# Download smaller model (~570MB vs 7.3GB)
wget -O models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
  https://huggingface.co/jartine/tinyllama-1.1b-chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf

# Update .env
echo "LOCAL_LLM_MODEL_PATH=/app/models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" >> .env

# Restart
docker-compose restart local-ai-server
```

**TinyLlama Expected Performance**:
- Load time: 10-20 seconds
- Response time: 5-10 seconds
- Quality: Basic but functional

#### Option C: Use Hybrid Pipeline (Recommended)
Keep local STT for privacy, use cloud for speed:

```bash
# Edit config/ai-agent.yaml
active_pipeline: "hybrid_support"  # local STT + OpenAI LLM + Deepgram TTS
```

**Hybrid Performance**:
- STT: Local (privacy preserved)
- LLM: <1 second (GPT-4o-mini)
- TTS: 1-2 seconds (Deepgram Aura)
- Total: <5 seconds end-to-end

---

## Performance Monitoring

### Real-time Latency Tracking
```bash
# Watch LLM timing
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  docker-compose logs -f local-ai-server | grep 'LATENCY'"
```

### Check Memory Usage
```bash
ssh root@voiprnd.nemtclouddispatch.com "docker stats local_ai_server --no-stream"
```

Should show:
- **MEM USAGE**: ~10-12GB (Llama-2-13B) or ~2-3GB (TinyLlama)
- **MEM %**: <35% with 39GB total RAM

---

## Configuration Files Modified

| File | Changes |
|------|---------|
| `/root/Asterisk-AI-Voice-Agent/.env` | Added optimized LLM parameters |
| `docker-compose.yml` | Already had configurable env vars |
| `config/ai-agent.yaml` | Already set to `local_only` pipeline |

**Backup created**: `.env.backup-20250929-HHMMSS`

---

## Next Steps

1. **Test the pipeline** with a short call
2. **Monitor logs** for `LLM generate` timing
3. **Adjust MAX_TOKENS** if needed (8-32 range)
4. **Consider hybrid** if pure local is too slow for production

---

## Quick Reference

### Restart Services
```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  docker-compose restart local-ai-server ai-engine"
```

### View Live Logs
```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  docker-compose logs -f --tail=100"
```

### Check Health
```bash
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && \
  curl -s http://localhost:15000/health | jq"
```

---

## Summary

✅ **Configuration Applied**: Optimized for <30s responses  
✅ **Services Restarted**: local-ai-server running with new settings  
✅ **Model Loaded**: Llama-2-13B loaded successfully  
⏳ **Next**: Place test call to verify functional pipeline  

**Estimated Response Time**: 20-30 seconds per turn with current settings.
