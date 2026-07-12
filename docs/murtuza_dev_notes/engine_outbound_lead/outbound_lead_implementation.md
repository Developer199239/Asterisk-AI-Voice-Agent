# outbound_lead — Implementation Notes

> **Branch:** `dev_5_10_26`  
> **Author:** Jalilur Rahman Murtuza  
> **Date:** 2026-07-11  

---

## What This Feature Does

Adds an **outbound lead follow-up** flow alongside the existing `outbound_reminder` flow.  
When triggered via `POST /api/outbound/trigger` with `context=outbound_lead`, the engine:

1. Dials the lead's phone number through Asterisk.
2. Runs AMD (Answering Machine Detection) via the `[sub-amd-check]` subroutine.
3. **If no answer / busy:** Dialplan POSTs `{"leadId":"…","result":"no_answer"}` directly to HOS via `curl`.
4. **If answered (human detected):** Stasis hands off to the AI engine, which starts a Deepgram Voice Agent session under the `outbound_lead` context.
5. **AI talks to person:** At conversation end, AI calls the `update_lead_call_result` in-call tool, which POSTs `{"leadId":"…","result":"answer","interest":"…"}` to HOS.

---

## Files Changed

### 1. `admin_ui/backend/api/outbound_trigger.py`

**What changed:** Added an `outbound_lead` branch inside the `/api/outbound/trigger` POST handler.

Key additions:
- `_outbound_lead_dial_context()` helper reads env var `AAVA_OUTBOUND_LEAD_DIAL_CONTEXT` (default `from-ai-outbound-lead`).
- `lead_id` field added to the request model (required when `context=outbound_lead`).
- Extension format for outbound lead: `{phone_number}_{lead_id}` (e.g. `01700000000_42`).
- `appArgs` encodes: `outbound_lead,patient_name=…|lead_id=…|context=outbound_lead`
- `channelVars` sets: `AI_CONTEXT=outbound_lead`, `LEAD_ID`, `PATIENT_NAME`, `CALL_TYPE`.

```python
# Branch added inside the route handler:
if req.context == "outbound_lead":
    if not req.lead_id:
        raise HTTPException(status_code=422, detail="lead_id is required for outbound_lead")
    _dial_ext = f"{req.phone_number}_{req.lead_id}"
    _data_arg = "|".join([
        f"patient_name={_safe(req.patient_name)}",
        f"lead_id={_safe(req.lead_id)}",
        f"context=outbound_lead",
    ])
    ari_query_params = {
        "endpoint": f"Local/{_dial_ext}@{dial_context}",
        "app": _app_name(),
        "appArgs": f"outbound_lead,{_data_arg}",
        ...
    }
```

---

### 2. `src/engine.py`

Three changes were made here.

#### 2a. `outbound_lead` action handler (~line 2512)

Added after the `outbound_reminder` block. Parses pipe-separated `key=value` pairs from `appArgs[1]`, stores them in `self._outbound_reminder_vars[channel_id]`, sets `AI_CONTEXT` on the channel, then calls `_handle_caller_stasis_start_hybrid`.

```python
if action_type == "outbound_lead":
    logger.info("📞 OUTBOUND LEAD - Routing to caller handler", ...)
    if not hasattr(self, "_outbound_reminder_vars"):
        self._outbound_reminder_vars: dict = {}
    _lead_context_name = "outbound_lead"
    if len(args) > 1 and "=" in args[1]:
        _lead_parsed: dict = {}
        for _kv in args[1].split("|"):
            if "=" in _kv:
                _k, _, _v = _kv.partition("=")
                _lead_parsed[_k.strip()] = _v.strip()
        if _lead_parsed:
            self._outbound_reminder_vars[channel_id] = _lead_parsed
            _lead_context_name = _lead_parsed.get("context", "outbound_lead")
    await self.ari_client.set_channel_var(channel_id, "AI_CONTEXT", _lead_context_name)
    await self._handle_caller_stasis_start_hybrid(channel_id, channel)
    return
```

#### 2b. Seeding fallback (~line 3356)

