# ViciDial Outbound Dialer Integration

**Branch**: `vicidial-integration` (from `main`)
**Customer Server**: `root@reliable365.smartaicalls.com`
**Date Started**: Feb 9, 2026

---

## Problem Statement

AAVA outbound dialer was built and tested exclusively with FreePBX. A community user running ViciDial cannot use the outbound campaign feature because:

1. `from-internal` context does not exist on ViciDial
2. ViciDial requires dial prefixes (e.g. `911`) to route to carrier trunks
3. ViciDial uses `SIP/` (chan_sip) not `PJSIP/` for endpoints
4. FreePBX-specific vars (`AMPUSER`, `FROMEXTEN`) are irrelevant on ViciDial

## Server Investigation (reliable365.smartaicalls.com)

### Environment
- **Asterisk**: 18.26.4-vici (SIP via chan_sip)
- **AAVA**: Deployed (ai_engine, admin_ui, local_ai_server containers running)
- **ARI**: Enabled, port 8088, `asterisk-ai-voice-agent` Stasis app registered
- **Inbound**: Working via `[from-ai-agent]` → `Stasis(asterisk-ai-voice-agent)`
- **Outbound AMD context**: `[aava-outbound-amd]` exists in extensions.conf

### ViciDial Outbound Architecture
- ViciDial originates via **AMI** through `vicidial_manager` MySQL table
- Dial string: `Local/<dial_prefix><phone>@<ext_context>`
- `ext_context` = `default` (from `asterisk.servers` table)
- `dial_prefix` = `911` (from `vicidial_campaigns.dial_prefix`)
- Carrier routes in `[vicidial-auto-external]`:
  - `_911.` → `Dial(SIP/peeredge/723${EXTEN:3})` (INSTACALL CC API)
  - `_912.` → `Dial(SIP/peeredge/723${EXTEN:3})` (INSTACALL static)
- Trunk: `SIP/peeredge` (chan_sip peer to 38.65.82.198)

### Key Differences: FreePBX vs ViciDial

| Feature | FreePBX | ViciDial |
|---|---|---|
| Dial context | `from-internal` | `default` (includes `vicidial-auto-external`) |
| Dial prefix | None | `911`, `912`, etc. (carrier selection) |
| Extension vars | `AMPUSER`, `FROMEXTEN` | Not used |
| Channel tech | PJSIP | SIP (chan_sip) |

## Implementation

### New Environment Variables

| Variable | Default | ViciDial Setting |
|---|---|---|
| `AAVA_OUTBOUND_PBX_TYPE` | `freepbx` | `vicidial` |
| `AAVA_OUTBOUND_DIAL_CONTEXT` | `from-internal` | `default` |
| `AAVA_OUTBOUND_DIAL_PREFIX` | *(empty)* | `911` |
| `AAVA_OUTBOUND_CHANNEL_TECH` | `auto` | `sip` or `local_only` |

### Files Modified

1. **`src/engine.py`**
   - `__init__`: Added 4 new env var reads (lines ~244-248)
   - `_outbound_originate_attempt()`: Docstring updated, AMPUSER/FROMEXTEN gated behind `self._outbound_pbx_type == "freepbx"`
   - `_outbound_choose_endpoint()`: Fully rewritten — configurable context, prefix, multi-tech probing (PJSIP + SIP)

2. **`.env.example`**
   - Added documented entries for all 4 new variables with FreePBX/ViciDial examples

3. **`admin_ui/frontend/src/pages/System/EnvPage.tsx`**
   - Added to known vars list
   - Added 4 new form fields (2x FormSelect, 2x FormInput) in Outbound Campaign section

### Backward Compatibility
- All defaults preserve existing FreePBX behavior
- No changes needed for existing FreePBX users
- Zero-config upgrade path

---

## Deployment & Testing Progress

### ViciDial Server Configuration Needed
```env
AAVA_OUTBOUND_PBX_TYPE=vicidial
AAVA_OUTBOUND_DIAL_CONTEXT=default
AAVA_OUTBOUND_DIAL_PREFIX=911
AAVA_OUTBOUND_CHANNEL_TECH=sip
```

### Test Checklist
- [ ] Push branch to origin
- [ ] Pull on customer server
- [ ] Set env vars in `.env`
- [ ] Rebuild ai_engine container
- [ ] Create test campaign via Admin UI
- [ ] Verify originate log shows: `Local/911<phone>@default`
- [ ] Verify call reaches carrier trunk
- [ ] Verify Stasis handoff after answer (via `[aava-outbound-amd]`)
- [ ] Verify full AI conversation flow
- [ ] Verify FreePBX regression (defaults unchanged)

### Test Results
*(To be filled during testing)*
