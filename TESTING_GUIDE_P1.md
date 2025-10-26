# P1 Testing Guide - Multi-Provider Transport Orchestration

**Status**: Ready for validation testing  
**Date**: October 26, 2025  
**Estimated Time**: ~30 minutes total

---

## Pre-Testing Checklist

- [ ] Code pushed to `develop` branch
- [ ] Server pulled latest code: `cd /root/Asterisk-AI-Voice-Agent && git pull --rebase`
- [ ] Engine rebuilt: `docker compose build ai-engine`
- [ ] Engine restarted: `docker compose up -d --force-recreate ai-engine`
- [ ] Health check passed: `docker ps | grep ai_engine` shows "Up"

---

## Test 1: Deepgram Golden Baseline Validation ⭐

**Goal**: Verify P1 doesn't regress P0 golden baseline  
**Duration**: ~10 minutes  
**Priority**: CRITICAL

### Setup

Server dialplan (`/etc/asterisk/extensions_custom.conf`):
```asterisk
[from-ai-agent-deepgram]
exten => s,1,NoOp(P1 Test: Deepgram via Transport Orchestrator)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Set(AI_AUDIO_PROFILE=telephony_ulaw_8k)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### Execution

1. **Place test call** (60 seconds, engage in natural conversation)
2. **Collect RCA**:
   ```bash
   # From local machine
   bash scripts/rca_collect.sh
   ```

3. **Check logs**:
   ```bash
   docker logs ai_engine --since 5m | grep -E "TransportOrchestrator|Resolved audio profile|Negotiated transport"
   ```

### Expected Results

**Logs should show**:
```
TransportOrchestrator initialized profiles=['telephony_ulaw_8k']
Resolved audio profile for call profile='telephony_ulaw_8k' provider='deepgram'
Negotiated transport profile wire_encoding='slin' provider_input='mulaw@8000'
Parsed Deepgram SettingsApplied ACK input_encoding='mulaw' output_encoding='mulaw'
```

**Metrics (compare to P0 golden baseline)**:
- ✅ **Underflows**: 0 (acceptable: 0-2)
- ✅ **Drift**: ≈ 0% (acceptable: -10% to +10%)
- ✅ **Provider bytes ratio**: ≈ 1.0 (acceptable: 0.95-1.05)
- ✅ **SNR**: > 64 dB (acceptable: > 60 dB)
- ✅ **Audio quality**: Subjectively clean, no garble

### Pass/Fail Criteria

**PASS** if:
- All metrics within acceptable range
- No underflow spike
- Audio sounds clean
- Logs show orchestrator initialization

**FAIL** if:
- Underflows > 10
- Drift < -20% or > +20%
- SNR < 55 dB
- Audio garbled/distorted
- Orchestrator not initialized

---

## Test 2: OpenAI Realtime Golden Baseline Validation ⭐

**Goal**: Verify P1 works with OpenAI Realtime provider  
**Duration**: ~10 minutes  
**Priority**: HIGH

### Setup

Server dialplan:
```asterisk
[from-ai-agent-openai]
exten => s,1,NoOp(P1 Test: OpenAI Realtime via Transport Orchestrator)
 same => n,Set(AI_PROVIDER=openai_realtime)
 same => n,Set(AI_AUDIO_PROFILE=telephony_ulaw_8k)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### Execution

1. **Place test call** (45-60 seconds, natural conversation with interruptions)
2. **Collect RCA**: `bash scripts/rca_collect.sh`
3. **Check logs** for orchestrator + OpenAI session.updated ACK

### Expected Results

**Logs should show**:
```
Resolved audio profile for call profile='telephony_ulaw_8k' provider='openai_realtime'
Parsed OpenAI session.updated ACK input_format='pcm16' sample_rate=24000
Applied wire format to provider target config target_encoding='slin' target_sample_rate_hz=8000
```

