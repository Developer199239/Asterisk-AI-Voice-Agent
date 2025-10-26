# P1 Multi-Provider Transport Orchestration - Implementation Complete

**Date**: October 26, 2025  
**Status**: ✅ **READY FOR TESTING**  
**ROADMAPv4 Milestone**: P1 — Transport Orchestrator + Audio Profiles

---

## Executive Summary

P1 implementation is **complete** and ready for validation testing against golden baselines. The Transport Orchestrator provides provider-agnostic audio format negotiation with declarative audio profiles and per-call overrides via channel variables.

### What Was Implemented

1. ✅ **TransportOrchestrator** (`src/core/transport_orchestrator.py`)
   - Profile resolution with precedence (AI_PROVIDER > AI_CONTEXT > AI_AUDIO_PROFILE > default)
   - Provider capability negotiation
   - Format validation and remediation logging
   - Legacy config synthesis for backward compatibility

2. ✅ **Provider Capabilities** (`src/providers/base.py`)
   - Added `can_negotiate` field to `ProviderCapabilities`
   - Deepgram: `can_negotiate=True` (uses `SettingsApplied` ACK)
   - OpenAI Realtime: `can_negotiate=False` (uses static `session.update`)

3. ✅ **Deepgram Provider** (`src/providers/deepgram.py`)
   - `get_capabilities()` - static capability hints
   - `parse_ack()` - parses `SettingsApplied` event
   - Supports: mulaw/linear16 @ 8k/16k input, mulaw @ 8k output

4. ✅ **OpenAI Realtime Provider** (`src/providers/openai_realtime.py`)
   - `get_capabilities()` - static capability hints
   - `parse_ack()` - parses `session.updated` event
   - Supports: ulaw/linear16 @ 8k/16k input, mulaw/pcm16 @ 8k/24k output

5. ✅ **Engine Integration** (`src/engine.py`)
   - `_resolve_audio_profile()` - integrated orchestrator
   - Reads `AI_PROVIDER`, `AI_AUDIO_PROFILE`, `AI_CONTEXT` channel vars
   - Applies resolved transport to session and streaming manager
   - Backwards compatible with legacy `TransportProfile` from `models.py`

---

## Architecture Overview

### Data Flow

```
Asterisk Channel Vars (AI_PROVIDER, AI_AUDIO_PROFILE, AI_CONTEXT)
  ↓
TransportOrchestrator.resolve_transport()
  ├─ Load audio profile from YAML
  ├─ Get provider capabilities (static or ACK)
  ├─ Negotiate formats (wire, provider I/O)
  ├─ Validate and add remediation
  └─ Return TransportProfile
        ↓
Engine applies to:
  ├─ session.transport_profile
  ├─ streaming_playback_manager (wire format, chunk_ms, idle_cutoff_ms)
  └─ provider.config (target encoding/rate)
```

### Key Components

**AudioProfile** (YAML config):
```yaml
profiles:
  default: telephony_ulaw_8k
  telephony_ulaw_8k:
    internal_rate_hz: 8000
    transport_out:
      encoding: slin          # AudioSocket wire format (ALWAYS PCM16)
      sample_rate_hz: 8000
    provider_pref:
      input_encoding: mulaw   # What provider accepts
      input_sample_rate_hz: 8000
      output_encoding: mulaw  # What provider sends
      output_sample_rate_hz: 8000
    chunk_ms: auto            # Resolves to 20ms
    idle_cutoff_ms: 1200
```

**TransportProfile** (resolved per call):
```python
@dataclass
class TransportProfile:
    profile_name: str
    wire_encoding: str                  # AudioSocket (from YAML/dialplan)
    wire_sample_rate: int
    provider_input_encoding: str        # Negotiated with provider
    provider_input_sample_rate: int
    provider_output_encoding: str
    provider_output_sample_rate: int
    internal_rate: int
    chunk_ms: int
    idle_cutoff_ms: int
    context: Optional[str]
    remediation: Optional[str]
```

### Critical Insights

1. **AudioSocket wire format is SEPARATE from provider format**
   - AudioSocket: Always PCM16 (`slin` @ 8k/16k/24k per dialplan)
   - Provider: Can be mulaw, linear16, pcm16, g711_ulaw, etc.
   - Engine handles transcoding at boundaries

2. **Two TransportProfile classes coexist**
   - `models.py`: Simple legacy version (format, sample_rate, source)
   - `transport_orchestrator.py`: Detailed P1 version (wire + provider I/O)
   - Engine code checks `hasattr(profile, 'wire_encoding')` to distinguish

