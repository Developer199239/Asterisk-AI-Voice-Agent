# P2.3 Config Cleanup - Comprehensive Audit

## Executive Summary

Current config: **374 lines, ~150 distinct parameters**

**Recommendation**: Keep production-critical knobs, move troubleshooting knobs to env vars, remove deprecated settings.

---

## 1. PRODUCTION-CRITICAL (MUST KEEP)

### 1.1 AudioSocket Transport
```yaml
audiosocket:
  host: "0.0.0.0"
  port: 8090
  format: "slin"  # CRITICAL: Must be PCM16 @ 8kHz per golden baseline
```

**Impact**: AudioSocket wire format  
**Affects**: All calls  
**Golden Baseline**: `format: slin` (PCM16 @ 8kHz)  
**Keep**: YES - Core functionality

---

### 1.2 VAD Configuration
```yaml
vad:
  use_provider_vad: false
  enhanced_enabled: true  # Required for OpenAI gating
  webrtc_aggressiveness: 1  # CRITICAL for OpenAI echo prevention
  webrtc_start_frames: 3
  webrtc_end_silence_frames: 50
  min_utterance_duration_ms: 600
  max_utterance_duration_ms: 10000
  utterance_padding_ms: 200
  confidence_threshold: 0.6  # Not in current dump but used in code
  energy_threshold: 1500     # Not in current dump but used in code
```

**Impact**: Turn detection, echo prevention, gating  
**Affects**: OpenAI Realtime (echo), all providers (turn detection)  
**Golden Baseline**: `webrtc_aggressiveness: 1` prevents echo false positives  
**Keep**: YES - Validated production settings

---

### 1.3 Barge-in Configuration
```yaml
barge_in:
  enabled: true
  initial_protection_ms: 100
  min_ms: 250
  energy_threshold: 1100
  post_tts_end_protection_ms: 100
```

**Impact**: User interruption handling  
**Affects**: All calls  
**Keep**: YES - Production feature

---

### 1.4 Streaming Core Settings
```yaml
streaming:
  sample_rate: 8000           # Output sample rate
  chunk_size_ms: 20           # Wire pacing (320 bytes PCM16)
  continuous_stream: true     # Single stream across segments
```

**Impact**: Audio pacing and delivery  
**Affects**: All calls  
**Golden Baseline**: 20ms frames, continuous stream  
**Keep**: YES - Core streaming behavior

---

### 1.5 Provider Configurations
```yaml
providers:
  deepgram:
    enabled: true
    api_key: "${DEEPGRAM_API_KEY}"
    model: "nova-2-phonecall"
    tts_model: "aura-2-thalia-en"
    input_encoding: "mulaw"
    input_sample_rate_hz: 8000
    output_encoding: "mulaw"
    output_sample_rate_hz: 8000
    continuous_input: true
    
  openai_realtime:
    enabled: true
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4o-realtime-preview-2024-12-17"
    voice: "alloy"
    input_encoding: "ulaw"
    input_sample_rate_hz: 8000
    provider_input_encoding: "linear16"
    provider_input_sample_rate_hz: 24000
    output_encoding: "linear16"
    output_sample_rate_hz: 24000
    target_encoding: "mulaw"
    target_sample_rate_hz: 8000
    turn_detection:  # OpenAI server-side VAD
      type: "server_vad"
      silence_duration_ms: 500
      threshold: 0.5
      prefix_padding_ms: 200
      create_response: true
```

**Impact**: Provider connectivity and format negotiation  
**Affects**: All calls to respective providers  
**Keep**: YES - Provider-specific settings

---

### 1.6 Audio Profiles (P1 Feature)
```yaml
profiles:
  default: telephony_responsive
  
  telephony_responsive:
    internal_rate_hz: 8000
    transport_out: { encoding: slin, sample_rate_hz: 8000 }
    provider_pref: { input_encoding: mulaw, input_sample_rate_hz: 8000 }
    chunk_ms: auto
    idle_cutoff_ms: 600
    
  openai_realtime_24k:
    internal_rate_hz: 24000
    transport_out: { encoding: slin, sample_rate_hz: 8000 }
    provider_pref: { input_encoding: pcm16, input_sample_rate_hz: 24000 }
    chunk_ms: 20
    idle_cutoff_ms: 0  # Rely on response.done
```

**Impact**: Per-call format negotiation  
**Affects**: Calls using AI_AUDIO_PROFILE channel var  
**Keep**: YES - P1 feature, production-ready

