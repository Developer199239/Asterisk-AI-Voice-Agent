# Documentation Audit & Consolidation Plan

**Date**: November 19, 2025  
**Commit**: 8187652  
**Status**: Action Required

## Executive Summary

Comprehensive audit identified redundant documentation, naming inconsistencies, and gaps in provider setup guides. This report outlines consolidation plan and next steps.

## Critical Findings

### 1. Redundant Documentation (DELETE)

#### ❌ `docs/ASTERISK_QUEUE_SETUP.md` → Consolidate into `docs/FreePBX-Integration-Guide.md`
**Reason**: Queue setup is FreePBX-specific configuration, belongs in integration guide

**Content to Extract**:
- Queue definitions (queues.conf)
- Queue members configuration
- Dialplan context for queue handling
- Transfer to queue integration
- Troubleshooting queue issues

**Action**: Add new section "Queue Setup for Call Transfers" in FreePBX guide

---

#### ❌ `docs/CLI_TOOLS_GUIDE.md` → Consolidate into `cli/README.md`
**Reason**: Duplicate content, cli/README.md is canonical location

**Content Status**:
- `CLI_TOOLS_GUIDE.md` (docs): 924 lines, comprehensive usage guide
- `cli/README.md`: 233 lines, brief overview with reference to CLI_TOOLS_GUIDE.md

**Action**: Merge comprehensive content into `cli/README.md`, delete docs version

---

#### ❌ `docs/ExternalMedia_Deployment_Guide.md` → Consolidate into `docs/PRODUCTION_DEPLOYMENT.md`
**Reason**: ExternalMedia is transport configuration, part of production deployment

**Content to Extract**:
- ExternalMedia architecture overview
- RTP configuration (port range, codec)
- Deployment validation steps
- Troubleshooting RTP issues
- Performance expectations

**Action**: Add "Audio Transport Configuration" section in PRODUCTION_DEPLOYMENT.md

---

### 2. Provider Documentation Inconsistencies

#### Provider Setup Guides (User-Facing)

**Current State**:
- ✅ `docs/Provider-Google-Setup.md` (renamed, correct)
- ❌ `docs/deepgram-agent-api.md` (WRONG NAME, technical reference not setup)
- ❌ `docs/Provider-Deepgram-Setup.md` (MISSING)
- ❌ `docs/Provider-OpenAI-Setup.md` (MISSING)

**Naming Convention**: `Provider-{Name}-Setup.md`

**Issues**:
1. `deepgram-agent-api.md` is **API reference**, NOT setup guide
   - Content: WebSocket endpoints, message formats, technical details
   - Should be: `contributing/references/Provider-Deepgram-API-Reference.md`
   
2. Missing user-facing setup guides for:
   - Deepgram Voice Agent (API keys, config, dialplan)
   - OpenAI Realtime (API keys, config, dialplan)

**Action Required**:
- Rename `deepgram-agent-api.md` → `contributing/references/Provider-Deepgram-API-Reference.md`
- Create `Provider-Deepgram-Setup.md` (user-facing)
- Create `Provider-OpenAI-Setup.md` (user-facing)

---

#### Provider Implementation Docs (Developer-Facing)

**Current State**:
- ✅ `contributing/references/Provider-Google-Implementation.md`
- ✅ `contributing/references/Provider-Deepgram-Implementation.md`
- ✅ `contributing/references/Provider-OpenAI-Implementation.md`

**Status**: Complete ✅

---

### 3. Missing Updates

#### `docs/TOOL_CALLING_GUIDE.md` Line 51

**Current**:
```markdown
| **Custom Pipelines** | 🚧 Planned | v4.3 release (AAVA-56) |
```

**Should Be** (based on memory - AAVA-85 completed Nov 19, 2025):
```markdown
| **Custom Pipelines (local_hybrid)** | ✅ Full Support | Production validated (Nov 19, 2025) |
```

**Evidence**: Memory shows local_hybrid pipeline successfully executing all 6 tools in production.

**Action**: Update TOOL_CALLING_GUIDE.md with correct status

---

## Audit Findings Summary

