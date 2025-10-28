# Config V4 Release - October 28, 2025

## 🎉 CLEAN V4 RELEASE (No Migration Needed)

This is a clean v4 config release with NO migration path. All deprecation warnings removed.

---

## ✅ WHAT CHANGED

### 1. `.env.example` - Added Diagnostic Settings

**New section with 8 diagnostic settings**:
```bash
# Streaming logger verbosity (debug|info|warning|error)
STREAMING_LOG_LEVEL=info

# PCM16 byte order detection (auto|swap|none)
DIAG_EGRESS_SWAP_MODE=none

# Force μ-law output (true|false)
DIAG_EGRESS_FORCE_MULAW=false

# Attack envelope duration in ms (0=disabled)
DIAG_ATTACK_MS=0

# Enable audio taps for RCA (true|false)
DIAG_ENABLE_TAPS=false

# Tap durations in seconds
DIAG_TAP_PRE_SECS=1
DIAG_TAP_POST_SECS=1

# Tap output directory
DIAG_TAP_OUTPUT_DIR=/tmp/ai-engine-taps
```

**Each setting includes**:
- Clear description
- Possible values
- When to use it
- Production recommendations

### 2. `config/ai-agent.yaml` - Clean V4 Format

**Changes**:
- ✅ Added `config_version: 4`
- ❌ Removed all diagnostic settings (now in `.env`)
- ❌ Removed `streaming.logging_level`
- ❌ Removed `streaming.egress_swap_mode`
- ❌ Removed `streaming.egress_force_mulaw`
- ❌ Removed `streaming.attack_ms`
- ❌ Removed `streaming.diag_enable_taps`
- ❌ Removed `streaming.diag_pre_secs/diag_post_secs/diag_out_dir`
- ❌ Removed `providers.*.allow_output_autodetect`

**Result**: 375 lines → 290 lines (23% smaller)

### 3. `src/config.py` - Clean Code

**Removed**:
- All deprecation warnings
- Migration messages
- YAML fallbacks for diagnostic settings

**Now**:
- Reads diagnostic settings from env vars only
- Clean, simple code
- Production-ready defaults

### 4. Removed Migration Script

- ❌ Deleted `scripts/migrate_config_v4.py`
- No migration path needed for v4

---

## 📊 BEFORE vs AFTER

### Startup Logs (Before - v3)
```
[info] Config version 3 detected. Consider running: python scripts/migrate_config_v4.py
[warning] DEPRECATED: streaming.egress_swap_mode in YAML - use DIAG_EGRESS_SWAP_MODE env var instead
[warning] DEPRECATED: streaming.egress_force_mulaw in YAML - use DIAG_EGRESS_FORCE_MULAW env var instead
[warning] DEPRECATED: streaming.attack_ms in YAML - use DIAG_ATTACK_MS env var instead
[warning] DEPRECATED: streaming.diag_enable_taps in YAML - use DIAG_ENABLE_TAPS env var instead
[warning] DEPRECATED: streaming.logging_level in YAML - use STREAMING_LOG_LEVEL env var instead
[info] Provider validated and ready: deepgram
[info] Provider validated and ready: openai_realtime
```

### Startup Logs (After - v4)
```
[info] Provider validated and ready: deepgram
[info] Provider validated and ready: openai_realtime
[info] Pipeline orchestrator initialized: healthy_pipelines=4
[info] Engine started and listening for calls.
```

**✅ NO WARNINGS!**

---

## 🚀 DEPLOYMENT STATUS

**Commit**: `59f2d39`  
**Deployed**: October 28, 2025 @ 12:01 PM PDT  
**Status**: ✅ **PRODUCTION READY**

**Validation**:
- ✅ No deprecation warnings
- ✅ No migration messages
- ✅ Clean startup
- ✅ All providers validated
- ✅ 4 healthy pipelines
- ✅ Engine started successfully

---

## 📖 FOR NEW DEPLOYMENTS

1. **Copy `.env.example` to `.env`**
2. **Set required variables**:
   ```bash
   ASTERISK_HOST=...
   ASTERISK_ARI_USERNAME=...
   ASTERISK_ARI_PASSWORD=...
   OPENAI_API_KEY=...
   DEEPGRAM_API_KEY=...
   ```
3. **Optionally enable diagnostics** (see `.env.example` for details)
4. **Deploy**: `docker compose up -d`

---

## 📖 FOR EXISTING DEPLOYMENTS

Your old config will still work, but diagnostic settings in YAML are now ignored.

**To enable diagnostics**, add to your `.env` file:
```bash
# Example: Enable debug logging and audio taps
STREAMING_LOG_LEVEL=debug
DIAG_ENABLE_TAPS=true
```

See `.env.example` for full list of diagnostic options.

---

## 🎯 BENEFITS

| Aspect | Before (v3) | After (v4) |
|--------|-------------|------------|
| **Warnings** | 5-6 per startup | 0 ✅ |
| **Config size** | 375 lines | 290 lines (-23%) |
| **Clarity** | Mixed concerns | Clear separation |
| **Diagnostics** | Edit YAML + rebuild | Edit .env + restart |
| **Migration** | Needed | None ✅ |

---

## 📝 RELATED

- Commit: `59f2d39`
- ROADMAPv4: P2.3 Config Cleanup
- Related fixes: Pipeline TTS bug, codec alignment warnings
