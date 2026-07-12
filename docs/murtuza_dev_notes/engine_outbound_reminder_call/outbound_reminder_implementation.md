# outbound_reminder — Implementation Notes

> **Branch:** `dev_5_10_26`  
> **Author:** Jalilur Rahman Murtuza  
> **Date:** 2026-07-11  

---

## What This Feature Does

Triggers a single **outbound appointment reminder** call from the HOS backend Java scheduler,
typically 1 hour before a patient's appointment. When triggered via
`POST /api/outbound/trigger` with `context=outbound_reminder`, the engine:

1. Dials the patient's phone number through Asterisk via a `Local/` channel.
2. Runs AMD (Answering Machine Detection) via the `[sub-amd-check]` subroutine.
3. **If no answer / busy:** Dialplan POSTs `{"appointmentId":"…","result":"no_answer","patientId":"…"}` directly to HOS via `curl`.
4. **If answered (human detected):** Stasis hands off to the engine under the `outbound_reminder` context — Deepgram Voice Agent session starts.
5. **During the call:** AI can confirm, cancel, or reschedule the appointment using in-call tools.
6. **At conversation end:** AI calls `update_call_result` which POSTs `{"appointmentId":"…","result":"…","patientId":"…"}` to HOS.

---

## Files Involved

| File | Role |
|------|------|
| `admin_ui/backend/api/outbound_trigger.py` | REST endpoint called by HOS; builds ARI originate request |
| `src/engine.py` | `outbound_reminder` action handler; seeding block in `_handle_caller_stasis_start_hybrid` |
| `config/ai-agent.local.yaml` | `outbound_reminder` context config + `update_call_result` / `cancel_appointment` tools |
| `docs/murtuza_dev_notes/3_extension_custom.conf` | `[from-ai-outbound]` dialplan + AMD subroutine |

---

## API Endpoint

### Trigger an outbound reminder call

```
POST /api/outbound/trigger
X-Api-Key: <OUTBOUND_TRIGGER_API_KEY>
Content-Type: application/json

{
  "context":          "outbound_reminder",
  "phone_number":     "01700000000",
  "patient_name":     "Md. Jalilur Rahman",
  "patient_id":       "101",
  "appointment_id":   "55",
  "doctor_name":      "Dr. Farhan Ahmed",
  "appointment_date": "2026-07-12",
  "start_time":       "09:00"
}
```

**Authentication:** `X-Api-Key` header, checked against `OUTBOUND_TRIGGER_API_KEY` in `.env`.
No JWT required — designed for machine-to-machine calls from the HOS Java scheduler.

**Required fields for `outbound_reminder`:** `phone_number`, `patient_name`, `patient_id`,
`appointment_id`, `doctor_name`, `appointment_date`, `start_time`.

---

## How the Trigger Works (`outbound_trigger.py`)

```
outbound_reminder branch:

  Extension format: {phone}_{appointment_id}_{patient_id}
  e.g. 01700000000_55_101

  ARI originate:
    endpoint  = Local/01700000000_55_101@from-internal
    app       = asterisk-ai-voice-agent
    appArgs   = outbound_reminder,patient_name=…|doctor_name=…|appointment_date=…
                |start_time=…|appointment_id=…|patient_id=…|context=outbound_reminder
    timeout   = 20
    callerId  = Smart Doctor Clinic

  channelVars (JSON body):
    AI_CONTEXT       = outbound_reminder
    PATIENT_ID       = 101
    PATIENT_NAME     = Md. Jalilur Rahman
    APPOINTMENT_ID   = 55
    DOCTOR_NAME      = Dr. Farhan Ahmed
    APPOINTMENT_DATE = 2026-07-12
    START_TIME       = 09:00
    CALL_TYPE        = outbound_reminder

  After originate: also SET each var individually via
  POST /ari/channels/{id}/variable (belt-and-suspenders, may 409 on Local/ half)
```