---

### 1.7 Context Mapping (P1 Feature)
```yaml
contexts:
  default: { prompt: "...", greeting: "...", profile: telephony_ulaw_8k }
  sales: { prompt: "...", greeting: "...", profile: wideband_pcm_16k }
  support: { prompt: "...", greeting: "...", profile: telephony_ulaw_8k }
  premium: { prompt: "...", greeting: "...", profile: openai_realtime_24k, provider: openai_realtime }
```

**Impact**: Semantic routing via AI_CONTEXT channel var  
**Affects**: Calls using context mapping  
**Keep**: YES - P1 feature, cleaner than inline vars

---

## 2. PRODUCTION-USEFUL (SHOULD KEEP)

### 2.1 Buffer Management
```yaml
streaming:
  jitter_buffer_ms: 950       # Buffer size for underflow prevention
  min_start_ms: 120           # Warmup before first frame
  low_watermark_ms: 80        # Pause threshold
  greeting_min_start_ms: 40   # Faster greeting start
```

**Impact**: Audio quality and timing  
**Affects**: All calls  
**Tuning**: May need adjustment per deployment  
**Keep**: YES - Validated settings, but allow override

---

### 2.2 Timeout Configuration
```yaml
streaming:
  keepalive_interval_ms: 5000
  connection_timeout_ms: 120000
  fallback_timeout_ms: 8000
  provider_grace_ms: 500
```

**Impact**: Connection stability and cleanup  
**Affects**: All calls  
**Keep**: YES - Operational stability

---

### 2.3 Normalizer
```yaml
streaming:
  normalizer:
    enabled: true
    target_rms: 1400
    max_gain_db: 18.0
```

**Impact**: Audio loudness normalization  
**Affects**: All calls  
**Tuning**: Validated settings  
**Keep**: YES - Improves audio quality

---

### 2.4 Pipeline Configuration
```yaml
pipelines:
  default: { stt: deepgram, llm: deepgram, tts: deepgram }
  openai_only: { stt: openai_stt, llm: openai_llm, tts: openai_tts }
  local_only: { stt: local_stt, llm: local_llm, tts: local_tts }
  
active_pipeline: "default"
```

**Impact**: Component selection  
**Affects**: Pipeline orchestrator (P1 feature)  
**Keep**: YES - Multi-provider support

---

## 3. TROUBLESHOOTING-ONLY (MOVE TO ENV VARS)

### 3.1 Egress Swap Mode ⚠️
```yaml
streaming:
  egress_swap_mode: "auto"    # Auto-detect PCM16 byte order
  egress_force_mulaw: false
```

**Impact**: PCM16 byte order detection (troubleshooting)  
**Affects**: Only if AudioSocket endianness issues  
**Current Use**: Not needed with golden baseline (slin=LE)  
**Action**: Move to env var `DIAG_EGRESS_SWAP_MODE=auto`  
**Default**: Remove from YAML (engine defaults to no-swap)

**Rationale**: 
- AudioSocket Type 0x10 is **always** little-endian PCM16 per spec
- Swap detection was for debugging big-endian issues
- Golden baseline uses slin correctly (no swap needed)
- Keep as env var for edge cases

---

### 3.2 Attack Envelope ⚠️
```yaml
streaming:
  attack_ms: 0  # DISABLED: Was creating initial silence
```

**Impact**: Attack envelope ramp (no longer used)  
**Affects**: Nothing (disabled at 0)  
**Current Use**: Disabled after causing issues  
**Action**: Remove from YAML entirely  
**Fallback**: Env var `DIAG_ATTACK_MS=0` if needed

**Rationale**:
- Created initial silence in production
- Disabled in golden baseline
- No production use case
- Keep as diagnostic env var only

---

### 3.3 Diagnostic Taps
```yaml
streaming:
  diag_enable_taps: true
  diag_pre_secs: 1
  diag_post_secs: 1
  diag_out_dir: "/tmp/ai-engine-taps"
```

**Impact**: Captures PCM snapshots for analysis  
**Affects**: Disk I/O, storage  
**Current Use**: Enabled for RCA collection  
**Action**: Move to env var `DIAG_ENABLE_TAPS=true`  
**Default**: Disable in YAML (enable via env for debugging)

**Rationale**:
- Production doesn't need continuous tap capture
- Enable only when running RCA
- Reduces disk I/O overhead
- Keeps troubleshooting capability

---