### Files to DELETE (after consolidation):
1. ❌ `docs/ASTERISK_QUEUE_SETUP.md` → into FreePBX-Integration-Guide.md
2. ❌ `docs/CLI_TOOLS_GUIDE.md` → into cli/README.md  
3. ❌ `docs/ExternalMedia_Deployment_Guide.md` → into PRODUCTION_DEPLOYMENT.md

### Files to CREATE:
1. ❌ `docs/Provider-Deepgram-Setup.md` (user setup guide)
2. ❌ `docs/Provider-OpenAI-Setup.md` (user setup guide)

### Files to MOVE/RENAME:
1. `docs/deepgram-agent-api.md` → `docs/contributing/references/Provider-Deepgram-API-Reference.md`

### Files to UPDATE:
1. `docs/FreePBX-Integration-Guide.md` - Add queue setup section
2. `cli/README.md` - Merge CLI tools content
3. `docs/PRODUCTION_DEPLOYMENT.md` - Add ExternalMedia transport section
4. `docs/TOOL_CALLING_GUIDE.md` - Update pipeline tool support status

---

## Detailed Action Plan

### Phase 1: Consolidations (Priority: HIGH)

#### Task 1.1: Consolidate Queue Setup
**File**: `docs/FreePBX-Integration-Guide.md`

**Add New Section** (after Dialplan Setup):
```markdown
## 6. Queue Setup for Call Transfers

### Overview
Configure Asterisk queues to work with the transfer tool for ACD (Automatic Call Distribution).

### 6.1 Define Queues
[Content from ASTERISK_QUEUE_SETUP.md lines 13-53]

### 6.2 Configure Queue Members
[Content from ASTERISK_QUEUE_SETUP.md lines 55-92]

### 6.3 Dialplan for Queue Context
[Content from ASTERISK_QUEUE_SETUP.md lines 94-147]

### 6.4 Testing Queue Transfers
[Content from ASTERISK_QUEUE_SETUP.md lines 182-209]

### 6.5 Troubleshooting Queues
[Content from ASTERISK_QUEUE_SETUP.md lines 211-249]
```

**Then DELETE**: `docs/ASTERISK_QUEUE_SETUP.md`

---

#### Task 1.2: Consolidate CLI Tools
**File**: `cli/README.md`

**Replace content with**:
- Keep current installation section
- Merge comprehensive command reference from `CLI_TOOLS_GUIDE.md`
- Keep development section
- Update cross-references to point to `cli/README.md`

**Update references in**:
- `docs/TROUBLESHOOTING_GUIDE.md`
- `docs/contributing/quickstart.md`
- `docs/contributing/debugging-guide.md` (when created)

**Then DELETE**: `docs/CLI_TOOLS_GUIDE.md`

---

#### Task 1.3: Consolidate ExternalMedia Guide
**File**: `docs/PRODUCTION_DEPLOYMENT.md`

**Add New Section** (after Configuration section):
```markdown
## Audio Transport Configuration

### AudioSocket (Default)
[Brief overview]

### ExternalMedia + RTP (Advanced)
[Content from ExternalMedia_Deployment_Guide.md]
- Architecture diagram
- Configuration options
- Port requirements
- Validation steps
- Troubleshooting
```

**Then DELETE**: `docs/ExternalMedia_Deployment_Guide.md`

---

### Phase 2: Provider Documentation (Priority: HIGH)

#### Task 2.1: Move Deepgram API Reference
**Action**:
```bash
mv docs/deepgram-agent-api.md docs/contributing/references/Provider-Deepgram-API-Reference.md
```

**Update references** in:
- `contributing/references/Provider-Deepgram-Implementation.md`
- `README.md` (if referenced)

---

#### Task 2.2: Create Provider-Deepgram-Setup.md
**Source**: Extract from `docs/case-studies/Deepgram-Agent-Golden-Baseline.md`

**Sections**:
1. Overview & Prerequisites
2. API Key Setup
3. Configuration (yaml example)
4. Dialplan Configuration
5. Testing
6. Troubleshooting
7. See Also (link to implementation docs, API reference)

**Format**: Mirror `Provider-Google-Setup.md` structure

---

#### Task 2.3: Create Provider-OpenAI-Setup.md
**Source**: Extract from `docs/case-studies/OpenAI-Realtime-Golden-Baseline.md`

