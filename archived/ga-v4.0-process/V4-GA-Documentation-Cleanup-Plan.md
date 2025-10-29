# V4 GA Documentation Cleanup Plan (REVISED)

**Purpose**: Prepare clean production documentation while preserving development context  
**Date**: October 29, 2025  
**Strategy**: 
- **develop branch**: Keep all development context for IDE/developers
- **staging/main branch**: Clean production documentation only
- **Local archived/**: Store non-essential docs (added to .gitignore)

**Target**: staging → main merge for v4.0.0

---

## Table of Contents

1. [Strategy Overview](#strategy-overview)
2. [Documentation Audit](#documentation-audit)
3. [Keep in develop - Development Context](#keep-in-develop---development-context)
4. [Archive Locally - Non-Essential](#archive-locally---non-essential)
5. [Production Documentation (for staging/main)](#production-documentation-for-stagingmain)
6. [Create - New for GA v4.0](#create---new-for-ga-v40)
7. [Update - Existing Documents](#update---existing-documents)
8. [Execution Plan](#execution-plan)

---

## Strategy Overview

### Three-Tier Approach

**1. develop Branch (Full Development Context)**
- Keep ALL useful development documentation
- Research documents, design decisions, investigations
- Provides full context for IDE tools (Cursor, Windsurf)
- Enables developers to understand "why" decisions were made

**2. Local archived/ Folder (Non-Essential)**
- Move test logs, RCA documents, obsolete files
- Added to .gitignore (not tracked in git)
- Available locally for reference
- Keeps develop branch clean without losing content

**3. staging/main Branches (Production Only)**
- Cherry-pick production documentation when merging
- Clean, professional documentation
- User-facing guides only
- No development artifacts

### Benefits

✅ **develop**: Developer-friendly with full context  
✅ **Local reference**: Quick access to archived docs  
✅ **Production**: Clean, professional release  
✅ **No data loss**: Everything preserved  

---

## Documentation Audit

### Current Develop Branch: 125 markdown files

**Root Directory**: 25 files  
**docs/**: 45 files  
**docs/plan/**: 5 files  
**docs/milestones/**: 4 files  
**logs/**: 50+ files  
**Other**: 4 files (monitoring, scripts, tests, tools)

---

## Keep in develop - Development Context

### Root Directory (15 documents - KEEP IN DEVELOP)

✅ **README.md** - Main entry point (update for v4.0)  
✅ **CONTRIBUTING.md** - Contribution guidelines  
✅ **V4-GA-MasterPlan.md** - GA v4.0 master plan  
✅ **GA-CODE-CLEANUP.md** - Code cleanup reference  
✅ **GA-CLEANUP-COMPLETE.md** - Cleanup completion report  

✅ **Agents.md** - Provider comparison and selection guide  
✅ **Gemini.md** - Google Gemini integration notes  
✅ **BRIDGE_ARCHITECTURE_VERIFICATION.md** - Bridge architecture validation  
✅ **CONFIG_V4_RELEASE.md** - v4.0 configuration changes  
✅ **GAv4-CHECKLIST.md** - v4.0 development checklist  
✅ **PRODUCTION_HARDENING_PLAN.md** - Production hardening notes  
✅ **ROADMAP_STATUS_20251025.md** - Roadmap status (Oct 25)  
✅ **ROADMAP_STATUS_REVIEW_OCT27.md** - Roadmap review (Oct 27)  
✅ **TESTING_GUIDE_P1.md** - P1 testing guide  
✅ **OPTION3_IMPLEMENTATION_ANALYSIS.md** - Design decision analysis  

**Why keep these?**
- Provide development context
- Explain design decisions
- Help new developers understand "why"
- Useful for Cursor/Windsurf context

### docs/ Directory (28 documents - KEEP IN DEVELOP)

#### Core Documentation (6 files)
✅ **docs/README.md** - Documentation index  
✅ **docs/Architecture.md** - System architecture (UPDATE)  
✅ **docs/INSTALLATION.md** - Installation guide (UPDATE)  
✅ **docs/Configuration-Reference.md** - Config reference (UPDATE)  
✅ **docs/Tuning-Recipes.md** - Performance tuning (UPDATE)  
✅ **docs/FreePBX-Integration-Guide.md** - FreePBX integration  

#### v4.0 Documentation (2 files)
✅ **docs/Transport-Mode-Compatibility.md** - Transport compatibility matrix  
✅ **docs/case-studies/OPENAI_REALTIME_GOLDEN_BASELINE.md** - Golden baseline  

#### Development Research (14 files - VALUABLE CONTEXT)
✅ **docs/AudioSocket with Asterisk_ Technical Summary for A.md** - AudioSocket research  
✅ **docs/AudioSocket-Provider-Alignment.md** - Provider alignment investigation  
✅ **docs/BENCHMARKING-IMPLEMENTATION-SUMMARY.md** - Benchmarking work  
✅ **docs/EXTERNAL_MEDIA_TEST_GUIDE.md** - ExternalMedia testing guide  
✅ **docs/ExternalMedia_Deployment_Guide.md** - ExternalMedia deployment  
✅ **docs/Hybrid-Pipeline-Golden-Baseline.md** - Hybrid pipeline validation  
✅ **docs/LOG_ANALYSIS_VAD_IMPLEMENTATION.md** - VAD analysis  
✅ **docs/OPENAI_FORMAT_DISCOVERY.md** - OpenAI format discovery  
✅ **docs/OpenAI-Realtime-Logging-Guide.md** - Debugging guide  
✅ **docs/Updated-Voice-AI-Stack.md** - Architecture evolution  
✅ **docs/VAD_CRITICAL_FIXES_SUMMARY.md** - VAD fixes summary  
✅ **docs/VAD_IMPLEMENTATION_SUMMARY.md** - VAD implementation  
✅ **docs/call-framework.md** - Call framework design  
✅ **docs/deepgram-agent-api.md** - Deepgram integration notes  

**Why keep these?**
- Explain architectural decisions
- Document investigation process
- Show "why" certain approaches were chosen
- Valuable for troubleshooting similar issues

#### Development Validation (7 files - KEEP)
✅ **docs/baselines/golden/README.md** - Golden baseline overview  
✅ **docs/baselines/golden/deepgram.md** - Deepgram baseline  
✅ **docs/baselines/golden/openai.md** - OpenAI baseline  
✅ **docs/regression/issues/0001-adapter-execution-path.md** - Regression tracking  
✅ **docs/regressions/deepgram-call-framework.md** - Deepgram regression  
✅ **docs/regressions/local-call-framework.md** - Local regression  
✅ **docs/regressions/milestone-7.md** - Milestone 7 regression  
✅ **docs/regressions/openai-call-framework.md** - OpenAI regression  

**Note**: docs/resilience.md is incomplete - move to archived/

### docs/plan/ Directory (5 documents - KEEP IN DEVELOP)

✅ **docs/plan/ROADMAP.md** - Project roadmap (UPDATE - merge ROADMAPv4)  
✅ **docs/plan/ROADMAPv4.md** - v4.0 roadmap (merge into ROADMAP.md)  
✅ **docs/plan/ROADMAPv4-GAP-ANALYSIS.md** - Gap analysis  
✅ **docs/plan/P1_IMPLEMENTATION_PLAN.md** - P1 implementation plan  
✅ **docs/plan/CODE_OF_CONDUCT.md** - Code of conduct  

**Note**: After merging ROADMAPv4 into ROADMAP.md, can archive ROADMAPv4.md

### docs/milestones/ Directory (4 documents - KEEP)

✅ **docs/milestones/milestone-5-streaming-transport.md**  
✅ **docs/milestones/milestone-6-openai-realtime.md**  
✅ **docs/milestones/milestone-7-configurable-pipelines.md**  
✅ **docs/milestones/milestone-8-monitoring-stack.md**  

### docs/local-ai-server/ (1 document - KEEP)

✅ **docs/local-ai-server/PROTOCOL.md** - Local AI server protocol  

### Other Directories (4 documents - KEEP)

✅ **monitoring/README.md** - Monitoring documentation  
✅ **scripts/README.md** - Scripts documentation  
✅ **tests/README.md** - Testing documentation  
✅ **tools/ide/README.md** - IDE tools documentation  

### Total Files to Keep in develop: ~80 files

---

## Archive Locally - Non-Essential

### Root Directory (2 documents)

📦 **DEPRECATED_CODE_AUDIT.md** - Code audit (outdated)  
📦 **OPENAI_*.md** (8 files if any remain) - RCA documents  

### docs/ Directory (2 documents)

📦 **docs/resilience.md** - Incomplete draft  
📦 **docs/Linear-Tracking-Rules.md** - Internal process (not code-related)  

### docs/plan/ Directory (1 document)

📦 **docs/plan/Asterisk AI Voice Agent_ Your Comprehensive Open Source Launch Strategy.md** - Old launch strategy  
📦 **docs/plan/README.md** - Superseded by main docs/README.md  

### logs/ Directory (ALL - 50+ documents)

📦 **logs/remote/rca-*/** - All RCA analysis folders (~44 documents)  
📦 **logs/remote/golden-baseline-telephony-ulaw/** - Golden baseline logs (4 documents)  
📦 **logs/test-call-logs-*.md** - Test call logs (8 documents)  

**Why archive these?**
- Test logs are ephemeral
- RCA documents are historical debugging
- Critical findings already documented in production docs
- Not needed for development context
- Available locally if needed for reference

### Total Files to Archive: ~65 files

### Archive Commands

```bash
# Create archived directory
mkdir -p archived

# Move files to archived/
mv DEPRECATED_CODE_AUDIT.md archived/
mv OPENAI_*.md archived/ 2>/dev/null || true

# Move docs files
mkdir -p archived/docs/plan
mv docs/resilience.md archived/docs/
mv docs/Linear-Tracking-Rules.md archived/docs/
mv "docs/plan/Asterisk AI Voice Agent_ Your Comprehensive Open Source Launch Strategy.md" archived/docs/plan/
mv docs/plan/README.md archived/docs/plan/

# Move entire logs directory
mv logs/ archived/

# Add to .gitignore
echo "" >> .gitignore
echo "# Archived development documentation" >> .gitignore
echo "archived/" >> .gitignore

# Commit
git add .
git commit -m "chore: Archive non-essential documentation

Moved to archived/ folder (not tracked in git):
- Test logs (50+ files)
- RCA documents (44 files)
- Incomplete/obsolete docs (5 files)

Kept in develop:
- All development context
- Research documents
- Design decisions
- Baseline validations

develop branch remains developer-friendly with full context"
```

---

## Production Documentation (for staging/main)

When merging develop → staging → main, **only include these files**:

### Root Directory (3 documents)

✅ README.md (updated for v4.0)  
✅ CONTRIBUTING.md  
✅ CHANGELOG.md (NEW - create)  

### docs/ Directory (11 documents)

✅ docs/README.md  
✅ docs/Architecture.md (updated)  
✅ docs/INSTALLATION.md (updated)  
✅ docs/Configuration-Reference.md (updated)  
✅ docs/Tuning-Recipes.md (updated)  
✅ docs/FreePBX-Integration-Guide.md  
✅ docs/Transport-Mode-Compatibility.md  
✅ docs/case-studies/OPENAI_REALTIME_GOLDEN_BASELINE.md  
✅ docs/case-studies/DEEPGRAM_HYBRID_GOLDEN_BASELINE.md (NEW - create)  
✅ docs/local-ai-server/PROTOCOL.md  
✅ docs/HARDWARE_REQUIREMENTS.md (NEW - create)  
✅ docs/MONITORING_GUIDE.md (NEW - create)  
✅ docs/PRODUCTION_DEPLOYMENT.md (NEW - create)  
✅ docs/TESTING_VALIDATION.md (NEW - create)  

### docs/plan/ (2 documents)

✅ docs/plan/ROADMAP.md (updated with v4.0 completion)  
✅ docs/plan/CODE_OF_CONDUCT.md  

### docs/milestones/ (4 documents)

✅ All milestone documents (historical record)  

### Other (4 documents)

✅ monitoring/README.md  
✅ scripts/README.md  
✅ tests/README.md  
✅ tools/ide/README.md  

**Total Production Files: ~30 documents**

---

## Create - New for GA v4.0

### Root Directory (1 document)

**📝 CHANGELOG.md** (NEW)
- v4.0.0 release notes
- Breaking changes (none)
- New features (pipeline architecture)
- Bug fixes
- Migration guide

### docs/ Directory (4 documents)

**📝 docs/HARDWARE_REQUIREMENTS.md** (NEW)
- Hardware specs for each pipeline
- Performance benchmarks
- CPU vs GPU guidance
- Cost analysis
- local_only requirements

**📝 docs/MONITORING_GUIDE.md** (NEW)
- Prometheus + Grafana setup
- Dashboard descriptions (5 dashboards)
- Alert configuration
- Troubleshooting with metrics
- Production deployment

**📝 docs/PRODUCTION_DEPLOYMENT.md** (NEW)
- Production best practices
- Security hardening
- Backup procedures
- Upgrade process
- Scaling guidance

**📝 docs/TESTING_VALIDATION.md** (NEW)
- Pipeline validation results
- Test call summaries
- Performance metrics
- Known limitations
- Validated configurations

### docs/case-studies/ (1 document)

**📝 docs/case-studies/DEEPGRAM_HYBRID_GOLDEN_BASELINE.md** (NEW)
- Deepgram + OpenAI + Deepgram pipeline
- Performance characteristics
- Golden baseline configuration
- Tuning guidance

---

## Update - Existing Documents

### Root Directory (1 document)

**📝 README.md**
- Update version: v3.0 → v4.0
- Add GA v4.0 badge
- Update feature list:
  - Add: Modular pipeline architecture
  - Add: Production monitoring stack
  - Add: Local + cloud hybrid support
- Update quick start for pipeline selection
- Add links to new docs (hardware requirements, monitoring)

### docs/ Directory (5 documents)

**📝 docs/Architecture.md**
- Add pipeline architecture section
- Document STT → LLM → TTS flow
- Update architecture diagram
- Explain transport layer improvements

**📝 docs/INSTALLATION.md**
- Add monitoring stack setup section
- Document pipeline selection in install.sh
- Add hardware requirements reference
- Update troubleshooting section

**📝 docs/Configuration-Reference.md**
- Document pipeline configuration format
- Remove deprecated settings documentation
- Add transport compatibility reference
- Update examples with v4.0 configs

**📝 docs/Tuning-Recipes.md**
- Add pipeline-specific tuning section
- Document local_only hardware optimization
- Add monitoring integration
- Update performance baselines

**📝 docs/plan/ROADMAP.md**
- Merge ROADMAPv4.md content
- Mark v4.0 as complete ✅
- Document v4.1+ plans (CLI tools, etc.)
- Clean up completed items
- Update timeline

---

## Execution Plan

### Phase 1: Setup archived/ Folder (15 min)

```bash
cd /Users/haider.jarral/Documents/Claude/Asterisk-AI-Voice-Agent

# Create archived structure
mkdir -p archived/docs/plan archived/logs

# Move non-essential files
mv DEPRECATED_CODE_AUDIT.md archived/ 2>/dev/null || true
mv OPENAI_*.md archived/ 2>/dev/null || true
mv docs/resilience.md archived/docs/ 2>/dev/null || true
mv docs/Linear-Tracking-Rules.md archived/docs/ 2>/dev/null || true
mv "docs/plan/Asterisk AI Voice Agent_ Your Comprehensive Open Source Launch Strategy.md" archived/docs/plan/ 2>/dev/null || true
mv docs/plan/README.md archived/docs/plan/ 2>/dev/null || true

# Move logs
mv logs/ archived/ 2>/dev/null || true

# Add to .gitignore
echo "" >> .gitignore
echo "# Archived development documentation" >> .gitignore
echo "archived/" >> .gitignore

# Commit
git add .
git commit -m "chore: Archive non-essential documentation locally

Created archived/ folder for:
- Test logs (50+ files)
- RCA documents (44 files)
- Obsolete/incomplete docs (5 files)

Added archived/ to .gitignore (not tracked in git)

develop branch keeps all useful development context:
- Research documents
- Design decisions
- Validation baselines
- Implementation analysis

Total: ~80 development docs remain in develop"

git push origin develop
```

### Phase 2: Create New Documentation (4 hours)

**Order of creation**:
1. CHANGELOG.md (30 min)
2. docs/HARDWARE_REQUIREMENTS.md (1 hour)
3. docs/MONITORING_GUIDE.md (1 hour)
4. docs/PRODUCTION_DEPLOYMENT.md (1 hour)
5. docs/TESTING_VALIDATION.md (30 min)
6. docs/case-studies/DEEPGRAM_HYBRID_GOLDEN_BASELINE.md (30 min - from notes)

### Phase 3: Update Existing Documentation (2 hours)

**Order of updates**:
1. README.md (30 min)
2. docs/Architecture.md (30 min)
3. docs/INSTALLATION.md (30 min)
4. docs/Configuration-Reference.md (15 min)
5. docs/Tuning-Recipes.md (15 min)

### Phase 4: Merge ROADMAP (30 min)

1. Merge ROADMAPv4.md content into docs/plan/ROADMAP.md
2. Mark v4.0 complete
3. Document v4.1+ plans
4. Move ROADMAPv4.md to archived/docs/plan/

### Phase 5: Final Review (1 hour)

- [ ] Check all links work
- [ ] Verify no broken references
- [ ] Review for consistency
- [ ] Check formatting
- [ ] Test examples
- [ ] Verify .gitignore working

### Phase 6: Commit and Push (5 min)

```bash
git add .
git commit -m "docs: Complete GA v4.0 documentation

Created (6 new):
- CHANGELOG.md
- docs/HARDWARE_REQUIREMENTS.md
- docs/MONITORING_GUIDE.md
- docs/PRODUCTION_DEPLOYMENT.md
- docs/TESTING_VALIDATION.md
- docs/case-studies/DEEPGRAM_HYBRID_GOLDEN_BASELINE.md

Updated (6 documents):
- README.md (v4.0)
- docs/Architecture.md
- docs/INSTALLATION.md
- docs/Configuration-Reference.md
- docs/Tuning-Recipes.md
- docs/plan/ROADMAP.md

Status: develop branch ready with full context
Ready: Production docs ready for staging/main merge"

git push origin develop
```

---

## Summary

### Files by Action

| Action | Count | Location | Tracked in Git |
|--------|-------|----------|----------------|
| **Keep in develop** | ~80 files | develop branch | ✅ Yes |
| **Archive locally** | ~65 files | archived/ folder | ❌ No (.gitignore) |
| **Create new** | 6 files | develop branch | ✅ Yes |
| **Update** | 6 files | develop branch | ✅ Yes |
| **For production** | ~30 files | staging/main (cherry-pick) | ✅ Yes |

### Three-Tier Structure

**develop Branch** (~86 files):
- Full development context
- Research and design decisions
- Implementation analysis
- Baseline validations
- All useful documentation
- Perfect for IDE tools (Cursor, Windsurf)

**Local archived/** (~65 files):
- Test logs
- RCA documents
- Obsolete docs
- Not tracked in git
- Available for reference

**staging/main Branches** (~30 files):
- Production documentation only
- User-facing guides
- Clean, professional
- No development artifacts

### Timeline

| Phase | Task | Time |
|-------|------|------|
| **Phase 1** | Setup archived/ folder | 15 min |
| **Phase 2** | Create new docs (6 files) | 4 hours |
| **Phase 3** | Update existing (6 files) | 2 hours |
| **Phase 4** | Merge ROADMAP | 30 min |
| **Phase 5** | Final review | 1 hour |
| **Phase 6** | Commit and push | 5 min |
| **Total** | | **~8 hours** |

---

## Validation Checklist

Before merge to staging:

- [ ] archived/ folder created with correct files
- [ ] archived/ added to .gitignore
- [ ] All new documentation created
- [ ] All existing documentation updated
- [ ] All links verified
- [ ] Examples tested
- [ ] Formatting consistent
- [ ] No broken references
- [ ] develop branch has full context
- [ ] Production docs identified

---

## Benefits of This Approach

✅ **develop branch**: Full development context for IDE tools  
✅ **Local archived/**: Quick reference without git clutter  
✅ **Production clean**: Professional staging/main branches  
✅ **No data loss**: Everything preserved  
✅ **Developer friendly**: New developers get full context  
✅ **Production ready**: Clean merge to staging/main  

---

**Status**: 🟢 READY TO EXECUTE  
**Timeline**: 8 hours total  
**Risk**: Low (all changes reversible, archived locally)  
**Impact**: Developer-friendly develop + clean production release