3. **Provider capability negotiation levels**
   - **Static**: Provider declares supported formats via `get_capabilities()`
   - **Runtime ACK**: Provider confirms negotiated formats via `parse_ack()`
   - **Fallback**: If ACK missing, orchestrator uses static capabilities or YAML config

---

## Testing Strategy

### Phase 1: Golden Baseline Validation (Deepgram)

**Goal**: Confirm P1 doesn't regress P0 golden baseline

**Setup**:
```bash
# Server dialplan
[from-ai-agent-deepgram]
exten => s,1,NoOp(Deepgram via P1 orchestrator)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Set(AI_AUDIO_PROFILE=telephony_ulaw_8k)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

**Config** (`config/ai-agent.yaml`):
```yaml
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
    idle_cutoff_ms: 1200
```

**Expected Metrics** (must match P0 golden baseline):
- ✅ Underflows: 0
- ✅ Drift: ≈ 0%
- ✅ Provider bytes: TX bytes ratio ≈ 1.0
- ✅ SNR: > 64 dB
- ✅ Audio quality: Subjectively clean, natural

**Logs to Verify**:
```bash
docker logs ai_engine --since 2m | grep -E "TransportOrchestrator|Resolved audio profile|Negotiated transport"
```

Expected output:
```
TransportOrchestrator initialized profiles=['telephony_ulaw_8k'] contexts=[] default='telephony_ulaw_8k'
Resolved audio profile for call profile='telephony_ulaw_8k' context=None provider='deepgram'
Negotiated transport profile profile='telephony_ulaw_8k' transport=TransportProfile(...)
```

---

### Phase 2: Golden Baseline Validation (OpenAI Realtime)

**Goal**: Confirm P1 works with OpenAI Realtime provider

**Setup**:
```bash
# Server dialplan
[from-ai-agent-openai]
exten => s,1,NoOp(OpenAI Realtime via P1 orchestrator)
 same => n,Set(AI_PROVIDER=openai_realtime)
 same => n,Set(AI_AUDIO_PROFILE=telephony_ulaw_8k)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

**Expected Metrics** (must match P0.5 golden baseline):
- ✅ SNR: > 64 dB
- ✅ No self-interruption
- ✅ Gate closures: ≤ 1 per call
- ✅ VAD buffered chunks: 0 (with `webrtc_aggressiveness: 1`)
- ✅ Audio quality: Clean, natural conversation flow

**Critical Config** (from P0.5 golden baseline):
```yaml
vad:
  use_provider_vad: false
  enhanced_enabled: true
  webrtc_aggressiveness: 1  # CRITICAL for OpenAI echo prevention
  confidence_threshold: 0.6
  energy_threshold: 1500
```

---

### Phase 3: Context Mapping Test

**Goal**: Verify `AI_CONTEXT` maps to profile + provider + prompt

**Setup**:
```yaml
# config/ai-agent.yaml
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

**Dialplan**:
```asterisk
[from-ai-agent-sales]
exten => s,1,Set(AI_CONTEXT=sales)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

**Expected**:
- Profile: `telephony_ulaw_8k`
- Provider: `deepgram`
- Greeting: "Thanks for calling sales!"

---

### Phase 4: Profile Override Test

**Goal**: Verify `AI_AUDIO_PROFILE` channel var overrides context/default

**Dialplan**:
```asterisk
[from-ai-agent-test]
exten => s,1,Set(AI_AUDIO_PROFILE=wideband_pcm_16k)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

**Expected**:
- Wire encoding: `slin16` (PCM16 @ 16k)
- Provider input: `linear16 @ 16000`
- Logs show: `profile='wideband_pcm_16k'`

---

## Validation Checklist

Before marking P1 as production-ready:

### Code Quality
- [x] TransportOrchestrator class created
- [x] Provider capabilities added (Deepgram, OpenAI Realtime)
- [x] ACK parsing methods implemented
- [x] Integration with engine._resolve_audio_profile()
- [x] can_negotiate field added to ProviderCapabilities
- [x] Backward compatibility maintained (legacy TransportProfile still works)

### Testing
- [ ] **Deepgram golden baseline validated** (run 60s call, compare metrics)
- [ ] **OpenAI Realtime golden baseline validated** (run 60s call, verify no self-interruption)
- [ ] Context mapping test passed
- [ ] Profile override test passed
- [ ] Legacy config (no profiles block) still works

### Documentation
- [ ] Update `docs/Architecture.md` with TransportOrchestrator section
- [ ] Create multi-provider usage guide
- [ ] Update `docs/plan/ROADMAPv4.md` with P1 completion status
- [ ] Add channel var reference guide

### Observability
- [ ] TransportCard logged at call start
- [ ] Profile resolution logs visible
- [ ] Remediation messages logged when provider doesn't support preferred format

---

## Known Issues & Limitations

### Type Compatibility
- **Issue**: Two `TransportProfile` classes exist (`models.py` vs `transport_orchestrator.py`)
- **Impact**: Engine code must check `hasattr(profile, 'wire_encoding')` to distinguish
- **Mitigation**: Already implemented in `_emit_transport_card()` and `_resolve_stream_targets()`
- **Future**: Consolidate into single TransportProfile class in P2

### Late ACK Handling
- **Current**: TransportProfile locked at call start; late ACK ignored with warning
- **Limitation**: If provider ACK arrives >500ms after call start, profile won't adjust
- **Mitigation**: Most providers ACK within 100-200ms; this is rare edge case
- **Future**: Add renegotiation support in post-GA

### Provider-Specific Quirks
- **Deepgram**: Some voices reject `linear16@8k`; orchestrator falls back to `mulaw@8k`
- **OpenAI**: Always prefers 24kHz output; downsampling to 8k/16k done in engine
- **Remediation**: Both handled automatically with logged warnings

---

## Deployment Instructions

### Local Development
```bash
# 1. Review changes
git diff develop

