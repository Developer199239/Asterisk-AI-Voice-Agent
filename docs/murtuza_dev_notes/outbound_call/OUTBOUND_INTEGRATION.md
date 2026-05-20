# Outbound Call Integration — Developer Guide

**Author:** Murtuza  
**Last updated:** 2026-05-20  
**Status:** Working in production

---

## Table of Contents

1. [What This Does](#1-what-this-does)
2. [End-to-End Architecture](#2-end-to-end-architecture)
3. [How It Works — Step by Step](#3-how-it-works--step-by-step)
4. [Files Changed and Why](#4-files-changed-and-why)
5. [How to Add a New Outbound Context](#5-how-to-add-a-new-outbound-context)
6. [Environment Variables](#6-environment-variables)
7. [API Reference](#7-api-reference)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. What This Does

The outbound call system lets an external backend (HOS Java scheduler) trigger an AI phone
call to a patient. Ava (Deepgram Voice Agent) makes the call, delivers the message, and
handles patient responses — no human operator needed.

**Current use case:** Appointment reminders (context: `outbound_reminder`)
- Ava calls the patient 1 hour before their appointment
- Reads the appointment details aloud
- Can confirm attendance, cancel, or reschedule based on patient response

**Authentication:** Shared API key via `X-Api-Key` header — no JWT needed.  
**Port:** Admin UI port `3003` (same as dashboard).

---

## 2. End-to-End Architecture

```
HOS Backend (Java Scheduler)
       │
       │  POST http://<AI_ENGINE_IP>:3003/api/outbound/trigger
       │  X-Api-Key: <OUTBOUND_TRIGGER_API_KEY>
       │  { "phone_number":"6000", "patient_name":"Ahmed Khan",
       │    "doctor_name":"Dr. Hina", "appointment_date":"2026-05-20",
       │    "start_time":"09:00", "appointment_id":"101",
       │    "patient_id":"42", "context":"outbound_reminder" }
       │
       ▼
Admin UI  (outbound_trigger.py)
       │
       ├─ 1. Validate X-Api-Key
       │
       └─ 2. POST /ari/channels to Asterisk ARI
              ?endpoint=Local/6000@from-internal
              &app=asterisk-ai-voice-agent
              &appArgs=outbound_reminder,patient_name=Ahmed Khan|doctor_name=Dr. Hina|...
              &timeout=60
              &callerId=Smart Doctor Clinic
              ▲
              Patient data embedded in appArgs — key design decision,
              explained in Section 4.

Asterisk
       │
       ├─ Creates Local channel PAIR:
       │    Local/6000;1  →  enters Stasis app (AI side)
       │    Local/6000;2  →  dialplan from-internal → rings extension 6000
       │
       └─ Fires StasisStart event (WebSocket) for Local/6000;1
              args = ['outbound_reminder',
                      'patient_name=Ahmed Khan|doctor_name=Dr. Hina|...']

AI Engine  (engine.py)
       │
       ├─ _handle_stasis_start()
       │    args[0] = 'outbound_reminder'  → routing decision
       │    args[1] = patient data string  → parsed into dict, cached in memory
       │    SET AI_CONTEXT=outbound_reminder on channel
       │    → call _handle_caller_stasis_start_hybrid()
       │
       ├─ _handle_caller_stasis_start_hybrid()
       │    Reads AI_CONTEXT from channel      → "outbound_reminder"
       │    Pops cached patient dict           → session.pre_call_results = {
       │                                            patient_name: "Ahmed Khan",
       │                                            doctor_name:  "Dr. Hina",
       │                                            appointment_date: "2026-05-20",
       │                                            start_time: "09:00",
       │                                            appointment_id: "101",
       │                                            patient_id: "42"
       │                                        }
       │
       ├─ _resolve_audio_profile()
       │    AI_CONTEXT = "outbound_reminder"  → loads outbound_reminder context
       │    session.context_name = "outbound_reminder"
       │
       └─ _ensure_provider_session_started()
            Gets outbound_reminder prompt from ai-agent.local.yaml
            Substitutes template vars:
                {patient_name}     → "Ahmed Khan"
                {doctor_name}      → "Dr. Hina"
                {appointment_date} → "2026-05-20"
                {start_time}       → "09:00"
            Sends final prompt + greeting to Deepgram

Deepgram Voice Agent
       Greeting: "Hello, may I speak with Ahmed Khan?"
       Ava handles: confirm / cancel / reschedule
       Tools: cancel_appointment, reschedule_appointment, hangup_call
```

---

## 3. How It Works — Step by Step

### Step 1 — HOS Backend sends the trigger request

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

### Step 2 — Admin UI encodes patient data into appArgs and calls ARI

`outbound_trigger.py` encodes all patient fields into the `appArgs` URL parameter:

```
appArgs = "outbound_reminder,patient_name=Ahmed Khan|doctor_name=Dr. Hina Farooqi|
           appointment_date=2026-05-20|start_time=09:00|appointment_id=101|
           patient_id=42|context=outbound_reminder"
```

This string is passed to ARI via:

```
POST http://asterisk:8088/ari/channels
  ?endpoint=Local/6000@from-internal
  &app=asterisk-ai-voice-agent
  &appArgs=outbound_reminder,patient_name=Ahmed Khan|...
  &timeout=60
  &callerId=Smart Doctor Clinic
```

### Step 3 — Asterisk creates a Local channel pair

Asterisk creates two channels:

| Channel | Goes to | Purpose |
|---------|---------|---------|
| `Local/6000@from-internal;1` | Stasis app (AI engine) | Audio stream, AI conversation |
| `Local/6000@from-internal;2` | Dialplan → extension 6000 | Rings the patient's phone |

Asterisk fires a `StasisStart` WebSocket event to the engine for the `;1` channel with:
```json
{
  "args": [
    "outbound_reminder",
    "patient_name=Ahmed Khan|doctor_name=Dr. Hina Farooqi|..."
  ]
}
```

### Step 4 — Engine routing block handles the event

In `engine.py → _handle_stasis_start()`:

```python
if action_type == "outbound_reminder":
    # Parse patient data from args[1] (zero race condition, in-memory)
    if len(args) > 1 and "=" in args[1]:
        _parsed_data = {}
        for kv in args[1].split("|"):
            k, _, v = kv.partition("=")
            _parsed_data[k.strip()] = v.strip()
        self._outbound_reminder_vars[channel_id] = _parsed_data

    # SET AI_CONTEXT on the ;1 channel so _resolve_audio_profile can read it
    await self.ari_client.set_channel_var(channel_id, "AI_CONTEXT", "outbound_reminder")

    await self._handle_caller_stasis_start_hybrid(channel_id, channel)
```

### Step 5 — Patient data seeds the prompt template

In `engine.py → _handle_caller_stasis_start_hybrid()`:

```python
if _ai_ctx_now.startswith("outbound_"):
    # Pop from in-memory cache (set in routing block 5ms earlier)
    _outbound_data = self._outbound_reminder_vars.pop(caller_channel_id, {})
    if _outbound_data:
        session.pre_call_results = _outbound_data   # {patient_name: ..., doctor_name: ...}
```

### Step 6 — Deepgram receives the substituted prompt

The engine substitutes `{patient_name}`, `{doctor_name}`, etc. from `session.pre_call_results`
into the context's prompt and greeting before sending the `Settings` message to Deepgram.

Ava's greeting becomes: `"Hello, may I speak with Ahmed Khan?"` ✅

---

## 4. Files Changed and Why

### `admin_ui/backend/api/outbound_trigger.py` — NEW FILE

The trigger endpoint. Created because the existing campaign API requires CSV import and
is designed for batch dialing — not suitable for single on-demand calls.

**Key design decisions:**

**a) No JWT auth** — uses `X-Api-Key` header instead. This endpoint is called by the HOS
Java backend (machine-to-machine), not a human in a browser.

**b) Patient data in appArgs, not channel vars** — this is the critical fix.

When you originate `Local/` channels via ARI:
- ARI originate returns the `;2` channel ID (dialplan side)
- `;2` is NOT in a Stasis application
- `POST /ari/channels/{id}/variable` on the `;2` id → HTTP **409 Conflict**
- The engine works with `;1` (different ID!) — so any SET calls on `;2` are invisible to it

By encoding data in `appArgs`, the data travels inside the `StasisStart` event itself.
No channel var reads needed. Zero race condition.

```python
# The key change in outbound_trigger.py:
_patient_arg = "|".join([
    f"patient_name={req.patient_name}",
    f"doctor_name={req.doctor_name}",
    f"appointment_date={req.appointment_date}",
    f"start_time={req.start_time}",
    f"appointment_id={req.appointment_id}",
    f"patient_id={req.patient_id}",
    f"context={req.context}",
])

ari_query_params = {
    "endpoint": f"Local/{req.phone_number}@from-internal",
    "app":      "asterisk-ai-voice-agent",
    "appArgs":  f"outbound_reminder,{_patient_arg}",   # ← patient data here
    "timeout":  "60",
    "callerId": caller_id,
}
```

---

### `admin_ui/backend/main.py` — 2 lines added

The trigger router is registered **without JWT dependency**:

```python
from api.outbound_trigger import trigger_router

# All other outbound routes remain JWT-protected above.
# This one uses X-Api-Key auth for machine-to-machine calls.
app.include_router(trigger_router, prefix="/api", tags=["outbound"])
```

---

### `src/engine.py` — 4 changes

#### Change 1 — `_handle_stasis_start()` routing block (~line 2450)

Added the `outbound_reminder` action type handler. Parses patient data from `args[1]`
and caches it so `_handle_caller_stasis_start_hybrid` can use it:

```python
if action_type == "outbound_reminder":
    # Parse patient data from args[1] — available immediately, no I/O needed
    if not hasattr(self, "_outbound_reminder_vars"):
        self._outbound_reminder_vars = {}
    if len(args) > 1 and "=" in args[1]:
        _parsed_data = {}
        for kv in args[1].split("|"):
            k, _, v = kv.partition("=")
            _parsed_data[k.strip()] = v.strip()
        self._outbound_reminder_vars[channel_id] = _parsed_data
        _reminder_context_name = _parsed_data.get("context", "outbound_reminder")
    else:
        _reminder_context_name = args[1] if len(args) > 1 else "outbound_reminder"

    # SET AI_CONTEXT on the ;1 channel from the engine itself
    # (can't be done from outbound_trigger.py — it only has the ;2 channel ID)
    await self.ari_client.set_channel_var(channel_id, "AI_CONTEXT", _reminder_context_name)
    await self._handle_caller_stasis_start_hybrid(channel_id, channel)
    return
```

**Why the engine SETs AI_CONTEXT itself:** `_resolve_audio_profile()` reads `AI_CONTEXT`
from the channel to determine which context (prompt/tools) to load. The engine has the
correct `;1` channel ID in the StasisStart event, so its own SET call works reliably.

#### Change 2 — `_handle_caller_stasis_start_hybrid()` patient data block (~line 3237)

Reads patient data from the in-memory cache (populated in Change 1) and seeds
`session.pre_call_results` so template substitution works:

```python
if _ai_ctx_now.startswith("outbound_"):
    _outbound_data = {}
    if hasattr(self, "_outbound_reminder_vars"):
        _outbound_data = self._outbound_reminder_vars.pop(caller_channel_id, {})
    if _outbound_data:
        _outbound_data.pop("context", None)   # remove routing key, not a template var
        session.pre_call_results = _outbound_data
```

#### Change 3 — `_resolve_audio_profile()` (~line 11936)

Fixed a bug where `context_name` was overwritten with `None` when `AI_CONTEXT` channel
var was not readable:

```python
# Before (broken):
session.context_name = channel_vars.get('AI_CONTEXT')   # sets None if not found

# After (fixed):
_resolved = channel_vars.get('AI_CONTEXT')
if _resolved:                                            # only overwrite if non-empty
    session.context_name = _resolved
```

#### Change 4 — `_execute_pre_call_tools()` (~line 14116)

Fixed pre-seeded patient data being wiped when no pre-call HTTP tools run:

```python
# Before (broken):
session.pre_call_results = results    # wiped pre-seeded data if results = {}

# After (fixed):
_pre_seeded = dict(getattr(session, "pre_call_results", {}) or {})
_pre_seeded.update(results)           # tool results win; pre-seeded data preserved
session.pre_call_results = _pre_seeded
```

---

### `config/ai-agent.local.yaml` — context added

Added the `outbound_reminder` context with Ava's full prompt, appointment details
template variables, and tools for cancel/reschedule.

---

## 5. How to Add a New Outbound Context

Adding a new outbound context (e.g., `outbound_feedback`) requires changes in
**at most 3 places**. The engine routing code never needs to change.

### Step A — Define the context in `config/ai-agent.local.yaml`

```yaml
contexts:
  outbound_reminder:
    # ... existing, do not touch ...

  outbound_feedback:                        # ← new context name
    provider: deepgram
    greeting: "Hello, may I speak with {patient_name}?"
    prompt: |
      You are Ava, calling on behalf of Smart Doctor Clinic to collect
      feedback about {patient_name}'s visit with {doctor_name}
      on {appointment_date}.

      Ask:
      1. How would you rate your experience? (1 to 5)
      2. Was {doctor_name} helpful and professional?
      3. Would you recommend us to others?

      After collecting all answers, thank them and use hangup_call.

    in_call_http_tools:
      - submit_feedback           # ← define this below in in_call_tools
    tools:
      - hangup_call
    post_call_tools:
      - smart_doctor_call_log
```

If the new context needs new HTTP tools, add them under `in_call_tools:`:

```yaml
in_call_tools:
  submit_feedback:
    kind: in_call_http_lookup
    phase: in_call
    enabled: true
    timeout_ms: 5000
    url: http://168.144.27.225/api/v1/feedback
    method: POST
    headers:
      Content-Type: application/json
      X-API-Key: your-api-key
    parameters:
      - name: appointment_id
        type: string
        required: true
      - name: rating
        type: integer
        required: true
    body_template: |
      {"appointmentId": "{appointment_id}", "rating": {rating}}
```

### Step B — Add new fields to the trigger request (if needed)

If the new context needs extra data that doesn't already exist in `OutboundTriggerRequest`
(e.g., a `visit_date` field for feedback calls), add it:

**`admin_ui/backend/api/outbound_trigger.py`:**

```python
class OutboundTriggerRequest(BaseModel):
    # ... existing fields ...
    visit_date: Optional[str] = Field(default=None, description="Date of the visit")
```

Then add it to the `_patient_arg` encoding in the route handler:

```python
_patient_arg = "|".join([
    f"patient_name={_safe(req.patient_name)}",
    f"doctor_name={_safe(req.doctor_name)}",
    f"appointment_date={_safe(req.appointment_date)}",
    f"start_time={_safe(req.start_time)}",
    f"appointment_id={_safe(req.appointment_id)}",
    f"patient_id={_safe(req.patient_id)}",
    f"context={_safe(req.context)}",
    f"visit_date={_safe(req.visit_date or '')}",    # ← new field
])
```

### Step C — Add new template vars to the engine reader (if needed)

In `engine.py → _handle_caller_stasis_start_hybrid()`, the patient data block reads all
keys from the appArgs dict and stores them in `session.pre_call_results`. Any key you
put in `_patient_arg` automatically becomes a template variable in your prompt.

**No engine code change is needed** for new fields — they flow through automatically
because the dict is stored as-is.

So if you add `visit_date=2026-05-14` to `_patient_arg` in Step B, you can use
`{visit_date}` in your prompt immediately. ✅

### Step D — Trigger with the new context

```bash
curl -s -X POST http://192.168.0.170:3003/api/outbound/trigger \
  -H "X-Api-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number":    "6000",
    "patient_id":      "42",
    "patient_name":    "Ahmed Khan",
    "appointment_id":  "101",
    "doctor_name":     "Dr. Hina Farooqi",
    "appointment_date":"2026-05-20",
    "start_time":      "09:00",
    "context":         "outbound_feedback",
    "visit_date":      "2026-05-14"
  }'
```

### Summary of what is required

| What to change | File | When required |
|----------------|------|---------------|
| Define context + prompt | `config/ai-agent.local.yaml` → `contexts:` | **Always** |
| Define new HTTP tools | `config/ai-agent.local.yaml` → `in_call_tools:` | Only if new tools |
| Add new request fields | `outbound_trigger.py` → `OutboundTriggerRequest` | Only if new data needed |
| Add to `_patient_arg` encoding | `outbound_trigger.py` → route handler | Only if new data needed |
| Change engine routing | `engine.py` → `_handle_stasis_start()` | **Never needed** |
| Change engine patient block | `engine.py` → `_handle_caller_stasis_start_hybrid()` | **Never needed** |

---

## 6. Environment Variables

Add these to your `.env` file:

```env
# Required — trigger endpoint is disabled (returns 503) if this is not set
OUTBOUND_TRIGGER_API_KEY=generate-with-openssl-rand-hex-32

# Optional — caller ID shown to the patient (defaults to "Smart Doctor Clinic")
AAVA_OUTBOUND_EXTENSION_IDENTITY=Smart Doctor Clinic

# Optional — dialplan context for outbound (default: from-internal)
AAVA_OUTBOUND_DIAL_CONTEXT=from-internal
```

Generate a strong key:
```bash
openssl rand -hex 32
```

---

## 7. API Reference

### `POST /api/outbound/trigger`

**Authentication:** `X-Api-Key: <OUTBOUND_TRIGGER_API_KEY>`  
**No JWT required.**

#### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `phone_number` | string | ✅ | Extension or E.164 number (`6000` or `+923001234567`) |
| `patient_id` | string | ✅ | Patient ID from HOS |
| `patient_name` | string | ✅ | Full name — used in greeting and prompt |
| `appointment_id` | string | ✅ | Used by cancel/reschedule tools during the call |
| `doctor_name` | string | ✅ | Doctor full name — used in reminder message |
| `appointment_date` | string | ✅ | `YYYY-MM-DD` format |
| `start_time` | string | ✅ | `HH:MM` 24-hour format |
| `context` | string | ✅ | Must match a context name in `ai-agent.local.yaml` |
| `caller_id` | string | ❌ | Caller ID shown to patient. Falls back to env var |

#### Success response (HTTP 200)

```json
{
  "ok": true,
  "channel_id": "1779279722.51",
  "phone_number": "6000",
  "context": "outbound_reminder",
  "message": "Outbound call initiated"
}
```

#### Error responses

| Code | Cause | Fix |
|------|-------|-----|
| 401 | Wrong or missing `X-Api-Key` | Check key matches `.env` |
| 503 | `OUTBOUND_TRIGGER_API_KEY` not set | Add to `.env`, restart `admin_ui` |
| 502 | ARI unreachable or ARI returned error | Check Asterisk is running |
| 500 | Unexpected error | Check `admin_ui` logs |

#### Test curl command

```bash
curl -s -X POST http://192.168.0.170:3003/api/outbound/trigger \
  -H "X-Api-Key: your-key-here" \
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
  }' | python3 -m json.tool
```

---

## 8. Troubleshooting

### Ava says `{patient_name}` literally instead of the actual name

```
Check engine logs:
  docker compose logs ai_engine | grep "OUTBOUND REMINDER"

Expected:
  🔔 OUTBOUND REMINDER - Patient data parsed from appArgs  keys=['patient_name', ...]
  Outbound: pre-seeded pre_call_results from appArgs       keys=['patient_name', ...]

If you see "no patient data in appArgs":
  The admin_ui container is running old code.
  Fix: docker compose restart admin_ui
```

### Context shows as empty or wrong in call history UI

```
Check engine logs for:
  "Outbound: context_name pre-set from AI_CONTEXT channel var  context_name=outbound_reminder"

If missing:
  Engine is running old code.
  Fix: docker compose restart ai_engine
```

### Call connects but uses the default prompt ("You are Asterisk Agent...")

```
Cause: Context name in request body doesn't match what is in ai-agent.local.yaml.
Check: "context":"outbound_reminder"  must match  contexts.outbound_reminder in yaml.
Fix:   Make sure both names are identical (case-sensitive).
       Then: docker compose restart ai_engine
```

### 503 from trigger endpoint

```
Cause: OUTBOUND_TRIGGER_API_KEY not set in .env
Fix:
  echo "OUTBOUND_TRIGGER_API_KEY=$(openssl rand -hex 32)" >> .env
  docker compose restart admin_ui
```

### 502 from trigger endpoint

```
Cause: admin_ui container cannot reach Asterisk ARI.
Check admin_ui logs:
  docker compose logs admin_ui | grep "ARI"
Verify:
  ASTERISK_HOST and ASTERISK_ARI_PORT in .env are correct
  Asterisk is running: docker compose ps
```

### Call rings but hangs up immediately after answer

```
Cause: A tool listed in in_call_http_tools doesn't have a definition in in_call_tools.
Fix:   Add the missing tool definition to config/ai-agent.local.yaml under in_call_tools.
       Then: docker compose restart ai_engine
```

### SET channel var returns HTTP 409 in admin_ui logs

```
This is expected and harmless.
Explanation: ARI originate returns the Local;2 channel ID.
             Local;2 is NOT in a Stasis application → 409 is correct.
             Patient data is passed via appArgs now — the 409 warnings can be ignored.
             The outbound_trigger.py code still attempts SET as legacy compatibility
             but the engine no longer depends on it.
```

---

## Appendix — Root Cause History (for reference)

Three bugs were discovered and fixed while building this feature:

| # | Bug | Root cause | Fix |
|---|-----|-----------|-----|
| 1 | `AI_CONTEXT` not readable from channel | `channelVars` in ARI originate body not exposed via GET on Local channels | Engine SETs `AI_CONTEXT` itself in routing block |
| 2 | `AI_CONTEXT` overwritten with `None` | `_resolve_audio_profile()` did `session.context_name = channel_vars.get('AI_CONTEXT')` — sets None if missing | Only assign if value is non-empty |
| 3 | Patient vars never readable despite explicit SET | ARI originate returns the `;2` channel ID. `;2` is not in Stasis → HTTP 409. Engine reads from `;1` (different ID) — SET on `;2` is invisible | Encode patient data in `appArgs` — available in `StasisStart.args[]` immediately |