**Metrics (compare to P0.5 golden baseline)**:
- ✅ **SNR**: > 64 dB
- ✅ **Gate closures**: ≤ 1 per call
- ✅ **VAD buffered chunks**: 0 (with webrtc_aggressiveness: 1)
- ✅ **Self-interruption**: None
- ✅ **Conversation flow**: Natural, no echo loops

### Pass/Fail Criteria

**PASS** if:
- SNR > 60 dB
- Gate closures ≤ 3
- No self-interruption observed
- Natural conversation flow

**FAIL** if:
- Gate fluttering (> 10 closures)
- Agent hears own audio (self-interruption)
- Echo detected
- Poor audio quality

---

## Test 3: Context Mapping Verification 🔧

**Goal**: Verify AI_CONTEXT maps to profile + provider + prompt  
**Duration**: ~5 minutes  
**Priority**: MEDIUM

### Setup

Config (`config/ai-agent.yaml`):
```yaml
contexts:
  sales:
    prompt: "You are an enthusiastic sales assistant."
    greeting: "Thanks for calling sales!"
    profile: telephony_ulaw_8k
    provider: deepgram
  support:
    prompt: "You are concise technical support."
    greeting: "Support line, how can we help?"
    profile: telephony_ulaw_8k
    provider: openai_realtime
```

Dialplan:
```asterisk
[from-ai-agent-sales]
exten => s,1,NoOp(P1 Test: Context Mapping - Sales)
 same => n,Set(AI_CONTEXT=sales)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### Execution

1. Place call to sales context
2. Verify greeting: "Thanks for calling sales!"
3. Check logs for context resolution

### Expected Results

**Logs**:
```
Resolved audio profile for call profile='telephony_ulaw_8k' context='sales' provider='deepgram'
```

**Behavior**:
- Greeting matches context: "Thanks for calling sales!"
- Provider is Deepgram (as specified in context)

### Pass/Fail Criteria

**PASS**: Correct greeting + provider  
**FAIL**: Wrong greeting or provider

---

## Test 4: Profile Override Verification 🔧

**Goal**: Verify AI_AUDIO_PROFILE overrides context/default  
**Duration**: ~5 minutes  
**Priority**: MEDIUM

### Setup

Config:
```yaml
profiles:
  default: telephony_ulaw_8k
  wideband_pcm_16k:
    internal_rate_hz: 16000
    transport_out:
      encoding: slin16
      sample_rate_hz: 16000
    provider_pref:
      input_encoding: linear16
      input_sample_rate_hz: 16000
      output_encoding: linear16
      output_sample_rate_hz: 16000
    chunk_ms: auto
    idle_cutoff_ms: 1200
```

Dialplan:
```asterisk
[from-ai-agent-wideband]
exten => s,1,NoOp(P1 Test: Profile Override)
 same => n,Set(AI_AUDIO_PROFILE=wideband_pcm_16k)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

**NOTE**: Asterisk dialplan must also use `c(slin16)` for 16kHz:
```asterisk
Dial(AudioSocket/127.0.0.1:8090/${uuid}/c(slin16))
```

### Execution

1. Place call with profile override
2. Check logs for profile selection
3. Verify wire format is `slin16` @ 16kHz

### Expected Results

**Logs**:
```
Resolved audio profile for call profile='wideband_pcm_16k' provider='deepgram'
Negotiated transport profile wire_encoding='slin16' wire_sample_rate=16000
```

### Pass/Fail Criteria

**PASS**: Logs show `wideband_pcm_16k` selected  
**FAIL**: Default profile used instead

---

## Test 5: Legacy Config Compatibility (Optional) 🔧

**Goal**: Verify backward compatibility when profiles block is missing  
**Duration**: ~5 minutes  
**Priority**: LOW

### Setup

Temporarily remove `profiles:` block from `config/ai-agent.yaml`

### Execution

1. Restart engine
2. Check logs for legacy synthesis message
3. Place normal call