# 2. Commit P1 implementation
git add src/core/transport_orchestrator.py \
        src/providers/base.py \
        src/providers/deepgram.py \
        src/providers/openai_realtime.py \
        src/engine.py

git commit -m "feat(p1): complete multi-provider transport orchestration

- Add TransportOrchestrator with profile resolution
- Add can_negotiate field to ProviderCapabilities
- Implement get_capabilities() and parse_ack() for Deepgram/OpenAI
- Integrate orchestrator into engine._resolve_audio_profile()
- Maintain backward compatibility with legacy TransportProfile

Ready for golden baseline validation testing."

# 3. Push to develop
git push origin develop
```

### Server Deployment
```bash
# Follow standard deployment workflow (from memory)
# 1. Server: git pull --rebase
# 2. Rebuild: docker compose build ai-engine
# 3. Restart: docker compose up -d --force-recreate ai-engine
# 4. Verify logs: docker logs --since 2m ai_engine | grep TransportOrchestrator
```

---

## Next Steps

### Immediate (Before Production)
1. **Run Deepgram golden baseline test** (~10 min)
   - Place 60s call to from-ai-agent-deepgram
   - Collect RCA: `bash scripts/rca_collect.sh`
   - Compare metrics vs P0 golden baseline
   - **Pass criteria**: Underflows=0, drift≈0%, SNR>64dB

2. **Run OpenAI Realtime golden baseline test** (~10 min)
   - Place 60s call to from-ai-agent-openai
   - Collect RCA
   - Compare metrics vs P0.5 golden baseline
   - **Pass criteria**: SNR>64dB, gate_closures≤1, no self-interruption

3. **Quick context mapping smoke test** (~5 min)
   - Set `AI_CONTEXT=sales` in dialplan
   - Place call, verify profile/provider/greeting

### P2 Preparation (Config Cleanup)
- Deprecate legacy knobs (`egress_swap_mode`, `allow_output_autodetect`)
- Add `config_version: 4` validation
- Create migration script: `scripts/migrate_config_v4.py`
- Add CLI tools: `agent doctor`, `agent demo`

### Future Enhancements
- Add more providers: Google Cloud, Azure, ElevenLabs
- Add wideband profiles: `wideband_pcm_16k`, `hifi_pcm_24k`
- Add Prometheus metrics: `ai_agent_profile_selection`, `ai_agent_negotiation_failures`
- Add late ACK renegotiation (post-GA)

---

## Rollback Plan

If P1 causes regressions:

```bash
# 1. Stop engine
docker compose stop ai-engine

# 2. Revert code
git revert <P1_commit_sha>

# 3. Rebuild
docker compose build ai-engine

# 4. Restart
docker compose up -d ai-engine

# 5. Validate golden baseline restored
```

**Or** set environment variable to disable orchestrator:
```bash
# .env
DISABLE_TRANSPORT_ORCHESTRATOR=true
```

---

## Acknowledgments

**Golden Baselines Referenced**:
- P0: Deepgram telephony_ulaw_8k (call 1761424308.2043, Oct 25 2025)
- P0.5: OpenAI Realtime with VAD level 1 (call 1761449250.2163, Oct 26 2025)

**Key Documents**:
- `docs/AudioSocket with Asterisk_ Technical Summary for A.md`
- `docs/AudioSocket-Provider-Alignment.md`
- `docs/plan/ROADMAPv4.md`
- `OPENAI_REALTIME_GOLDEN_BASELINE.md`

---

**Status**: ✅ **Implementation Complete — Ready for Validation Testing**
