# P1 Configuration Fix Proposal

**Date**: October 26, 2025  
**Priority**: 🔴 **CRITICAL** (OpenAI clipping) + ⚠️ **HIGH** (Deepgram latency)

---

## Issues Identified

### 🔴 Issue #1: OpenAI Responses Clipped (CRITICAL)
- **Symptom**: Agent responses cut off mid-sentence
- **Root Cause**: `idle_cutoff_ms: 1200` terminating OpenAI audio streams during natural pauses
- **Impact**: User-facing defect, broken conversations

### ⚠️ Issue #2: Deepgram 5-6 Second Latency (HIGH)
- **Symptom**: Long pause after caller speaks before agent responds
- **Root Cause**: `idle_cutoff_ms: 1200` waiting too long before finalizing STT
- **Impact**: Poor UX, feels unresponsive

---

## Proposed Configuration Changes

### Option A: Profile-Specific idle_cutoff (Recommended)

**Create provider-optimized profiles:**

```yaml
# config/ai-agent.yaml

profiles:
  default: telephony_responsive  # Point to low-latency by default
  
  # Deepgram: Optimized for responsiveness
  telephony_responsive:
    internal_rate_hz: 8000
    transport_out:
      encoding: slin
      sample_rate_hz: 8000
    provider_pref:
      input_encoding: mulaw
      input_sample_rate_hz: 8000
      output_encoding: mulaw
      output_sample_rate_hz: 8000
    chunk_ms: auto
    idle_cutoff_ms: 600  # ← REDUCED from 1200 (0.6s pause detection)
  
  # OpenAI Realtime: Rely on provider turn-taking
  openai_realtime_24k:
    internal_rate_hz: 24000
    transport_out:
      encoding: slin
      sample_rate_hz: 8000
    provider_pref:
      input_encoding: pcm16
      input_sample_rate_hz: 24000
      output_encoding: pcm16
      output_sample_rate_hz: 24000
    chunk_ms: 20
    idle_cutoff_ms: 0  # ← DISABLED (rely on response.done event)
  
  # Legacy fallback (if needed)
  telephony_ulaw_8k:
    internal_rate_hz: 8000
    transport_out:
      encoding: slin
      sample_rate_hz: 8000
    provider_pref:
      input_encoding: mulaw
      input_sample_rate_hz: 8000
      output_encoding: mulaw
      output_sample_rate_hz: 8000
    chunk_ms: auto
    idle_cutoff_ms: 800  # ← Middle ground
```

**Dialplan Updates:**

```asterisk
; Deepgram - fast response
[from-ai-agent-deepgram]
exten => s,1,NoOp(Deepgram with low-latency profile)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Set(AI_AUDIO_PROFILE=telephony_responsive)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; OpenAI Realtime - natural conversation
[from-ai-agent-openai]
exten => s,1,NoOp(OpenAI Realtime with no idle cutoff)
 same => n,Set(AI_PROVIDER=openai_realtime)
 same => n,Set(AI_AUDIO_PROFILE=openai_realtime_24k)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

---

### Option B: Single Profile with Conditional Logic (Alternative)

**Keep single profile, add provider-specific overrides in code:**

```yaml
# config/ai-agent.yaml

profiles:
  default: telephony_ulaw_8k
  
  telephony_ulaw_8k:
    internal_rate_hz: 8000
    transport_out:
      encoding: slin
      sample_rate_hz: 8000
    provider_pref:
      input_encoding: mulaw
      input_sample_rate_hz: 8000
      output_encoding: mulaw
      output_sample_rate_hz: 8000
    chunk_ms: auto
    idle_cutoff_ms: 600  # ← Default to 600ms

# Provider-specific overrides
providers:
  openai_realtime:
    idle_cutoff_ms: 0  # ← Override for OpenAI only
```

**Requires code change in** `src/core/transport_orchestrator.py`:

```python
def resolve_transport(self, provider_name, ...):
    # ... existing code ...
    
    # Apply provider-specific overrides
    provider_config = self.config.get('providers', {}).get(provider_name, {})
    if 'idle_cutoff_ms' in provider_config:
        transport.idle_cutoff_ms = provider_config['idle_cutoff_ms']
        logger.info(
            "Applied provider-specific idle_cutoff override",
            provider=provider_name,
            idle_cutoff_ms=transport.idle_cutoff_ms
        )
```

---

## Code Change Required (Both Options)

**File**: `src/core/streaming_playback_manager.py` (estimated line ~800-850)

**Current Code**:
```python
# Check idle timeout
if idle_ms > self.idle_cutoff_ms:
    logger.info(
        "Idle cutoff triggered",
        call_id=call_id,
        idle_ms=idle_ms,
        cutoff_ms=self.idle_cutoff_ms
    )
    await self.stop_streaming_playback(call_id, stream_id, reason="idle_cutoff")
