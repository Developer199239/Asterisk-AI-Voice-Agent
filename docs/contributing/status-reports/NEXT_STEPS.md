# Next Steps - Documentation Consolidation

**Quick Reference** | Full details: `2025-11-19-documentation-audit.md`

## Summary of Issues Found

### 🔴 Critical (Must Fix)

1. **3 Redundant Docs** - DELETE after consolidation:
   - `docs/ASTERISK_QUEUE_SETUP.md` → Merge into `FreePBX-Integration-Guide.md`
   - `docs/CLI_TOOLS_GUIDE.md` → Merge into `cli/README.md`
   - `docs/ExternalMedia_Deployment_Guide.md` → Merge into `PRODUCTION_DEPLOYMENT.md`

2. **Provider Setup Inconsistencies**:
   - ❌ `deepgram-agent-api.md` → WRONG NAME, should be in `/contributing/references/`
   - ❌ Missing: `Provider-Deepgram-Setup.md` (user-facing)
   - ❌ Missing: `Provider-OpenAI-Setup.md` (user-facing)

3. **Outdated Information**:
   - `TOOL_CALLING_GUIDE.md` says pipelines "Planned" - Actually PRODUCTION ✅ (AAVA-85)

## Action Plan (7 Tasks)

### Task 1: Consolidate Queue Setup ⏱️ 45 min
- Merge `ASTERISK_QUEUE_SETUP.md` → `FreePBX-Integration-Guide.md`
- Add as Section 6: "Queue Setup for Call Transfers"
- Delete original file

### Task 2: Consolidate CLI Tools ⏱️ 60 min
- Merge `CLI_TOOLS_GUIDE.md` → `cli/README.md`
- Update references in TROUBLESHOOTING_GUIDE.md
- Delete original file

### Task 3: Consolidate ExternalMedia ⏱️ 30 min
- Merge `ExternalMedia_Deployment_Guide.md` → `PRODUCTION_DEPLOYMENT.md`
- Add as Section: "Audio Transport Configuration"
- Delete original file

### Task 4: Move API Reference ⏱️ 5 min
```bash
mv docs/deepgram-agent-api.md docs/contributing/references/Provider-Deepgram-API-Reference.md
```

### Task 5: Create Provider-Deepgram-Setup.md ⏱️ 60 min
- Extract from `case-studies/Deepgram-Agent-Golden-Baseline.md`
- Format: API keys, config, dialplan, testing
- Mirror `Provider-Google-Setup.md` structure

### Task 6: Create Provider-OpenAI-Setup.md ⏱️ 60 min
- Extract from `case-studies/OpenAI-Realtime-Golden-Baseline.md`
- **Include critical VAD setting**: `webrtc_aggressiveness: 1`
- Format: API keys, config, dialplan, testing, troubleshooting

### Task 7: Update TOOL_CALLING_GUIDE.md ⏱️ 30 min
- Line 51: Change "Planned" → "✅ Full Support (Nov 19, 2025)"
- Add new section on local_hybrid pipeline tool execution
- Reference AAVA-85 implementation

**Total Estimated Time**: 5 hours

## Decisions Needed

### Question 1: Provider Setup Guides
How should I create Provider-Deepgram-Setup.md and Provider-OpenAI-Setup.md?

- **Option A** (Recommended): Extract from case studies, create user-friendly versions
- **Option B**: You'll create manually later
- **Option C**: Create minimal placeholders now

**My Recommendation**: Option A - I can extract the key setup steps right now

### Question 2: Markdown Lint
~150 lint warnings across new docs (blank lines, code fences). Fix now or defer?

- **Fix Now**: 30-60 min, clean codebase
- **Defer**: Focus on content, batch fix later

**My Recommendation**: Defer - content is more important

### Question 3: Implementation Order
Proceed with all 7 tasks now, or phase it?

- **All Now**: 5 hours, complete cleanup
- **Phase 1 First**: Tasks 1-4 (consolidations + move), then review
- **User Review First**: No changes until approved

**My Recommendation**: Phase 1 first (2 hours), get your feedback, then Phase 2

## Files Ready to View

Before proceeding, you may want to review:

- ✅ Full audit: `2025-11-19-documentation-audit.md` (this folder)
- ✅ Current structure: `docs/contributing/README.md`
- ✅ New provider impl docs: `contributing/references/Provider-*-Implementation.md`

## Quick Start (If Approved)

```bash
# I'll execute these commands in sequence:

# Task 1-3: Consolidations (edit files, then delete)
# Task 4: Move deepgram API reference
# Task 5-6: Create provider setup guides
# Task 7: Update tool calling guide

# Then commit:
git add -A
git commit -m "docs: Consolidate redundant documentation

- Merged queue setup into FreePBX guide
- Merged CLI tools into cli/README.md
- Merged ExternalMedia into PRODUCTION_DEPLOYMENT.md
- Moved deepgram-agent-api.md to proper location
- Created Provider-Deepgram-Setup.md
- Created Provider-OpenAI-Setup.md
- Updated TOOL_CALLING_GUIDE.md with pipeline support"
git push origin develop
```

---

**Awaiting Your Decision** 🎯

Reply with:
1. Approve all 7 tasks? (Yes/No/Modify)
2. Provider setup approach? (A/B/C)
3. Markdown lint priority? (Now/Defer)

Or just say "proceed" and I'll use recommended options!