### Expected Results

**Logs**:
```
No audio profiles found in config; synthesizing legacy profile default='telephony_ulaw_8k'
Synthesized legacy profile from config profile=AudioProfile(...) suggestion='Add profiles.* block...'
```

**Behavior**:
- Call works normally
- Uses synthesized profile from legacy config

### Pass/Fail Criteria

**PASS**: Call works with legacy config  
**FAIL**: Engine crashes or refuses to start

---

## Results Summary Template

```markdown
# P1 Testing Results - [Date]

## Test 1: Deepgram Golden Baseline
- Status: PASS / FAIL
- Underflows: [value]
- Drift: [value]%
- SNR: [value] dB
- Notes: [any observations]

## Test 2: OpenAI Realtime Golden Baseline
- Status: PASS / FAIL
- SNR: [value] dB
- Gate closures: [value]
- Self-interruption: YES / NO
- Notes: [any observations]

## Test 3: Context Mapping
- Status: PASS / FAIL
- Greeting correct: YES / NO
- Provider correct: YES / NO
- Notes: [any observations]

## Test 4: Profile Override
- Status: PASS / FAIL
- Profile selected: [value]
- Wire encoding: [value]
- Notes: [any observations]

## Test 5: Legacy Compatibility
- Status: PASS / FAIL / SKIPPED
- Synthesis message: YES / NO
- Call worked: YES / NO
- Notes: [any observations]

## Overall P1 Status
- [ ] READY FOR PRODUCTION (all critical tests pass)
- [ ] NEEDS FIXES (list issues below)

### Issues Found:
1. [issue description]
2. [issue description]

### Next Actions:
- [ ] Fix issues
- [ ] Re-test failed scenarios
- [ ] Update documentation
- [ ] Deploy to production
```

---

## Troubleshooting Guide

### Issue: Orchestrator not initialized

**Symptoms**: No "TransportOrchestrator initialized" log

**Check**:
```bash
docker logs ai_engine --since 2m | grep TransportOrchestrator
```

**Fix**: Verify `src/engine.py` line 306 instantiates orchestrator

---

### Issue: Profile not found

**Symptoms**: "Audio profile 'X' not found" error

**Check**: Profile exists in `config/ai-agent.yaml` under `profiles:`

**Fix**: Add profile or use existing profile name

---

### Issue: Provider format mismatch

**Symptoms**: Remediation warning in logs

**Check**:
```bash
docker logs ai_engine | grep "Provider may not support"
```

**Fix**: Update profile `provider_pref` to match provider capabilities

---

### Issue: AudioSocket format mismatch

**Symptoms**: Garbled audio, frame size errors

**Check**: `audiosocket.format` in YAML matches dialplan `c(...)` parameter

**Fix**: 
- YAML `format: slin` → dialplan `c(slin)`
- YAML `format: slin16` → dialplan `c(slin16)`

---

## Quick Commands Reference

```bash
# Check engine status
docker ps | grep ai_engine

# Watch live logs
docker logs -f ai_engine

# Filter orchestrator logs
docker logs ai_engine --since 5m | grep -E "Orchestrator|Resolved|Negotiated"

# Collect RCA bundle
bash scripts/rca_collect.sh

# Restart engine only
docker compose restart ai-engine

# Force rebuild + restart
docker compose build ai-engine && docker compose up -d --force-recreate ai-engine

# SSH to server
ssh root@voiprnd.nemtclouddispatch.com

# Server logs capture
timestamp=$(date +%Y%m%d-%H%M%S)
ssh root@voiprnd.nemtclouddispatch.com "cd /root/Asterisk-AI-Voice-Agent && docker compose logs ai-engine --since 30m --no-color" > logs/ai-engine-p1-test-$timestamp.log
```

---

**Status**: Ready for testing  
**Next**: Run Test 1 (Deepgram golden baseline) to validate P1 implementation