**Env var for dial context** (add to `.env` to override):
```
AAVA_OUTBOUND_DIAL_CONTEXT=from-internal
```
Default is `from-internal` (FreePBX standard context).
The extension `8000` inside `[from-internal-custom]` redirects to `[from-outbound-reminder]` for manual testing.

---

## Engine Handler (`src/engine.py`)

### Action handler (~line 2450)

When `StasisStart` fires with `args[0] == "outbound_reminder"`:

1. Parses `args[1]` (pipe-separated `key=value` pairs) into a dict.
2. Stores the dict in `self._outbound_reminder_vars[channel_id]`.
3. Tries to `SET AI_CONTEXT=outbound_reminder` on the channel via ARI.
4. Calls `_handle_caller_stasis_start_hybrid(channel_id, channel)`.

```python
if action_type == "outbound_reminder":
    if not hasattr(self, "_outbound_reminder_vars"):
        self._outbound_reminder_vars: dict = {}

    if len(args) > 1 and "=" in args[1]:
        _parsed_data: dict = {}
        for _kv in args[1].split("|"):
            if "=" in _kv:
                _k, _, _v = _kv.partition("=")
                _parsed_data[_k.strip()] = _v.strip()
        if _parsed_data:
            self._outbound_reminder_vars[channel_id] = _parsed_data

    await self._handle_caller_stasis_start_hybrid(channel_id, channel)
    return
```

### Seeding block (~line 3356) inside `_handle_caller_stasis_start_hybrid`

After the caller channel is answered and the bridge is set up, the engine reads
`AI_CONTEXT` from the channel via ARI GET. If it starts with `"outbound_"`, the
seeding block:

1. Pops `self._outbound_reminder_vars[caller_channel_id]` into `_outbound_data`.
2. Removes the `"context"` key (internal routing only).
3. Sets `session.pre_call_results = _outbound_data` — this makes template variables
   like `{patient_name}`, `{appointment_id}`, `{doctor_name}`, `{start_time}` available
   in the prompt and greeting.

**Fallback:** If ARI GET returns empty (intermittent for `Local/` channels), the block
reads context from `_outbound_reminder_vars.get(channel_id, {}).get("context", "")` so
the seeding still runs.

---

## Dialplan (`3_extension_custom.conf`)

### Test extension `8000` in `[from-internal-custom]`

Dial `8000` internally to jump straight into the `outbound_reminder` context
(bypasses AMD and real outbound dialing — useful for testing voice/prompt):

```asterisk
exten => 8000,1,NoOp(IVR: 8000 -> outbound_reminder)
 same => n,Goto(from-outbound-reminder,s,1)
```

### `[from-outbound-reminder]` (simple entry, no AMD)

Used by the `8000` test extension:

```asterisk
[from-outbound-reminder]
exten => s,1,NoOp(AI Outbound Reminder)
 same => n,Set(AI_CONTEXT=outbound_reminder)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### `[from-ai-outbound]` (real outbound dialing with AMD)

Extension pattern `_X.` matches `{phone}_{appointment_id}_{patient_id}`:

```asterisk
[from-ai-outbound]
exten => _X.,1,NoOp(AI Outbound Reminder with AMD - raw exten=${EXTEN})
 same => n,Set(DIAL_NUMBER=${CUT(EXTEN,_,1)})
 same => n,Set(APPOINTMENT_ID=${CUT(EXTEN,_,2)})
 same => n,Set(PATIENT_ID=${CUT(EXTEN,_,3)})
 same => n,Dial(PJSIP/${DIAL_NUMBER},20,U(sub-amd-check,s,1))
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,Set(CALL_RESULT=${IF($["${DIALSTATUS}"="BUSY"]?busy:no_answer)})
 same => n,Set(IGNORED=${SHELL(curl -s -X POST http://…/call-result
   --data '{"appointmentId":"${APPOINTMENT_ID}","result":"${CALL_RESULT}","patientId":"${PATIENT_ID}"}')})
 same => n(done),Hangup()