The seeding block that populates `session.pre_call_results` originally only ran when `ARI GET channel_var(AI_CONTEXT)` returned a value. For `Local/` channels, the ARI GET can return empty, silently skipping the block and leaving `{lead_id}` unresolvable.

**Fix:** Added fallback that reads context from `_outbound_reminder_vars` when `_ai_ctx_now` is empty:

```python
_outbound_context_for_seeding = _ai_ctx_now
if not _outbound_context_for_seeding and hasattr(self, "_outbound_reminder_vars"):
    _outbound_context_for_seeding = (
        self._outbound_reminder_vars.get(caller_channel_id, {}).get("context", "")
    )
```

Also sets `session.context_name` from the fallback when `_ai_ctx_now` was empty.

#### 2c. `outbound_lead_id` seeding (~line 3400)

`_build_prompt_substitutions` pre-fills `"lead_id"` from `session.outbound_lead_id` (built-in key). The loop that reads `pre_call_results` has a guard `if key not in substitutions`, so `pre_call_results["lead_id"]` was being silently skipped — leaving `{lead_id}` as `""` in the prompt even though the value was in `pre_call_results`.

**Fix:** After seeding `pre_call_results`, also populate `session.outbound_lead_id`:

```python
if "lead_id" in _outbound_data and not getattr(session, "outbound_lead_id", None):
    session.outbound_lead_id = _outbound_data["lead_id"]
```

---

### 3. `config/ai-agent.local.yaml`

#### 3a. `outbound_lead` context

Added between `outbound_reminder` and `ivr_main`:

```yaml
outbound_lead:
  greeting: "Hello, may I speak with {patient_name}?"
  prompt: |
    You are Ava … 3-step flow (CONFIRM IDENTITY → INTRODUCE PURPOSE → HANDLE RESPONSE)
    … GENERAL RULES: always call update_lead_call_result before hangup_call …
  profile: telephony_ulaw_8k
  provider: deepgram
  tools:
    - hangup_call
    - transfer
  in_call_http_tools:
    - update_lead_call_result
  post_call_tools:
    - smart_doctor_call_log
```

#### 3b. `update_lead_call_result` in-call tool

Added under `in_call_tools:` (after `update_call_result`):

```yaml
update_lead_call_result:
  kind: in_call_http_lookup
  phase: in_call
  enabled: true
  url: http://168.144.27.225/api/v1/tools/call-result
  method: POST
  headers:
    Content-Type: application/json
    X-Tenant-ID: '1'
    X-API-Key: dev-api-key-replace-in-production
  parameters:
    - name: lead_id
      type: string
      required: true
    - name: interest
      type: string
      required: true
  body_template: '{"leadId": "{lead_id}", "result": "answer", "interest": "{interest}"}'
```

`result` is always `"answer"` (fixed — means the call was connected and the AI spoke to a person).  
`interest` is dynamic: `interested` / `not_interested` / `busy` / `wrong_person` / `voicemail`.

---

### 4. `docs/murtuza_dev_notes/3_extension_custom.conf`

#### 4a. Extension `8001` in `[from-internal-custom]`

For internal testing — dial 8001 to enter the `outbound_lead` context directly:

```asterisk
exten => 8001,1,NoOp(IVR: 8001 -> outbound_lead)
 same => n,Set(AI_CONTEXT=outbound_lead)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent,outbound_lead,context=outbound_lead)
 same => n,Hangup()
```

#### 4b. `[from-ai-outbound-lead]` context

Handles the real outbound dialing. Extension pattern `_X.` matches `{phone}_{lead_id}`:

```asterisk
[from-ai-outbound-lead]
exten => _X.,1,NoOp(AI Outbound Lead Call - exten=${EXTEN})
 same => n,Set(DIAL_NUMBER=${CUT(EXTEN,_,1)})
 same => n,Set(LEAD_ID=${CUT(EXTEN,_,2)})
 same => n,Dial(PJSIP/${DIAL_NUMBER},20,U(sub-amd-check,s,1))
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,Set(CALL_RESULT=${IF($["${DIALSTATUS}"="BUSY"]?busy:no_answer)})
 same => n,Set(IGNORED=${SHELL(curl -s -X POST http://168.144.27.225/api/v1/tools/call-result \
   -H 'Content-Type: application/json' ... --data '{"leadId":"${LEAD_ID}","result":"${CALL_RESULT}"}')})
 same => n(done),Hangup()
```