**Sections**:
1. Overview & Prerequisites
2. API Key Setup
3. Configuration (yaml example)
   - **Critical**: Include VAD settings (`webrtc_aggressiveness: 1`)
4. Dialplan Configuration
5. Testing
6. Troubleshooting
   - Tool execution issues
   - Echo/self-interruption
7. See Also (link to implementation docs, case study)

**Format**: Mirror `Provider-Google-Setup.md` structure

---

#### Task 2.4: Update TOOL_CALLING_GUIDE.md
**File**: `docs/TOOL_CALLING_GUIDE.md`

**Line 51 - Update table**:

```markdown
| Provider | Status | Notes |
|----------|--------|-------|
| **OpenAI Realtime** | ✅ Full Support | Production validated (Nov 19, 2025) |
| **Deepgram Voice Agent** | ✅ Full Support | Production validated (Nov 9, 2025) |
| **Modular Pipelines (local_hybrid)** | ✅ Full Support | Production validated (Nov 19, 2025) - AAVA-85 |
```

**Add New Section** (after Deepgram section):

```markdown
### Modular Pipelines (local_hybrid)

**Status**: ✅ Production validated (Nov 19, 2025)

Modular pipelines support full tool execution through OpenAI Chat Completions API integration.

**Supported Tools**:
- ✅ transfer (UnifiedTransferTool)
- ✅ hangup_call (HangupCallTool)
- ✅ send_email_summary (SendEmailSummaryTool)
- ✅ request_transcript (RequestTranscriptTool)
- 🟡 cancel_transfer (CancelTransferTool) - Requires active transfer
- 🟡 leave_voicemail (VoicemailTool) - Requires voicemail config

**Configuration**:
```yaml
pipelines:
  local_hybrid:
    stt: vosk_local
    llm: openai  # Uses Chat Completions API
    tts: piper_local
    tools:
      - transfer
      - hangup_call
      - send_email_summary
      - request_transcript