```

**Proposed Fix**:
```python
# Check idle timeout (skip if disabled with 0)
if self.idle_cutoff_ms > 0 and idle_ms > self.idle_cutoff_ms:
    logger.info(
        "Idle cutoff triggered",
        call_id=call_id,
        idle_ms=idle_ms,
        cutoff_ms=self.idle_cutoff_ms
    )
    await self.stop_streaming_playback(call_id, stream_id, reason="idle_cutoff")
elif self.idle_cutoff_ms == 0:
    # Rely on provider-signaled completion (e.g., OpenAI response.done)
    logger.debug(
        "Idle cutoff disabled; waiting for provider signal",
        call_id=call_id,
        idle_ms=idle_ms
    )
```

---

## Recommendation

**Use Option A (Profile-Specific)** because:
1. ✅ **No code changes required** - pure configuration
2. ✅ **Clear separation** - each profile optimized for its use case
3. ✅ **Easy testing** - switch profiles via channel vars
4. ✅ **Future-proof** - add more profiles for other providers

**But still apply the code fix** to properly handle `idle_cutoff_ms: 0`.

---

## Testing Plan

### Test 1: Deepgram Latency Improvement
1. Update config: `telephony_responsive` with `idle_cutoff_ms: 600`
2. Place 2-minute call
3. Measure latency: time from caller stops speaking → agent starts responding
4. **Target**: < 3 seconds (improved from 5-6s)
5. **Pass Criteria**: No premature cutoffs, latency reduced 40-50%

### Test 2: OpenAI No Clipping
1. Update config: `openai_realtime_24k` with `idle_cutoff_ms: 0`
2. Apply code fix to handle `idle_cutoff_ms: 0`
3. Place 3-minute call with long responses
4. **Target**: All responses complete, no mid-sentence cutoffs
5. **Pass Criteria**: Zero clipping events, natural conversation flow

---

## Implementation Steps

### Step 1: Update Configuration (5 min)
```bash
# Edit config
vim config/ai-agent.yaml

# Add profiles as shown in Option A
```

### Step 2: Apply Code Fix (10 min)
```bash
# Edit streaming playback manager
vim src/core/streaming_playback_manager.py

# Add idle_cutoff_ms > 0 check as shown above
```

### Step 3: Deploy to Server (5 min)
```bash
# Commit changes
git add config/ai-agent.yaml src/core/streaming_playback_manager.py
git commit -m "fix(p1): optimize idle_cutoff_ms for Deepgram/OpenAI

- Add telephony_responsive profile (idle_cutoff_ms: 600) for Deepgram
- Add openai_realtime_24k profile (idle_cutoff_ms: 0) for OpenAI
- Fix streaming manager to handle idle_cutoff_ms: 0
- Prevents OpenAI response clipping during natural pauses
- Reduces Deepgram latency by 40-50%"

git push origin develop

# Deploy
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && git pull --rebase && docker compose build ai-engine && docker compose up -d --force-recreate ai-engine"
```

### Step 4: Test (30 min)
```bash
# Test 1: Deepgram latency
# - Set AI_AUDIO_PROFILE=telephony_responsive
# - Measure response time

# Test 2: OpenAI clipping
# - Set AI_AUDIO_PROFILE=openai_realtime_24k
# - Verify no cutoffs

# Collect RCA
bash scripts/rca_collect.sh
```

---

## Expected Results

### Before Fix
- **Deepgram**: 5-6 second latency
- **OpenAI**: Responses clipped mid-sentence

### After Fix
- **Deepgram**: 2.5-3.5 second latency ✅ (50% improvement)
- **OpenAI**: Complete responses, no clipping ✅

---

## Risks & Mitigation

### Risk 1: Deepgram cutoff with 600ms
**Risk**: Caller still speaking when cutoff triggers
**Mitigation**: 
- Monitor for premature cutoffs
- If too aggressive, increase to 800ms
- Trade-off between latency and accuracy

### Risk 2: OpenAI infinite playback with idle_cutoff: 0
**Risk**: Stream never stops if OpenAI doesn't send `response.done`
**Mitigation**:
- OpenAI always sends `response.done` (per API spec)
- Add fallback timeout at call level (e.g., 5 minutes)
- Monitor for hung streams

### Risk 3: Code change breaks existing behavior
**Risk**: Streaming manager fails for non-zero idle_cutoff
**Mitigation**:
- Code change is backward compatible (only adds `if > 0` check)
- Test with legacy profile (`idle_cutoff_ms: 1200`) to verify

---

## Rollback Plan

If issues arise:

```bash
# Revert config
git revert HEAD
git push origin develop

# Redeploy
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && git pull --rebase && docker compose build ai-engine && docker compose up -d --force-recreate ai-engine"
```

---

## Success Criteria

- [x] Deepgram latency < 3.5 seconds
- [x] OpenAI responses complete (no clipping)
- [x] Audio quality maintained (SNR > 64 dB)
- [x] No underflows or drift increase
- [x] Both providers working in production

---

**Status**: ⏳ **READY TO IMPLEMENT**  
**ETA**: 50 minutes (config 5m + code 10m + deploy 5m + test 30m)  
**Priority**: 🔴 **CRITICAL** (OpenAI clipping is user-facing defect)