> **Important:** Each `curl` must be a single unbroken line — Asterisk dialplan does not support backslash line continuation.

The `h` extension (hangup handler) provides a safety net: if the main extension exits unexpectedly without setting `CALL_RESULT`, the handler catches it and posts `no_answer`.

---

## Call Flow Summary

```
POST /api/outbound/trigger
  context=outbound_lead, phone_number, lead_id, patient_name
        │
        ▼
ARI originate → Local/{phone}_{lead_id}@from-ai-outbound-lead
        │
        ├─── ;2 half dials PJSIP/{phone} via AMD subroutine
        │         │
        │    ┌────┴────────────────────────────────────┐
        │    │ No Answer / Busy                        │ Human detected
        │    │                                         │
        │    ▼                                         ▼
        │  curl POST to HOS               Stasis → engine (outbound_lead)
        │  {"leadId":"…",                   Deepgram Voice Agent starts
        │   "result":"no_answer"}              AI talks to person
        │                                         │
        │                                   AI calls update_lead_call_result
        │                                   {"leadId":"…",
        │                                    "result":"answer",
        │                                    "interest":"interested|…"}
        │                                         │
        └─────────────────────────────────────────┘
                                        HOS receives result
```

---

## Bugs Fixed

| # | Symptom | Root Cause | Fix |
|---|---------|------------|-----|
| 1 | No-answer not posting to HOS | Dialplan `curl` used backslash line continuation (invalid in Asterisk) | Rewrote curl as a single line in `[from-ai-outbound-lead]` |
| 2 | `{lead_id}` = `""` in prompt | `_handle_caller_stasis_start_hybrid` seeding block gated on ARI GET returning a non-empty context; Local/ channels can return empty | Added fallback reading context from `_outbound_reminder_vars` cache |
| 3 | `"leadId": ""` in HOS API payload | `_build_prompt_substitutions` pre-fills `"lead_id"` from `session.outbound_lead_id` (None); `pre_call_results["lead_id"]` is then skipped by the `if key not in substitutions` guard | Set `session.outbound_lead_id` from appArgs data in the seeding block |

---

## Reload Checklist

After deploying changes:

```bash
# Rebuild engine (engine.py + config changes)
docker compose up -d --build ai_engine

# Rebuild admin UI (outbound_trigger.py)
docker compose up -d --build admin_ui

# Copy updated dialplan to FreePBX and reload
# (copy 3_extension_custom.conf to /etc/asterisk/extensions_custom.conf or include path)
asterisk -rx "dialplan reload"
```

Optional env var (add to `.env` if using a non-default dial context name):

```
AAVA_OUTBOUND_LEAD_DIAL_CONTEXT=from-ai-outbound-lead
```

---

## API Reference

### Trigger an outbound lead call

```http
POST /api/outbound/trigger
Content-Type: application/json

{
  "context": "outbound_lead",
  "phone_number": "01700000000",
  "lead_id": "42",
  "patient_name": "Md. Jalilur Rahman"
}
```

### HOS result endpoint (called automatically)

```http
POST http://168.144.27.225/api/v1/tools/call-result

# No answer / busy (from dialplan):
{"leadId": "42", "result": "no_answer"}
{"leadId": "42", "result": "busy"}

# Call answered, AI spoke (from in-call tool):
{"leadId": "42", "result": "answer", "interest": "interested"}
{"leadId": "42", "result": "answer", "interest": "not_interested"}
{"leadId": "42", "result": "answer", "interest": "busy"}
{"leadId": "42", "result": "answer", "interest": "wrong_person"}
{"leadId": "42", "result": "answer", "interest": "voicemail"}
```