exten => h,1,NoOp(Hangup handler: DIALSTATUS=${DIALSTATUS})
 same => n,GotoIf($["${CALL_RESULT}" != ""]?done)
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,GotoIf($["${APPOINTMENT_ID}" = ""]?done)
 same => n,Set(CALL_RESULT=no_answer)
 same => n,Set(IGNORED=${SHELL(curl … '{"appointmentId":"${APPOINTMENT_ID}","result":"no_answer","patientId":"${PATIENT_ID}"}')})
 same => n(done),NoOp(Hangup handler done)
```

> **Note:** Each `curl` is a single unbroken line — Asterisk does not support
> backslash line continuation inside `SHELL()`.

### `[sub-amd-check]` — shared AMD subroutine

```asterisk
[sub-amd-check]
exten => s,1,NoOp(AMD detection running)
 same => n,AMD(2000,2000,1000,5000)
 same => n,GotoIf($["${AMDCAUSE:0:7}" = "TOOLONG"]?human)
 same => n,GotoIf($["${AMDCAUSE:0:14}" = "INITIALSILENCE"]?human)
 same => n,GotoIf($["${AMDSTATUS}" = "HUMAN"]?human)
 same => n,Hangup()
 same => n(human),Return()
```

Both `[from-ai-outbound]` and `[from-ai-outbound-lead]` share this subroutine.

---

## AI Context Config (`ai-agent.local.yaml`)

### outbound_reminder context

```yaml
outbound_reminder:
  greeting: "Hello, may I speak with {patient_name}?"
  prompt: |
    You are Ava, an AI appointment assistant calling on behalf of Smart Doctor Clinic.
    You are making an OUTBOUND call to remind the patient about their appointment.

    APPOINTMENT DETAILS (do NOT ask the patient for these):
    - Patient name:     {patient_name}
    - Doctor:           {doctor_name}
    - Appointment date: {appointment_date}
    - Appointment time: {start_time}
    - Appointment ID:   {appointment_id}

    CONVERSATION FLOW:
    STEP 1 - Confirm identity  → greet, check it is {patient_name}
    STEP 2 - Deliver reminder  → state appointment with {doctor_name} on {appointment_date} at {start_time}
    STEP 3 - Handle response:
      a) CONFIRM  → patient will attend → call update_call_result(result=confirmed)
      b) CANCEL   → call cancel_appointment, then update_call_result(result=cancelled)
      c) RESCHEDULE → call get_next_serial / reschedule_appointment, then update_call_result(result=rescheduled)
      d) BUSY     → call update_call_result(result=busy)

    GENERAL RULES:
    - BEFORE hangup_call, ALWAYS call update_call_result with the appropriate result value.
  profile: telephony_ulaw_8k
  provider: deepgram
  tools:
    - transfer
    - hangup_call
  in_call_http_tools:
    - cancel_appointment
    - update_call_result
  post_call_tools:
    - smart_doctor_call_log
    - lead_classify_webhook
```

### update_call_result in-call tool

```yaml
update_call_result:
  kind: in_call_http_lookup
  phase: in_call
  url: http://168.144.27.225/api/v1/tools/call-result
  method: POST
  headers:
    Content-Type: application/json
    X-Tenant-ID: '1'
    X-API-Key: dev-api-key-replace-in-production
  parameters:
    - name: call_result   # confirmed / cancelled / rescheduled / no_answer / busy / voicemail
    - name: appointment_id
    - name: patient_id
  body_template: '{"appointmentId": "{appointment_id}", "result": "{call_result}", "patientId": "{patient_id}"}'
```

---

## Call Flow Summary

```
POST /api/outbound/trigger
  context=outbound_reminder, phone, patient_id, appointment_id, doctor_name, ...
        │
        ▼
