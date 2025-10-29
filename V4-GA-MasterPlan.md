# GA v4.0 Master Plan

**Version**: 4.0.0  
**Status**: 🟢 READY FOR RELEASE  
**Date**: October 28, 2025  
**Branch**: `develop` → `staging`

---

## Executive Summary

All core functionality **validated and working**. Three pipeline configurations tested successfully:
- ✅ **local_hybrid**: Golden baseline (recommended)
- ✅ **hybrid_support**: Cloud golden baseline  
- ✅ **local_only**: Functional (hardware-dependent)

**Status**: Ready for GA after documentation cleanup and pre-merge checklist completion.

---

## Table of Contents

1. [Pipeline Validation Summary](#pipeline-validation-summary)
2. [Monitoring & Metrics Status](#monitoring--metrics-status)
3. [Linear Issues Status](#linear-issues-status)
4. [CLI Tools Status](#cli-tools-status)
5. [Main Branch Structure](#main-branch-structure)
6. [Documentation Cleanup Plan](#documentation-cleanup-plan)
7. [Pre-Release Checklist](#pre-release-checklist)
8. [Release Timeline](#release-timeline)

---

## Pipeline Validation Summary

### ✅ local_hybrid (PRIMARY RECOMMENDATION)

**Components**: Vosk STT → OpenAI GPT-4o-mini → Piper TTS  
**Transport**: ExternalMedia RTP  
**Status**: ✅ **GOLDEN BASELINE**

**Performance**:
- Turn latency: **3-7 seconds**
- STT: Local, streaming partials
- LLM: Cloud, <1s response
- TTS: Local, ~600ms synthesis

**Use Cases**: Privacy-focused (audio stays local), fast responses

**Recommended For**: Most production deployments

---

### ✅ hybrid_support (CLOUD GOLDEN BASELINE)

**Components**: Deepgram STT → OpenAI LLM → Deepgram TTS  
**Status**: ✅ **VALIDATED**

**Performance**:
- Turn latency: **<3 seconds**
- Best quality (Deepgram + GPT-4)
- Fastest responses

**Recommended For**: Quality-critical deployments

---

### ⚠️ local_only (HARDWARE-DEPENDENT)

**Components**: Vosk STT → Phi-3 LLM → Piper TTS  
**Status**: ✅ **FUNCTIONAL**, ⚠️ **HARDWARE-DEPENDENT**

**Performance**:
- 2020+ CPU: **3-7 seconds** ✅
- 2014-2019 CPU: **10-30 seconds** ❌

**Hardware Requirements**:
- Minimum: AMD Ryzen 9 5950X / Intel i9-11900K (2020+)
- OR GPU: NVIDIA RTX 3060+
- 2014-2016 CPUs: NOT PRACTICAL

**Recommended For**: Air-gapped deployments with modern hardware

---

## Monitoring & Metrics Status

### ✅ COMPLETE - Production Ready

**Status**: ✅ **Implemented and Documented**

#### Components

1. **Prometheus** (port 9090) - Metrics collection
2. **Grafana** (port 3000) - Dashboards  
3. **Metrics Endpoint**: `ai_engine:15000/metrics`

#### Dashboards (5 Total)

- **call-tuning.json**: Turn latency, quality scores
- **gating-capture.json**: Audio gating events
- **latency.json**: Latency histograms (p50/p95/p99)
- **reliability.json**: Underflows, fallbacks, errors
- **streaming-health.json**: Jitter buffer, streaming stats

#### Collected Metrics (50+)

- Call quality (latency, underflows, barge-in)
- Audio quality (RMS, DC offset, codec alignment)
- Provider performance (Deepgram, OpenAI)
- System health (active calls, connections)

#### Documentation

**File**: `monitoring/README.md` (304 lines) - Complete guide

### Gaps: NONE ✅

All monitoring infrastructure is complete and production-ready.

---

## Linear Issues Status

### 📊 Summary

| Status | Count | Issues |
|--------|-------|--------|
| ✅ **Done** | **3** | AAVA-28, AAVA-24, AAVA-13 |
| ⚠️ **Backlog** | **6** | AAVA-14, AAVA-19, AAVA-20, AAVA-23, AAVA-25, AAVA-26 |

### Critical Issues for GA

#### ✅ AAVA-14: Production Logging Levels
**Status**: Will fix during merge to main (15 min)  
**Action**: Set LOG_LEVEL=info before merge

#### ✅ AAVA-19: Documentation Updates
**Status**: Will complete (4-6 hours)  
**Action**: Documentation cleanup session

#### ✅ AAVA-20: Pre-GA Testing
**Status**: USER COMPLETED  
**Action**: Document test results

### Non-Blocking Issues (Post-GA)

- AAVA-23: Config cleanup (defer to v4.1)
- AAVA-25: install.sh profiles (defer to v4.1)
- AAVA-26: install.sh UX (defer to v4.1+)

---

## CLI Tools Status

### ✅ CLI Tools Implemented

**Status**: ✅ **COMPLETE**

**Location**: `cli/cmd/agent/` (Go implementation)

**Available Commands**:
- `agent doctor` - System health check (cli/cmd/agent/doctor.go)
- `agent demo` - Demo functionality (cli/cmd/agent/demo.go)
- `agent init` - Initialize configuration (cli/cmd/agent/init.go)
- `agent troubleshoot` - Post-call analysis (cli/cmd/agent/troubleshoot.go)
- `agent version` - Show version (cli/cmd/agent/version.go)

**Build**:
```bash
cd cli/cmd/agent
go build -o agent
```

### Scripts Directory

**Available Scripts**:
- `rca_collect.sh` - RCA collection ✅
- `analyze_logs.py` - Log analysis (convert to shell script)
- `model_setup.py` - Model management (convert to shell script)
- Various testing/monitoring scripts

### GA Action Items

**Before Release**:
1. Convert `analyze_logs.py` to shell script (Python version compatibility)
2. Convert `model_setup.py` to shell script (Python version compatibility)
3. Document CLI tools in README.md
4. Add build instructions for `agent` binary

---

## Main Branch Structure

### Files to Add

```
CHANGELOG.md (root)
V4-GA-MasterPlan.md (this file)
monitoring/ (entire directory)
docs/
├── MONITORING_GUIDE.md
├── PRODUCTION_DEPLOYMENT.md
├── HARDWARE_REQUIREMENTS.md
├── Transport-Mode-Compatibility.md
└── case-studies/
    └── OPENAI_REALTIME_GOLDEN_BASELINE.md
```

### Files to Remove

```
# Development artifacts (40+ files)
OPENAI_*_RCA.md (23 files)
P1_*.md, P2_*.md, P3_*.md (20+ files)
PROGRESS_SUMMARY_*.md
DEPLOYED_FIX.md
# Keep in git history only
```

---

## Documentation Cleanup Plan

### Phase 1: Remove Development Artifacts (30 min)

```bash
# Remove RCA documents
rm OPENAI_*.md P1_*.md P2_*.md P3_*.md PROGRESS_*.md DEPLOYED_*.md

# Move golden baseline
mkdir -p docs/case-studies
mv OPENAI_REALTIME_GOLDEN_BASELINE.md docs/case-studies/
```

### Phase 2: Create New Documentation (5 hours)

1. **CHANGELOG.md** (30 min)
   - v4.0 features, fixes, breaking changes
   - Upgrade notes

2. **docs/HARDWARE_REQUIREMENTS.md** (1 hour)
   - local_only hardware requirements
   - Performance benchmarks by hardware
   - Decision tree

3. **docs/MONITORING_GUIDE.md** (1 hour)
   - Quick start
   - Dashboard walkthroughs
   - Alert configuration

4. **docs/PRODUCTION_DEPLOYMENT.md** (1 hour)
   - Security checklist
   - Logging configuration
   - Backup procedures

5. **Update README.md** (30 min)
   - Add GA v4.0 badge
   - Update features list
   - Add quick links

6. **docs/TESTING_VALIDATION.md** (30 min)
   - Document 3 validated pipeline calls
   - Test results summary

### Phase 3: Code Cleanup (1-2 hours)

**Remove Dead Code**:
1. **Remove unused classes** (src/engine.py):
   - `AudioFrameProcessor` (lines 128-167) - Defined but never instantiated
   - `VoiceActivityDetector` (lines 168-195) - Defined but never used

2. **Clean LLM Config** (src/config.py, config/ai-agent.yaml):
   - Remove `model` field from `LLMConfig` (not used, providers have own model fields)
   - Remove `temperature` from `LLMConfig` (not used at top level)
   - Remove from YAML: `llm.model`, `llm.temperature`

3. **Remove unused config** (config/ai-agent.yaml):
   - Delete `external_media.jitter_buffer_ms` (not consumed by RTP server)

4. **Convert Python scripts to shell**:
   - `scripts/analyze_logs.py` → `scripts/analyze_logs.sh`
   - `scripts/model_setup.py` → `scripts/model_setup.sh`
   - Reason: Python version compatibility across systems

**Impact**: Cleaner codebase, no functional changes

### Phase 4: Final Review (1 hour)

- Read through all documentation
- Check links work
- Verify examples correct
- Test CLI tools build

**Total Time**: ~8-9 hours

---

## Pre-Release Checklist

### Critical Path (Required Before Merge)

- [ ] **Set production logging** (15 min)
  ```bash
  LOG_LEVEL=info
  STREAMING_LOG_LEVEL=info
  ```

- [ ] **Create CHANGELOG.md** (30 min)
- [ ] **Create docs/HARDWARE_REQUIREMENTS.md** (1 hour)
- [ ] **Create docs/MONITORING_GUIDE.md** (1 hour)
- [ ] **Create docs/PRODUCTION_DEPLOYMENT.md** (1 hour)
- [ ] **Update README.md** (30 min)
- [ ] **Create docs/TESTING_VALIDATION.md** (30 min)
- [ ] **Code cleanup** (1-2 hours)
  - Remove dead classes (AudioFrameProcessor, VoiceActivityDetector)
  - Clean LLM config (remove unused fields)
  - Remove external_media.jitter_buffer_ms
  - Convert Python scripts to shell
- [ ] **Remove development artifacts** (30 min)
- [ ] **Document CLI tools** (30 min)
- [ ] **Final documentation review** (1 hour)

**Total Time**: ~8-9 hours

### Verification Steps

- [ ] Build from clean checkout
- [ ] Verify pipelines initialize
- [ ] Make test call (any pipeline)
- [ ] Deploy monitoring stack
- [ ] Review all documentation

### Merge to Main

1. Complete critical path checklist
2. Create merge commit (--no-ff)
3. Tag release (v4.0.0)
4. Push to remote
5. Create GitHub release

---

## Release Timeline

### Day 1 (Oct 28, 2025)
- [x] Create V4-GA-MasterPlan.md
- [x] Review Linear issues
- [x] Identify gaps
- [ ] Begin documentation work

### Day 2 (Oct 29, 2025)
- [ ] Complete CHANGELOG.md
- [ ] Create HARDWARE_REQUIREMENTS.md
- [ ] Create MONITORING_GUIDE.md
- [ ] Create PRODUCTION_DEPLOYMENT.md

### Day 3 (Oct 30, 2025)
- [ ] Update README.md
- [ ] Create TESTING_VALIDATION.md
- [ ] Remove development artifacts
- [ ] Final review

### Day 4 (Oct 31, 2025)
- [ ] Set production logging
- [ ] Verification tests
- [ ] Merge to main
- [ ] Tag and release

**Total Timeline**: 4 days

---

## Known Limitations (for Documentation)

### local_only Pipeline

**Hardware Dependency**:
- Requires modern hardware (2020+ CPU or GPU)
- Performance: 24-30s on 2014 CPUs (not practical)
- Performance: 3-7s on 2020+ CPUs (acceptable)
- Performance: 1-2s with GPU (excellent)

**Recommendation**: Use local_hybrid for most deployments

### CLI Tools

**Status**: ✅ Implemented (Go binaries in cli/cmd/agent)
**Commands**: doctor, demo, init, troubleshoot, version
**Build**: `cd cli/cmd/agent && go build -o agent`

### Monitoring

**Optional**: Not required for basic operation
**Deployment**: Separate docker-compose file
**Benefit**: Production observability

---

## Success Criteria

### Must Have (Blocking) ✅

- [x] All 3 pipelines validated and working
- [x] Monitoring infrastructure complete
- [x] Critical bugs fixed (AAVA-28, AAVA-24, AAVA-13)
- [ ] Production logging configured
- [ ] Documentation complete and accurate

### Nice to Have (Non-Blocking) 🟡

- CLI tools (defer to v4.1)
- Config cleanup (defer to v4.1)
- install.sh enhancements (defer to v4.1)

---

## Conclusion

**GA v4.0 Status**: 🟢 **READY FOR RELEASE**

**Remaining Work**: ~6-7 hours documentation  
**Timeline**: 4 days (with testing and review)  
**Confidence**: HIGH ✅

All core functionality validated. Documentation cleanup is final step before merging to main and tagging v4.0.0.

---

**Next Actions**:
1. Begin documentation work (Day 1-2)
2. Complete pre-release checklist (Day 3)
3. Merge to main and release (Day 4)

🎉 **We're at the finish line!**
