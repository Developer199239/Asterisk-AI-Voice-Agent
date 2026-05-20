# Outbound Call System — Developer Guide

**Author:** Murtuza  
**Date:** 2026-05-20  
**Status:** Production (working)

---

## Table of Contents

1. [Overview](#1-overview)
2. [End-to-End Flow](#2-end-to-end-flow)
3. [How It Works — Step by Step](#3-how-it-works--step-by-step)
4. [The Root-Cause Bug and Fix](#4-the-root-cause-bug-and-fix)
5. [Current Contexts](#5-current-contexts)
6. [How to Add a New Outbound Context](#6-how-to-add-a-new-outbound-context)
7. [Files Reference](#7-files-reference)
8. [API Reference](#8-api-reference)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Overview

The outbound call system allows the HOS backend (Java Spring Boot) to trigger an AI-powered
phone call to a patient using Ava (Deepgram Voice Agent). The call is initiated by the HOS
scheduler and handled entirely by the AI engine — no human operator is involved.

**Use cases:**
- Appointment reminders (1 hour before appointment) → context: `outbound_reminder`
- Post-visit feedback collection → context: `outbound_feedback` *(example)*
- Any future outbound scenario you define

**Authentication:** Shared API key (`X-Api-Key` header). No JWT required.  
**Port:** Admin UI on `:3003` (same port used for the dashboard).

---

## 2. End-to-End Flow

```
HOS Backend (Java Scheduler)
        │
        │  POST http://<AI_ENGINE_IP>:3003/api/outbound/trigger
        │  X-Api-Key: <OUTBOUND_TRIGGER_API_KEY>
        │  { "phone_number": "6000", "patient_name": "Ahmed Khan",
        │    "context": "outbound_reminder", ... }
        │
        ▼
Admin UI  (outbound_trigger.py)
        │
        ├─ 1. Validate API key
        ├─ 2. POST /ari/channels  → Asterisk ARI
        │      endpoint = Local/6000@from-internal
        │      app      = asterisk-ai-voice-agent
        │      appArgs  = outbound_reminder
        │      timeout  = 60
        │
        ├─ 3. Receive channel_id from ARI
        │
        └─ 4. POST /ari/channels/{id}/variable  (8 times, in parallel)
               AI_CONTEXT=outbound_reminder
               PATIENT_NAME=Ahmed Khan
               PATIENT_ID=42
               APPOINTMENT_ID=101
               DOCTOR_NAME=Dr. Hina Farooqi
               APPOINTMENT_DATE=2026-05-20
               START_TIME=09:00
               CALL_TYPE=outbound_reminder

Asterisk
        │
        ├─ Creates Local channel pair:
        │   Local/6000;1  →  enters Stasis app  (AI engine audio side)
        │   Local/6000;2  →  from-internal dialplan  →  rings extension 6000
        │
        └─ StasisStart event (WebSocket) fires on Local/6000;1
               args = ['outbound_reminder']

AI Engine  (engine.py)
        │
        ├─ _handle_stasis_start()
        │   args[0] = 'outbound_reminder'
        │   ↓
        │   SET AI_CONTEXT=outbound_reminder on channel  ← critical fix
        │   ↓
        │   _handle_caller_stasis_start_hybrid()
        │       ↓
        │       Creates session, bridge, AudioSocket
        │       Reads CALL_TYPE from channel  → "outbound_reminder"
        │       Pre-seeds session.pre_call_results = {
        │           patient_name, patient_id, appointment_id,
        │           doctor_name, appointment_date, start_time
        │       }
        │       ↓
        │       _resolve_audio_profile()
        │           Reads AI_CONTEXT  → "outbound_reminder"  ✅
        │           session.context_name = "outbound_reminder"
        │       ↓
        │       _ensure_provider_session_started()
        │           Gets outbound_reminder context from ai-agent.local.yaml
        │           Substitutes template vars:
        │               {patient_name}    → "Ahmed Khan"
        │               {doctor_name}     → "Dr. Hina Farooqi"
        │               {appointment_date}→ "2026-05-20"
        │               {start_time}      → "09:00"
        │           Sends Settings to Deepgram with outbound_reminder prompt
        │
        ▼
Deepgram Voice Agent
        Greeting: "Hello, may I speak with Ahmed Khan?"
        Ava handles: confirm / cancel / reschedule
        Uses tools: cancel_appointment, reschedule_appointment, hangup_call
```

---

## 3. How It Works — Step by Step

### Step A — HOS Backend triggers the call

The Java scheduler calls the trigger endpoint 1 hour before the appointment:

```http
POST http://192.168.0.170:3003/api/outbound/trigger
X-Api-Key: your-strong-random-key
Content-Type: application/json

{
  "phone_number":    "6000",
  "patient_id":      "42",
  "patient_name":    "Ahmed Khan",
  "appointment_id":  "101",
  "doctor_name":     "Dr. Hina Farooqi",
  "appointment_date":"2026-05-20",
  "start_time":      "09:00",
  "context":         "outbound_reminder",
  "caller_id":       "Smart Doctor Clinic"
}
```

### Step B — Admin UI originates the Asterisk call

`outbound_trigger.py` calls Asterisk ARI:

```
POST http://asterisk:8088/ari/channels
  ?endpoint=Local/6000@from-internal
  &app=asterisk-ai-voice-agent
  &appArgs=outbound_reminder        ← becomes args[0] in StasisStart
  &timeout=60
  &callerId=Smart Doctor Clinic
Body: { "channelVars": { ... } }    ← NOTE: not reliably readable on Local channels
                                       but we SET them explicitly in the next step
```

### Step C — Admin UI explicitly SETs channel variables

Immediately after getting `channel_id`, `outbound_trigger.py` makes 8 parallel ARI requests:

```
POST /ari/channels/{channel_id}/variable?variable=AI_CONTEXT&value=outbound_reminder
POST /ari/channels/{channel_id}/variable?variable=CALL_TYPE&value=outbound_reminder
POST /ari/channels/{channel_id}/variable?variable=PATIENT_NAME&value=Ahmed+Khan
... (5 more vars)
```

This is necessary because `channelVars` in the originate body are **not readable** via
`GET /variable` on Local channels — known Asterisk limitation. The explicit SET calls use
the write API (`POST`), which IS readable by subsequent GET requests.

### Step D — Engine receives StasisStart and sets AI_CONTEXT itself

When Asterisk fires the StasisStart event, the engine sees `args[0] = 'outbound_reminder'`
and IMMEDIATELY sets `AI_CONTEXT` on the channel before doing anything else:

```python
# engine.py — _handle_stasis_start()
if action_type == "outbound_reminder":
    await self.ari_client.set_channel_var(channel_id, "AI_CONTEXT", "outbound_reminder")
    await self._handle_caller_stasis_start_hybrid(channel_id, channel)
```

This is the **critical reliability fix**: even if the admin_ui SET calls haven't arrived yet
(timing edge case), the engine guarantees AI_CONTEXT is set before `_resolve_audio_profile`
reads it ~130 ms later.

### Step E — Engine builds the prompt with patient data

`_handle_caller_stasis_start_hybrid` reads the patient variables from the channel
(set by admin_ui in Step C) and stores them as `session.pre_call_results`:

```python
{
    "patient_name":     "Ahmed Khan",
    "patient_id":       "42",
    "appointment_id":   "101",
    "doctor_name":      "Dr. Hina Farooqi",
    "appointment_date": "2026-05-20",
    "start_time":       "09:00",
}
```

These substitute `{patient_name}`, `{doctor_name}` etc. in the context's prompt and greeting.

### Step F — Deepgram gets the correct context

`_ensure_provider_session_started` loads the `outbound_reminder` context from
`config/ai-agent.local.yaml`, substitutes all template variables, and sends the final
prompt + greeting to Deepgram. Ava greets the patient and handles the conversation.

---

## 4. The Root-Cause Bug and Fix

### The bug

```
Problem: All ARI GET /channels/{id}/variable requests return 404 for Local/ channels.

This means:
  - channelVars set in the ARI originate body → NOT readable
  - Any GET request for AI_CONTEXT, AI_PROVIDER, etc. → 404 (not set)
  - session.context_name → stays empty
  - Wrong prompt (default "You are Asterisk Agent...") is sent to Deepgram
```

### Why it happens

Asterisk creates a Local channel pair (`Local/6000;1` and `Local/6000;2`). The `channelVars`
from the ARI originate body are stored internally but the `Local;1` channel (which enters
Stasis) does not expose them through the ARI REST API. This is a known Asterisk behaviour
for Local channels.

### The fix (two layers)

**Layer 1 — Admin UI explicit SET (admin_ui/backend/api/outbound_trigger.py):**
```python
# After getting channel_id from originate, SET each var via POST /variable
for var_name, var_value in _vars_to_set.items():
    await http_session.post(
        f"{ari_url}/{channel_id}/variable",
        params={"variable": var_name, "value": var_value},
    )
```
This runs before StasisStart fires on the engine side (~3 second window for Local channels).

**Layer 2 — Engine self-SET in routing block (src/engine.py):**
```python
if action_type == "outbound_reminder":
    await self.ari_client.set_channel_var(channel_id, "AI_CONTEXT", "outbound_reminder")
    await self._handle_caller_stasis_start_hybrid(channel_id, channel)
```
This is the belt-and-suspenders guarantee. Even if Layer 1 has a timing issue, the engine
sets `AI_CONTEXT` itself before `_resolve_audio_profile` reads it.

---

## 5. Current Contexts

### `outbound_reminder` (appointment reminder)

| Field | Value |
|---|---|
| Trigger | HOS scheduler, 1 hour before appointment |
| Greeting | `"Hello, may I speak with {patient_name}?"` |
| Tools | `cancel_appointment`, `reschedule_appointment`, `get_next_serial`, `hangup_call` |
| Prompt vars | `{patient_name}`, `{doctor_name}`, `{appointment_date}`, `{start_time}`, `{appointment_id}` |
| Defined in | `config/ai-agent.local.yaml` → `contexts.outbound_reminder` |

---

## 6. How to Add a New Outbound Context

Adding a new outbound context (e.g., `outbound_feedback` for post-visit surveys) requires
changes in **4 files**. The engine routing code does NOT need to change.

### File 1 — `config/ai-agent.local.yaml`

Add the new context under `contexts:`:

```yaml
contexts:
  outbound_reminder:
    # ... existing ...

  outbound_feedback:                          # ← new context name
    provider: deepgram
    greeting: "Hello, may I speak with {patient_name}?"

    prompt: |
      You are Ava, calling on behalf of Smart Doctor Clinic to collect
      feedback about {patient_name}'s recent visit with {doctor_name}
      on {appointment_date}.

      Ask the patient these questions:
      1. How would you rate your experience? (1 to 5)
      2. Was {doctor_name} helpful and professional?
      3. Would you recommend Smart Doctor Clinic to others?

      After collecting all answers, thank them warmly and use hangup_call.

    in_call_http_tools:
      - submit_feedback             # ← define this tool below in in_call_tools

    tools:
      - hangup_call

    post_call_tools:
      - smart_doctor_call_log
```

If the new context uses new HTTP tools, add them under `in_call_tools:`:

```yaml
in_call_tools:
  # ... existing tools ...

  submit_feedback:
    kind: in_call_http_lookup
    phase: in_call
    enabled: true
    timeout_ms: 5000
    url: http://168.144.27.225/api/v1/feedback
    method: POST
    headers:
      Content-Type: application/json
      X-Tenant-ID: '1'
      X-API-Key: dev-api-key-replace-in-production
    success_status_codes: [200, 201]
    output_variables:
      feedback_saved: success
      feedback_id: data.id
    parameters:
      - name: appointment_id
        type: string
        required: true
      - name: rating
        type: integer
        required: true
    body_template: |
      {
        "appointmentId": "{appointment_id}",
        "rating": {rating}
      }
```

### File 2 — `admin_ui/backend/api/outbound_trigger.py`

**2a.** Add any new request fields to `OutboundTriggerRequest`:

```python
class OutboundTriggerRequest(BaseModel):
    phone_number:    str = Field(...)
    patient_id:      str = Field(...)
    patient_name:    str = Field(...)
    appointment_id:  str = Field(...)
    doctor_name:     str = Field(...)
    appointment_date:str = Field(...)
    start_time:      str = Field(...)
    context:         str = Field(default="outbound_reminder")
    caller_id: Optional[str] = Field(default=None)

    # Add new optional fields for additional contexts:
    visit_date: Optional[str] = Field(default=None)    # ← example for feedback
```

**2b.** Add the new field to `_vars_to_set` inside the route handler:

```python
_vars_to_set = {
    "AI_CONTEXT":       req.context,
    "CALL_TYPE":        req.context,
    "PATIENT_NAME":     req.patient_name,
    "PATIENT_ID":       req.patient_id,
    "APPOINTMENT_ID":   req.appointment_id,
    "DOCTOR_NAME":      req.doctor_name,
    "APPOINTMENT_DATE": req.appointment_date,
    "START_TIME":       req.start_time,
    # Add new vars here:
    "VISIT_DATE":       req.visit_date or "",     # ← new field
}
```

### File 3 — `src/engine.py` (optional — only if new prompt vars needed)

In `_handle_caller_stasis_start_hybrid`, add the new channel var to `_reminder_var_map`:

```python
_reminder_var_map = {
    "PATIENT_NAME":     "patient_name",
    "PATIENT_ID":       "patient_id",
    "APPOINTMENT_ID":   "appointment_id",
    "DOCTOR_NAME":      "doctor_name",
    "APPOINTMENT_DATE": "appointment_date",
    "START_TIME":       "start_time",
    # Add new vars here (channel var name → template var name):
    "VISIT_DATE":       "visit_date",             # ← new field
}
```

> **Note:** The engine routing block (`if action_type == "outbound_reminder":`) does NOT
> need to change. It handles ALL outbound contexts because `appArgs` is always
> `"outbound_reminder"` for any outbound trigger call. The actual context (prompt/tools)
> is determined by `AI_CONTEXT` which is read from the channel and resolved against
> `ai-agent.local.yaml`.

### File 4 — HOS Backend call

Just change the `context` field in the API request:

```json
POST /api/outbound/trigger
{
  "phone_number":    "+923001234567",
  "patient_id":      "42",
  "patient_name":    "Ahmed Khan",
  "appointment_id":  "101",
  "doctor_name":     "Dr. Hina Farooqi",
  "appointment_date":"2026-05-20",
  "start_time":      "09:00",
  "context":         "outbound_feedback",    ← just change this
  "visit_date":      "2026-05-14"            ← new optional field
}
```

### Summary table

| Step | File | Always required? |
|---|---|---|
| Define context prompt + greeting | `config/ai-agent.local.yaml` → `contexts:` | ✅ Yes |
| Define new HTTP tools (if needed) | `config/ai-agent.local.yaml` → `in_call_tools:` | Only if new tools |
| Add new request fields | `outbound_trigger.py` → `OutboundTriggerRequest` | Only if new data |
| Add new vars to SET | `outbound_trigger.py` → `_vars_to_set` | Only if new data |
| Add new vars to engine reader | `engine.py` → `_reminder_var_map` | Only if new prompt vars |
| Change `context` in API call | HOS Backend | ✅ Yes |
| Modify engine routing block | `engine.py` → `_handle_stasis_start` | ❌ Never needed |

---

## 7. Files Reference

```
admin_ui/backend/api/outbound_trigger.py
    POST /api/outbound/trigger endpoint
    - OutboundTriggerRequest model (all request fields)
    - ARI originate call (Step B)
    - Explicit channel var SET calls (Step C)
    - OutboundTriggerResponse model

src/engine.py
    _handle_stasis_start()              ~line 2428
        Routes 'outbound_reminder' action_type, SETs AI_CONTEXT
    _handle_caller_stasis_start_hybrid()~line 3043
        Reads CALL_TYPE + patient vars from channel → pre_call_results
    _resolve_audio_profile()            ~line 11847
        Reads AI_CONTEXT → sets session.context_name (patched to not overwrite)
    _execute_pre_call_tools()           ~line 14108
        Merges pre-seeded pre_call_results with tool results (patched to merge)

config/ai-agent.local.yaml
    contexts.outbound_reminder          → outbound reminder prompt/tools
    in_call_tools.cancel_appointment    → cancel tool definition
    in_call_tools.reschedule_appointment→ reschedule tool definition

admin_ui/backend/main.py
    Line ~127: from api.outbound_trigger import trigger_router
    Line ~237: app.include_router(trigger_router, prefix="/api")
               (NO JWT dependency — API key auth only)
```

---

## 8. API Reference

### POST `/api/outbound/trigger`

**Auth:** `X-Api-Key: <OUTBOUND_TRIGGER_API_KEY>` (set in `.env`)

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `phone_number` | string | ✅ | Extension or E.164 number to dial |
| `patient_id` | string | ✅ | Patient ID from HOS backend |
| `patient_name` | string | ✅ | Patient full name (used in greeting) |
| `appointment_id` | string | ✅ | Appointment ID (used by cancel/reschedule tools) |
| `doctor_name` | string | ✅ | Doctor full name (used in reminder message) |
| `appointment_date` | string | ✅ | Date in `YYYY-MM-DD` format |
| `start_time` | string | ✅ | Time in `HH:MM` format (24h) |
| `context` | string | ✅ | AI context name — must exist in `ai-agent.local.yaml` |
| `caller_id` | string | ❌ | Caller ID shown to patient. Falls back to `AAVA_OUTBOUND_EXTENSION_IDENTITY` |

**Success response (HTTP 200):**
```json
{
  "ok": true,
  "channel_id": "1779279722.51",
  "phone_number": "6000",
  "context": "outbound_reminder",
  "message": "Outbound call initiated"
}
```

**Error responses:**

| Code | Meaning |
|---|---|
| 401 | Wrong or missing `X-Api-Key` |
| 503 | `OUTBOUND_TRIGGER_API_KEY` not set in `.env` — endpoint disabled |
| 502 | Asterisk ARI unreachable or returned an error |
| 500 | Unexpected internal error |

**Test with curl:**
```bash
curl -s -X POST http://192.168.0.170:3003/api/outbound/trigger \
  -H "X-Api-Key: your-strong-random-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number":    "6000",
    "patient_id":      "42",
    "patient_name":    "Ahmed Khan",
    "appointment_id":  "101",
    "doctor_name":     "Dr. Hina Farooqi",
    "appointment_date":"2026-05-20",
    "start_time":      "09:00",
    "context":         "outbound_reminder"
  }'
```

---

## 9. Troubleshooting

### Context is empty in call history UI

```
Symptom: Configuration shows  Context: -
Cause:   AI_CONTEXT channel var not readable from Local channel
Fix:     Already handled by engine-side SET in routing block.
         If still happening, restart ai_engine container:
           docker compose restart ai_engine
```

### Call connects but wrong prompt (default "You are Asterisk Agent...")

```
Symptom: Deepgram Think prompt shows default prompt
Cause 1: Context name in request body doesn't match context name in ai-agent.local.yaml
         Check: "context": "outbound_reminder" matches contexts.outbound_reminder in yaml
Cause 2: ai-agent.local.yaml not reloaded after changes
         Fix: docker compose restart ai_engine
```

### Template vars empty (Ava says "Hello, may I speak with ?")

```
Symptom: Patient name / doctor name is blank in greeting
Cause:   Channel vars (PATIENT_NAME etc.) not readable from Local channel
         outbound_trigger.py SET calls might have failed or timed out.
Check:   docker compose logs admin_ui | grep "channel vars SET"
         Should show: channel vars SET via ARI — channel_id=... vars=[...]
Fix:     Check Asterisk ARI is reachable from admin_ui container
```

### Call immediately hangs up (no audio)

```
Symptom: Phone rings, when answered it hangs up immediately
Cause:   Context listed in in_call_http_tools does not have a tool definition
         in in_call_tools section of ai-agent.local.yaml.
Fix:     Add the missing tool definition under in_call_tools:
         See ai-agent.local.yaml for cancel_appointment / reschedule_appointment examples.
```

### 503 from trigger endpoint

```
Symptom: {"detail": "Outbound trigger is not configured..."}
Cause:   OUTBOUND_TRIGGER_API_KEY not set in .env
Fix:     Add to .env:  OUTBOUND_TRIGGER_API_KEY=<generate with: openssl rand -hex 32>
         Then restart:  docker compose restart admin_ui
```

### 401 from trigger endpoint

```
Symptom: {"detail": "Invalid or missing API key"}
Cause:   X-Api-Key header missing or value doesn't match OUTBOUND_TRIGGER_API_KEY in .env
Fix:     Check the key in .env matches what HOS backend is sending
```