ARI originate → Local/{phone}_{appointment_id}_{patient_id}@from-internal
        │
        ├── ;2 half dials PJSIP/{phone} via AMD subroutine
        │         │
        │    ┌────┴──────────────────────────────────────────────────┐
        │    │  No Answer / Busy                                     │  Human detected
        │    │                                                       │
        │    ▼                                                       ▼
        │  dialplan curl POST to HOS                  Stasis → engine (outbound_reminder)
        │  {"appointmentId":"…",                        Deepgram Voice Agent starts
        │   "result":"no_answer",                         AI delivers reminder
        │   "patientId":"…"}                                       │
        │                                              AI calls update_call_result
        │                                              {"appointmentId":"…",
        │                                               "result":"confirmed|cancelled|…",
        │                                               "patientId":"…"}
        │                                                           │
        └───────────────────────────────────────────────────────────┘
                                             HOS records appointment outcome
```

---

## HOS API Payloads

All requests go to `POST http://168.144.27.225/api/v1/tools/call-result`.

```json
// No answer / busy — sent by dialplan curl:
{"appointmentId": "55", "result": "no_answer", "patientId": "101"}
{"appointmentId": "55", "result": "busy",      "patientId": "101"}

// Call answered, AI spoke — sent by update_call_result in-call tool:
{"appointmentId": "55", "result": "confirmed",   "patientId": "101"}
{"appointmentId": "55", "result": "cancelled",   "patientId": "101"}
{"appointmentId": "55", "result": "rescheduled", "patientId": "101"}
{"appointmentId": "55", "result": "no_answer",   "patientId": "101"}
{"appointmentId": "55", "result": "busy",        "patientId": "101"}
{"appointmentId": "55", "result": "voicemail",   "patientId": "101"}
```

---

## Template Variables Available in Prompt

These are substituted from `session.pre_call_results` before the provider session starts:

| Variable | Source | Example |
|----------|--------|---------|
| `{patient_name}` | appArgs | `Md. Jalilur Rahman` |
| `{patient_id}` | appArgs | `101` |
| `{appointment_id}` | appArgs | `55` |
| `{doctor_name}` | appArgs | `Dr. Farhan Ahmed` |
| `{appointment_date}` | appArgs | `2026-07-12` |
| `{start_time}` | appArgs | `09:00` |

---

## Comparison: outbound_reminder vs outbound_lead

| | outbound_reminder | outbound_lead |
|---|---|---|
| **Trigger fields** | patient_id, appointment_id, doctor_name, appointment_date, start_time | lead_id |
| **Extension format** | `{phone}_{appt_id}_{patient_id}` | `{phone}_{lead_id}` |
| **Dialplan context** | `from-ai-outbound` (env `AAVA_OUTBOUND_DIAL_CONTEXT`) | `from-ai-outbound-lead` (env `AAVA_OUTBOUND_LEAD_DIAL_CONTEXT`) |
| **HOS no-answer payload** | `{"appointmentId":"…","result":"…","patientId":"…"}` | `{"leadId":"…","result":"no_answer"}` |
| **HOS answered payload** | `{"appointmentId":"…","result":"confirmed\|…","patientId":"…"}` | `{"leadId":"…","result":"answer","interest":"…"}` |
| **In-call tools** | cancel_appointment, update_call_result | update_lead_call_result |
| **Post-call tools** | smart_doctor_call_log, lead_classify_webhook | smart_doctor_call_log |
| **Result values** | confirmed, cancelled, rescheduled, no_answer, busy, voicemail | (in answered payload) interested, not_interested, busy, wrong_person, voicemail |

---

## Reload Checklist

```bash
# Config change only (no Python change) — restart engine to reload yaml:
docker compose restart ai_engine

# If outbound_trigger.py was changed:
docker compose up -d --build admin_ui

# After updating 3_extension_custom.conf on FreePBX:
asterisk -rx "dialplan reload"
```