### 3.4 Logging Level Override
```yaml
streaming:
  logging_level: "debug"
```

**Impact**: Streaming logger verbosity  
**Affects**: Log volume  
**Current Use**: Debug mode enabled  
**Action**: Move to env var `STREAMING_LOG_LEVEL=debug`  
**Default**: Use root logger level (info/warning)

**Rationale**:
- Production doesn't need debug logs
- Increases log volume significantly
- Keep as env var for troubleshooting

---

### 3.5 Empty Backoff Ticks
```yaml
streaming:
  empty_backoff_ticks_max: 5
```

**Impact**: Adaptive backoff during provider silence  
**Affects**: Buffer behavior  
**Current Use**: Reduces filler churn  
**Action**: Keep but document as advanced tuning  
**Alternative**: Move to env var if rarely changed

**Rationale**:
- Working well in current implementation
- Rarely needs adjustment
- Could move to env var if not user-facing

---

## 4. DEPRECATED/LEGACY (REMOVE OR MARK)

### 4.1 Allow Output Autodetect ❌
```yaml
providers:
  deepgram:
    allow_output_autodetect: false
```

**Impact**: Output format auto-detection  
**Affects**: Nothing (always false)  
**Current Use**: Disabled  
**Action**: **REMOVE** - No longer used  

**Rationale**:
- Format negotiation now handled by Transport Orchestrator (P1)
- Provider capabilities are explicit
- Auto-detection caused unpredictable behavior
- Not used in golden baseline

---

### 4.2 Downstream Mode Selection
```yaml
downstream_mode: "stream"
```

**Impact**: Stream vs file playback mode  
**Affects**: Playback path selection  
**Current Use**: Always "stream" in production  
**Action**: Keep for now, consider deprecating "file" mode  
**Alternative**: Make stream-only, remove mode selection

**Rationale**:
- File mode has higher latency
- Stream mode is proven stable
- Could simplify by making stream-only
- Keep for backward compatibility temporarily

---

### 4.3 Audio Transport Selection
```yaml
audio_transport: "audiosocket"
```

**Impact**: AudioSocket vs ExternalMedia  
**Affects**: Transport layer selection  
**Current Use**: Always AudioSocket (ExternalMedia fallback unused)  
**Action**: Keep but document AudioSocket as primary  

**Rationale**:
- AudioSocket is proven stable
- ExternalMedia (RTP) is fallback only
- Keep option but clarify primary path

---

### 4.4 Fallback VAD Settings
```yaml
vad:
  fallback_enabled: true
  fallback_interval_ms: 4000
  fallback_buffer_size: 128000
```

**Impact**: VAD fallback when detection fails  
**Affects**: Edge cases with VAD failures  
**Current Use**: Enabled but rarely triggered  
**Action**: Keep but document as safety net  

**Rationale**:
- Rarely used in production
- Good safety mechanism
- Low overhead when not triggered
- Keep for robustness

---

## 5. PROVIDER-SPECIFIC ANALYSIS

### 5.1 Deepgram Settings

**Production-Critical**:
- `enabled`, `api_key`, `model`, `tts_model`
- `input_encoding`, `input_sample_rate_hz`
- `output_encoding`, `output_sample_rate_hz`
- `continuous_input: true`

**Remove**:
- `allow_output_autodetect: false` ❌

---

### 5.2 OpenAI Realtime Settings

**Production-Critical**:
- All encoding/sample rate settings (complex transcoding)
- `turn_detection` block (server-side VAD)
- `egress_pacer_enabled`, `egress_pacer_warmup_ms`

**Note**: OpenAI has most complex config due to:
- 24kHz internal processing
- 8kHz telephony output
- Server-side VAD settings
- Multiple encoding layers

---

### 5.3 Local Provider Settings

**Status**: Experimental/development  
**Action**: Keep but mark as development-only  
**Rationale**: Local AI server for offline inference

---

## 6. SUMMARY & RECOMMENDATIONS

### Keep in YAML (Production Config)

**Core Settings** (~80 lines):
- AudioSocket (host, port, format)
- VAD (webrtc_aggressiveness, frames, utterance settings)
- Barge-in (protection timings, thresholds)
- Streaming core (sample_rate, chunk_size_ms, continuous_stream)
- Buffer management (jitter_buffer_ms, watermarks)
- Normalizer (enabled, target_rms, max_gain_db)
- Timeouts (keepalive, connection, fallback)
- Provider configs (credentials, models, encodings)
- Audio profiles (P1 feature)
- Context mapping (P1 feature)
- Pipeline definitions