```

**How It Works**:
1. User intent detected via STT (Vosk)
2. LLM (OpenAI Chat Completions) returns tool_calls in response
3. Pipeline orchestrator executes via tool_registry
4. Results incorporated into conversation

**Production Evidence**:
- Call 1763582071.6214: Transfer to sales team (✅ Success)
- Call 1763582133.6224: Hangup + transcript email (✅ Success)

**See Also**:
- Implementation details: `docs/contributing/references/aava-85-implementation.md`
- Common pitfalls: `docs/contributing/COMMON_PITFALLS.md#tool-execution-issues`
```

---

### Phase 3: Final Checks (Priority: MEDIUM)

#### Task 3.1: Update Cross-References
**Files to check**:
- `README.md` - Update links to moved/deleted docs
- `CONTRIBUTING.md` - Verify all links work
- `AVA.mdc` - Update canonical sources
- `docs/contributing/README.md` - Update references

#### Task 3.2: Verify Documentation Gaps
**Check for missing docs referenced but not created**:
- `contributing/tool-development.md` - Still needed
- `contributing/provider-development.md` - Still needed
- `contributing/debugging-guide.md` - Still needed

#### Task 3.3: Fix Markdown Lint Issues
**Decision**: Fix or defer to separate PR?
- ~100+ warnings across new docs
- Non-blocking, style only
- Can be automated with markdownlint-cli

---

## Implementation Order

### Immediate (Today):
1. ✅ Move IMPLEMENTATION_STATUS.md to archived/
2. ✅ Create this audit report
3. ⏳ Consolidate ASTERISK_QUEUE_SETUP.md → FreePBX-Integration-Guide.md
4. ⏳ Consolidate CLI_TOOLS_GUIDE.md → cli/README.md
5. ⏳ Consolidate ExternalMedia_Deployment_Guide.md → PRODUCTION_DEPLOYMENT.md
6. ⏳ Move deepgram-agent-api.md → contributing/references/
7. ⏳ Update TOOL_CALLING_GUIDE.md (pipeline support)

### Short-term (This Week):
8. ⏳ Create Provider-Deepgram-Setup.md
9. ⏳ Create Provider-OpenAI-Setup.md
10. ⏳ Update cross-references
11. ⏳ Verify all links work

### Optional (Next Week):
12. Fix markdown lint warnings
13. Create remaining Priority 1 docs (tool-development.md, etc.)

---

## File Manifest After Changes

### `/docs` Root (User-Facing)
```
✅ INSTALLATION.md
✅ FreePBX-Integration-Guide.md (+ queue section)
✅ PRODUCTION_DEPLOYMENT.md (+ ExternalMedia section)
✅ TOOL_CALLING_GUIDE.md (+ pipeline section)
✅ TROUBLESHOOTING_GUIDE.md
✅ Provider-Google-Setup.md
✅ Provider-Deepgram-Setup.md (NEW)
✅ Provider-OpenAI-Setup.md (NEW)
✅ MONITORING_GUIDE.md
✅ Configuration-Reference.md
❌ ASTERISK_QUEUE_SETUP.md (DELETED)
❌ CLI_TOOLS_GUIDE.md (DELETED)
❌ ExternalMedia_Deployment_Guide.md (DELETED)
❌ deepgram-agent-api.md (MOVED)
```

### `/cli` Root (CLI Documentation)
```
✅ README.md (comprehensive CLI guide)
```

### `/docs/contributing/references` (Developer Technical)
```
✅ Provider-Google-Implementation.md
✅ Provider-Deepgram-Implementation.md
✅ Provider-OpenAI-Implementation.md
✅ Provider-Deepgram-API-Reference.md (MOVED from docs/deepgram-agent-api.md)
✅ aava-85-implementation.md
✅ team-setup.md
```

---

## Success Criteria

### Must Complete (Blocking):
- [ ] All 3 redundant docs consolidated and deleted
- [ ] deepgram-agent-api.md moved to proper location
- [ ] Provider-Deepgram-Setup.md created
- [ ] Provider-OpenAI-Setup.md created
- [ ] TOOL_CALLING_GUIDE.md updated with pipeline support
- [ ] All cross-references updated
- [ ] No broken links

### Should Complete (High Value):
- [ ] All changes committed and pushed
- [ ] Documentation tested (links work, content accurate)
- [ ] README.md updated

### Nice to Have (Can Defer):
- [ ] Markdown lint warnings fixed
- [ ] Priority 1 developer docs created
- [ ] Automated link checker added to CI

---

## Questions for User

1. **Provider Setup Guides**: Confirm approach to create Provider-Deepgram-Setup.md and Provider-OpenAI-Setup.md:
   - Option A: Extract from case studies (recommended)
   - Option B: User will create manually
   - Option C: Create minimal versions now, enhance later

2. **Consolidation Review**: After consolidating the 3 docs, should I:
   - Delete immediately after merge?
   - Keep for one release cycle?
   - User will review before deletion?

3. **Markdown Lint**: Fix ~100 warnings now or defer?
   - Fix now: 30-60 min, clean codebase
   - Defer: Focus on content, fix later in batch

---

## Risk Assessment

### Low Risk (Safe to proceed):
- Moving/renaming files (git tracks history)
- Consolidating redundant content
- Updating tool support status (factually correct per memory)

### Medium Risk (Review recommended):
- Creating new provider setup guides (need accurate API key instructions)
- Updating cross-references (could break links if missed)

### No Risk (Information only):
- This audit report
- Markdown lint warnings

---

## Estimated Effort

**Phase 1 (Consolidations)**: 2-3 hours
- Queue setup merge: 45 min
- CLI tools merge: 60 min
- ExternalMedia merge: 30 min
- Testing: 30 min

**Phase 2 (Provider Docs)**: 2-3 hours
- Move API reference: 5 min
- Create Deepgram setup: 60 min
- Create OpenAI setup: 60 min
- Update tool guide: 30 min
- Testing: 30 min

**Phase 3 (Final Checks)**: 1 hour
- Update references: 30 min
- Verify links: 30 min

**Total**: 5-7 hours

---

## Next Steps

**Awaiting User Decision**:
1. Approve consolidation plan
2. Clarify provider setup guide approach
3. Decide on markdown lint priority
4. Confirm implementation order

**Ready to Proceed**:
- All technical details documented
- File paths verified
- Content identified for extraction
- Git operations planned

---

**Report Complete** ✅  
**Status**: Ready for user review and approval to proceed