### Move to Environment Variables

**Troubleshooting Settings**:
```bash
DIAG_EGRESS_SWAP_MODE=auto       # Default: no-swap
DIAG_ATTACK_MS=0                 # Default: 0 (disabled)
DIAG_ENABLE_TAPS=false           # Default: false
STREAMING_LOG_LEVEL=info         # Default: info
DIAG_ENABLE_AUDIO_PROCESSING=false  # Attack/normalizer/limiter override
```

### Remove from YAML

**Deprecated**:
- `allow_output_autodetect` (everywhere)
- `attack_ms` (move to env var)
- Diagnostic taps (move to env var)
- Logging level overrides (move to env var)

### Mark as Advanced/Optional

**Low-frequency tuning**:
- `empty_backoff_ticks_max`
- `provider_grace_ms`
- Fallback VAD settings
- External Media config (fallback path)

---

## 7. MIGRATION PLAN

### Phase 1: Immediate (No Breaking Changes)

1. **Add env var support** for troubleshooting knobs:
   - Read `DIAG_*` env vars
   - Fall back to YAML if env not set
   - Log deprecation warnings

2. **Mark deprecated** in comments:
   ```yaml
   # DEPRECATED: Use DIAG_EGRESS_SWAP_MODE env var instead
   egress_swap_mode: "auto"
   ```

3. **Update documentation**:
   - List production-critical settings
   - Document env var overrides
   - Migration guide for existing deployments

### Phase 2: Gradual Deprecation (1-2 releases)

1. **Warn on deprecated usage**:
   - Log warnings when deprecated knobs are present
   - Suggest env var alternatives
   - Continue functioning

2. **Provide migration script**:
   ```bash
   ./scripts/migrate_config_v4.py
   ```
   - Reads current YAML
   - Generates clean YAML + .env file
   - Preserves settings via env vars

### Phase 3: Removal (2-3 releases later)

1. **Remove deprecated knobs** from schema
2. **Env vars become only option** for diagnostics
3. **Clean production config** (~150 lines)

---

## 8. IMPACT ANALYSIS

### Current Config Complexity

| Category | Lines | Knobs |
|----------|-------|-------|
| Production-Critical | ~80 | ~40 |
| Production-Useful | ~50 | ~25 |
| Troubleshooting | ~30 | ~15 |
| Deprecated/Legacy | ~20 | ~10 |
| Comments | ~194 | - |
| **Total** | **374** | **~90** |

### After Cleanup

| Category | Lines | Knobs |
|----------|-------|-------|
| Production Config (YAML) | ~150 | ~65 |
| Troubleshooting (env vars) | - | ~15 |
| Removed | - | ~10 |
| **Total User-Facing** | **150** | **80** |

### Benefits

✅ **Simpler onboarding** - Less to understand  
✅ **Clearer intent** - Production vs troubleshooting  
✅ **Safer defaults** - Diagnostics opt-in  
✅ **Better performance** - No diagnostic overhead  
✅ **Easier validation** - Smaller schema  

---

## 9. RECOMMENDED ACTION

### Option A: Full Cleanup (P2.3)
**Timeline**: 1-2 days  
**Breaking**: Minor (with migration script)  
**Value**: High (cleaner config long-term)

### Option B: Incremental (Over Time)
**Timeline**: Per release  
**Breaking**: None (deprecation warnings)  
**Value**: Medium (gradual improvement)

### Option C: Defer (Focus on Production)
**Timeline**: N/A  
**Breaking**: None  
**Value**: Low (current config works)

---

## 10. DECISION QUESTIONS

1. **Is config complexity causing operator confusion?**
   - If YES → Do P2.3 now
   - If NO → Defer

2. **Are troubleshooting knobs being misused in production?**
   - If YES → Move to env vars now
   - If NO → Can defer

3. **Do we need cleaner config for documentation/marketing?**
   - If YES → Do P2.3 for better first impression
   - If NO → Current config is functional

4. **Is there user demand for simplified config?**
   - If YES → Prioritize cleanup
   - If NO → Focus on features

---

**My Recommendation**: **Option B - Incremental Deprecation**

- Add env var support now (non-breaking)
- Deprecation warnings in next release
- Remove in 2-3 releases
- Keeps momentum on production features
- Reduces risk of breaking changes

**What's your preference?**
