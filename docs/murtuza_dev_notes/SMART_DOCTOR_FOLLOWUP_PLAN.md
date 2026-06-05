# Smart Doctor — Outbound Follow-up & Cancel/Reschedule Implementation Plan

**Project:** Smart Doctor Clinic — AI Voice Agent (Ava)  
**Author:** Murtuza Rahman  
**Date:** 2026-05-19 (updated 2026-05-19)  
**Engine version:** v6.5.1  
**Provider:** Deepgram Voice Agent

---

## Overview

After a successful inbound appointment booking, Ava asks whether the patient would like a reminder call one hour before their appointment. If they agree, the HOS backend Java scheduler fires the call at the right time. During both the inbound booking call and the outbound reminder call, the patient can cancel or reschedule their appointment.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  INBOUND CALL  (patient calls clinic)                           │
│  Phone → FreePBX → Asterisk ARI → AI Engine (Deepgram/Ava)     │
│                                                                  │
│  STATE 5 (booking confirmed):                                    │
│  Ava: "Would you like a reminder call 1 hour before?"           │
│  Patient: "Yes"                                                  │
│  AI calls: save_followup_request (POST → HOS backend)           │
└──────────────────────┬──────────────────────────────────────────┘
                       │  HOS stores follow-up preference
                       │
               ┌───────▼────────┐
               │  HOS Backend   │
               │  Java Scheduler│
               │  (Spring Boot) │
               └───────┬────────┘
                       │  T - 1 hour: calls AI Engine trigger API
                       │  POST /api/outbound/trigger
                       │
               ┌───────▼────────────────────────────────────────┐
               │  AI Engine Admin API  (FastAPI)                 │
               │  admin_ui/backend/api/outbound_trigger.py  ✅   │
               │  POST /api/outbound/trigger                     │
               │  Auth: X-Api-Key (OUTBOUND_TRIGGER_API_KEY)     │
               └───────┬────────────────────────────────────────┘
                       │  aiohttp → ARI POST /ari/channels
                       │
               ┌───────▼────────────────────────────────────────┐
               │  Asterisk / FreePBX                             │
               │  Dials patient phone number                     │
               └───────┬────────────────────────────────────────┘
                       │  StasisStart → AI Engine creates session
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│  OUTBOUND CALL  (AI Engine calls patient)                       │
│  Context: "outbound_reminder"                                   │
│                                                                  │
│  Ava: "Hello {patient_name}, this is Ava from Smart Doctor      │
│        Clinic. You have an appointment with {doctor_name}       │
│        tomorrow at {start_time}. Would you like to confirm,     │
│        cancel, or reschedule?"                                   │
│                                                                  │
│  Patient options:                                               │
│  ├── Confirm  → Ava: "Great, see you then!" → hangup           │
│  ├── Cancel   → AI calls cancel_appointment → hangup           │
│  └── Reschedule → AI runs mini booking flow → hangup           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 1 — Inbound Call Changes (STATE 5 Extension)

### 1.1  New In-Call Tool: `save_followup_request`

After the booking is confirmed, Ava asks the follow-up question and, if the patient agrees, calls this tool to register the reminder on the HOS backend.

**Add to `config/ai-agent.local.yaml`** under `in_call_tools:`:

```yaml
save_followup_request:
  kind: in_call_http_lookup
  phase: in_call
  enabled: true
  is_global: false
  timeout_ms: 5000
  url: http://168.144.27.225/api/v1/tools/follow-ups
  method: POST
  headers:
    Content-Type: application/json
    X-Tenant-ID: '1'
    X-API-Key: dev-api-key-replace-in-production
  query_params: {}
  success_status_codes: [200, 201]
  output_variables:
    followup_saved: success
    followup_id: data.id
  description: >-
    Saves the patient's request for a follow-up reminder call 1 hour before
    their appointment. Call this ONLY in STATE 5 after the patient explicitly
    says Yes to the follow-up question. Requires appointment_id and patient_id.
  parameters:
    - name: appointment_id
      type: string
      description: The appointment ID returned by book_appointment
      required: true
    - name: patient_id
      type: string
      description: The patient ID (from lookup or registration)
      required: true
  return_raw_json: false
  error_message: I am sorry, I could not save your reminder preference. Please call us if you need a reminder.
  body_template: |
    {
      "appointmentId": {appointment_id},
      "patientId": {patient_id},
      "reminderType": "CALL",
      "minutesBefore": 60
    }
```

### 1.2  Add `save_followup_request` to the context tool lists

```yaml
contexts:
  default:
    in_call_http_tools:
      - register_patient
      - fetch_doctor_list
      - get_next_serial
      - book_appointment
      - save_followup_request    # ← add this
```

### 1.3  Update STATE 5 prompt block

Replace the current STATE 5 block with:

```
=========================================================
STATE 5 - BOOKING CONFIRMED
=========================================================
ENTRY: You arrive here after book_appointment returns successfully.
Say: "Your appointment is confirmed. Confirmation code [confirmation_code].
      [Day] [Date] at [start_time], serial number [serial_number], with [Doctor Name]."

When reading times, say only hours and minutes. Say "9:00 AM" not "09:00:00".
Do NOT spell out the confirmation code letter by letter. Read it as a word group.

Then ask: "Would you like me to give you a reminder call one hour before your appointment?"

Wait for explicit Yes or No.
  - Yes → Call save_followup_request with appointment_id and patient_id.
           Say: "Perfect! We will call you one hour before your appointment."
  - No  → Say: "No problem!"

Then ask: "Is there anything else I can help you with?"
  - If yes and patient wants to CANCEL:
      Ask: "Are you sure you want to cancel your appointment?"
      On Yes: Call cancel_appointment with appointment_id.
              Say: "Your appointment has been cancelled."
      Move to STATE 6.
  - If yes and patient wants to RESCHEDULE:
      Go back to STATE 3 (date selection) with the same doctor.
      After new booking, stay in STATE 5.
  - If no  → move to STATE 6.

If book_appointment fails:
  Say: "I am sorry, I was not able to confirm your booking right now."
  Ask: "Would you like to try a different date?" then go back to STATE 3.
```

---

## Part 2 — New In-Call Tools: `cancel_appointment` and `reschedule_appointment`

These tools are used in BOTH the inbound context (STATE 5) and the outbound reminder context.

### 2.1  `cancel_appointment`

```yaml
cancel_appointment:
  kind: in_call_http_lookup
  phase: in_call
  enabled: true
  is_global: false
  timeout_ms: 5000
  url: http://168.144.27.225/api/v1/appointments/{appointment_id}/cancel
  method: POST
  headers:
    Content-Type: application/json
    X-Tenant-ID: '1'
    X-API-Key: dev-api-key-replace-in-production
  query_params: {}
  success_status_codes: [200, 201]
  output_variables:
    cancel_success: success
    cancel_status: data.status
  description: >-
    Cancels an existing appointment. Call this ONLY after the patient explicitly
    confirms they want to cancel. Requires appointment_id.
    The appointment_id is the one returned by book_appointment (stored as appointment_id).
  parameters:
    - name: appointment_id
      type: string
      description: The ID of the appointment to cancel
      required: true
  return_raw_json: false
  error_message: I am sorry, I could not cancel your appointment right now. Please call us directly.
  body_template: |
    {
      "reason": "PATIENT_REQUEST"
    }
```

> **Note on URL path variable:** The engine supports `{appointment_id}` inside the URL string.
> It resolves the value from the AI's function call parameters before making the HTTP request.
> This was confirmed as a supported feature during earlier testing.

### 2.2  `reschedule_appointment`

If the HOS backend has a dedicated reschedule API (PATCH/PUT), use this tool.
If not (and rescheduling = cancel + rebook), skip this tool and handle it in the prompt flow
by calling `cancel_appointment` followed by re-running the doctor+date selection states.

```yaml
reschedule_appointment:
  kind: in_call_http_lookup
  phase: in_call
  enabled: true
  is_global: false
  timeout_ms: 5000
  url: http://168.144.27.225/api/v1/appointments/{appointment_id}/reschedule
  method: PATCH
  headers:
    Content-Type: application/json
    X-Tenant-ID: '1'
    X-API-Key: dev-api-key-replace-in-production
  query_params: {}
  success_status_codes: [200, 201]
  output_variables:
    reschedule_success: success
    new_appointment_id: data.id
    new_confirmation_code: data.confirmationCode
    new_start_time: data.startTime
    new_serial_number: data.serialNumber
  description: >-
    Reschedules an existing appointment to a new date with the same doctor.
    Call this ONLY after the patient confirms the new date and serial (go through
    get_next_serial first to confirm availability).
    Requires appointment_id, doctor_id, and new_appointment_date.
  parameters:
    - name: appointment_id
      type: string
      description: The ID of the appointment to reschedule
      required: true
    - name: doctor_id
      type: string
      description: The doctor ID (same doctor as original booking)
      required: true
    - name: new_appointment_date
      type: string
      description: New appointment date in YYYY-MM-DD format
      required: true
  return_raw_json: false
  error_message: I am sorry, I could not reschedule your appointment. Would you like to try a different date?
  body_template: |
    {
      "doctorId": {doctor_id},
      "newAppointmentDate": "{new_appointment_date}"
    }
```

---

## Part 3 — Outbound Trigger API ✅ IMPLEMENTED

The existing outbound API (`admin_ui/backend/api/outbound.py`) only supports campaign-based dialing.
A new dedicated file was created for the single-shot trigger so it can have its own auth (API key, no JWT).

### 3.1  What was built

| Item | Detail |
|---|---|
| New file | `admin_ui/backend/api/outbound_trigger.py` |
| Endpoint | `POST /api/outbound/trigger` |
| Auth | `X-Api-Key` header — checked against `OUTBOUND_TRIGGER_API_KEY` in `.env` |
| ARI call | Direct `aiohttp` POST to `http://{ASTERISK_HOST}:{ASTERISK_ARI_PORT}/ari/channels` |
| Channel vars | 7 vars passed: `AI_CONTEXT`, `PATIENT_ID`, `PATIENT_NAME`, `APPOINTMENT_ID`, `DOCTOR_NAME`, `APPOINTMENT_DATE`, `START_TIME` |
| `main.py` change | `trigger_router` registered **without** `Depends(get_current_user)` — all other outbound routes keep JWT |
| `.env.example` | `OUTBOUND_TRIGGER_API_KEY=` documented in new section |

### 3.2  Why a separate file (not added to `outbound.py`)

`outbound.py` is registered in `main.py` with `dependencies=[Depends(auth.get_current_user)]` — this applies to every route in the file. Adding the trigger there would force it to require JWT too, which defeats the purpose. A separate `trigger_router` is registered independently without the JWT dependency.

### 3.3  Authentication — API key (Option 3 implemented)

Three options were considered:

| Option | Verdict |
|---|---|
| Option 1 — HOS backend logs in, caches JWT 24h | Not implemented — token expiry means refresh logic needed in Java |
| Option 2 — Dedicated service user + JWT | Not implemented — same refresh problem |
| **Option 3 — Shared API key (`X-Api-Key`)** | **✅ Implemented** — no expiry, no login step, standard M2M pattern |

**How to configure:**

Step 1 — Add to `.env` on the AI engine server:
```
OUTBOUND_TRIGGER_API_KEY=your-strong-random-key-here
```
Generate with: `openssl rand -hex 32`

Step 2 — Restart admin_ui container:
```bash
docker compose restart admin_ui
```

Step 3 — HOS backend Java scheduler sends:
```
POST http://192.168.0.170:3003/api/outbound/trigger
X-Api-Key: your-strong-random-key-here
Content-Type: application/json
```

> **Security notes:**
> - If `OUTBOUND_TRIGGER_API_KEY` is empty/not set → endpoint returns **503 Disabled** (safe fail)
> - Wrong key → **401 Unauthorized**
> - The key lives only in `.env` (git-ignored) on each server — never committed to source control

### 3.4  Request and response

**Request body:**
```json
{
  "phone_number":     "+923001234567",
  "patient_id":       "42",
  "patient_name":     "Ahmed Khan",
  "appointment_id":   "101",
  "doctor_name":      "Dr. Hina Farooqi",
  "appointment_date": "2026-05-20",
  "start_time":       "09:00",
  "context":          "outbound_reminder",
  "caller_id":        "Smart Doctor Clinic"
}
```

`caller_id` is optional — falls back to `AAVA_OUTBOUND_EXTENSION_IDENTITY` from `.env`, then `"Smart Doctor Clinic"`.

**Success response (HTTP 200):**
```json
{
  "ok": true,
  "channel_id": "Local/+923001234567@from-internal-00000001",
  "phone_number": "+923001234567",
  "context": "outbound_reminder",
  "message": "Outbound call initiated"
}
```

**Error responses:**

| HTTP | Cause |
|---|---|
| 401 | Missing or wrong `X-Api-Key` |
| 503 | `OUTBOUND_TRIGGER_API_KEY` not set in `.env` |
| 502 | Cannot reach Asterisk ARI (Asterisk down or wrong host/port in `.env`) |
| 500 | Unexpected internal error |

### 3.5  How the ARI originate works

The endpoint does NOT use the engine's `ARIClient` Python class (that is a live object inside the engine process — not accessible from the admin_ui process). Instead it makes a direct HTTP call to the ARI REST API using `aiohttp` and the ARI credentials from `.env`:

```
POST http://{ASTERISK_HOST}:{ASTERISK_ARI_PORT}/ari/channels
Authorization: Basic base64(ARI_USERNAME:ARI_PASSWORD)
Content-Type: application/json

{
  "endpoint":   "Local/{phone}@from-internal",
  "app":        "asterisk-ai-voice-agent",
  "appArgs":    "outbound_reminder",
  "timeout":    "60",
  "callerId":   "Smart Doctor Clinic",
  "channelVars": {
    "AI_CONTEXT":       "outbound_reminder",
    "PATIENT_ID":       "42",
    "PATIENT_NAME":     "Ahmed Khan",
    "APPOINTMENT_ID":   "101",
    "DOCTOR_NAME":      "Dr. Hina Farooqi",
    "APPOINTMENT_DATE": "2026-05-20",
    "START_TIME":       "09:00",
    "CALL_TYPE":        "outbound_reminder"
  }
}
```

Asterisk dials `Local/{phone}@from-internal` → routes through the outbound dialplan → patient's phone rings → on answer, Stasis fires `StasisStart` on the engine → engine reads channel vars and starts the `outbound_reminder` AI session.

---

## Part 4 — Outbound Reminder Context (`outbound_reminder`)

Add a new context to `config/ai-agent.local.yaml`:

```yaml
contexts:
  default:
    # ... existing inbound context ...

  outbound_reminder:
    provider: deepgram
    greeting: "Hello, this is Ava calling from Smart Doctor Clinic."

    prompt: |
      You are Ava, an AI assistant for Smart Doctor Clinic.
      You have called the patient to remind them about their upcoming appointment.
      Be warm, concise, and professional.

      =========================================================
      APPOINTMENT DETAILS (injected before call):
      - patient_name:     {patient_name}
      - appointment_id:   {appointment_id}
      - doctor_name:      {doctor_name}
      - appointment_date: {appointment_date}
      - start_time:       {start_time}
      =========================================================

      =========================================================
      OUTBOUND REMINDER FLOW
      =========================================================

      STEP 1 - GREETING AND CONFIRM IDENTITY
      Say: "Hello, may I speak with {patient_name}?"
      If person says they are someone else: apologize and use hangup_call.
      If person confirms they are {patient_name}: move to STEP 2.

      STEP 2 - APPOINTMENT REMINDER
      Say: "This is a reminder that you have an appointment with {doctor_name}
            on [appointment_date spoken naturally] at {start_time}.
            Would you like to confirm, cancel, or reschedule?"

      Wait for their response:
        - "Confirm" / "Yes" / "I'll be there"  → Go to STEP 3 (Confirmed)
        - "Cancel"                              → Go to STEP 4 (Cancel)
        - "Reschedule"                          → Go to STEP 5 (Reschedule)
        - No answer / unclear                   → Ask once more, then say farewell and hangup.

      STEP 3 - CONFIRMED
      Say: "Wonderful! We look forward to seeing you. Have a great day!"
      Use hangup_call immediately after.

      STEP 4 - CANCEL
      Ask: "Are you sure you want to cancel your appointment with {doctor_name}?"
      On Yes: Call cancel_appointment with appointment_id = {appointment_id}.
              Say: "Your appointment has been cancelled. We hope to see you again soon."
              Use hangup_call.
      On No:  Return to STEP 2.

      STEP 5 - RESCHEDULE
      Say: "Of course! I can help you reschedule."
      Ask: "What date would you like instead?"
      Convert their answer to YYYY-MM-DD. Today is {today}.
      Confirm back the new date.
      On Yes: Call get_next_serial with the ORIGINAL doctor_id and new date.
              (You must look up doctor_id: it is not passed directly —
               call fetch_doctor_list if needed, or use the appointment context.)
              Show serial and estimated time.
              On patient confirms serial: Call reschedule_appointment with
              appointment_id={appointment_id}, doctor_id, new_appointment_date.
              Say: "Your appointment has been rescheduled to [new date] at [new time],
                    serial number [new_serial]. See you then!"
              Use hangup_call.
      On No (date):  Ask for another date.

      =========================================================
      GENERAL RULES
      =========================================================
      - You INITIATED this call. Introduce yourself immediately.
      - Keep responses to 1-2 sentences.
      - NEVER invent doctor names, times, or appointment details.
      - Do NOT read time seconds. Say "9:00 AM" not "09:00:00".
      - NEVER mention tool names to the caller.
      - Today's date: {today}.

    in_call_http_tools:
      - fetch_doctor_list
      - get_next_serial
      - cancel_appointment
      - reschedule_appointment

    tools:
      - hangup_call

    # No pre_call_tools needed — patient context injected via channel variables
    # from the /outbound/trigger API call
```

### 4.1  How channel variables reach the outbound prompt

When the HOS backend calls `POST /outbound/trigger`, the engine passes `channel_vars` to ARI's originate. Asterisk sets these as channel variables on the new call. The engine reads them at `StasisStart` (same as it reads `AI_CONTEXT`, `AI_PROVIDER`, `CALLERID`, etc.) and injects them into the prompt.

**Engine changes needed (src/engine.py, `StasisStart` handler):**

At the point where the engine builds the context variables for the prompt, add reading of the outbound-specific channel variables:

```python
# ── Murtuza change ──────────────────────────────────────────────────────────
# REASON: Outbound reminder calls pass patient/appointment context via
# Asterisk channel variables (set by originate_channel's channel_vars).
# Read them here so they are available as {patient_name}, {appointment_id},
# etc. in the outbound_reminder prompt without a pre-call HTTP lookup.
#
# Variables set by POST /outbound/trigger:
#   PATIENT_ID, PATIENT_NAME, APPOINTMENT_ID,
#   DOCTOR_NAME, APPOINTMENT_DATE, START_TIME, CALL_TYPE
# ── end Murtuza change ────────────────────────────────────────────────────────
outbound_patient_vars = {}
for var_name in ["PATIENT_ID", "PATIENT_NAME", "APPOINTMENT_ID",
                 "DOCTOR_NAME", "APPOINTMENT_DATE", "START_TIME", "CALL_TYPE"]:
    val = channel_vars.get(var_name, "")
    if val:
        outbound_patient_vars[var_name.lower()] = val  # e.g. patient_id, patient_name
```

These lowercase keys are then merged into the prompt template variables alongside the pre-call results.

---

## Part 5 — HOS Backend Java Scheduler

This section describes what the HOS backend team needs to build. The AI engine team has no changes here beyond confirming the API contract.

### 5.1  Data model

```sql
-- follow_up_requests table
CREATE TABLE follow_up_requests (
    id             BIGINT PRIMARY KEY AUTO_INCREMENT,
    appointment_id BIGINT NOT NULL,
    patient_id     BIGINT NOT NULL,
    reminder_type  VARCHAR(20) DEFAULT 'CALL',
    minutes_before INT DEFAULT 60,
    status         VARCHAR(20) DEFAULT 'PENDING',   -- PENDING, SENT, FAILED, CANCELLED
    scheduled_at   DATETIME NOT NULL,               -- appointment_time - 60 min
    triggered_at   DATETIME,
    created_at     DATETIME DEFAULT NOW()
);
```

### 5.2  Scheduler logic

```
Every minute:
  SELECT * FROM follow_up_requests
  WHERE status = 'PENDING'
  AND scheduled_at <= NOW() + interval 30 seconds

  For each row:
    POST http://192.168.0.170:3003/api/outbound/trigger
    X-Api-Key: <OUTBOUND_TRIGGER_API_KEY from .env>
    Content-Type: application/json
    {
      "phone_number":     patient.phone,
      "patient_id":       String(row.patient_id),
      "patient_name":     patient.fullName,
      "appointment_id":   String(row.appointment_id),
      "doctor_name":      doctor.fullName,
      "appointment_date": appointment.date (YYYY-MM-DD),
      "start_time":       appointment.startTime (HH:MM),
      "context":          "outbound_reminder"
    }

    On HTTP 200: UPDATE status = 'SENT', triggered_at = NOW()
    On HTTP 401: STOP — API key is wrong, alert ops team
    On HTTP 503: STOP — OUTBOUND_TRIGGER_API_KEY not configured, alert ops team
    On HTTP 502/5xx: UPDATE status = 'FAILED', retry after 5 minutes (max 3 attempts)
```

### 5.3  Save follow-up API (called by AI during inbound booking)

The AI engine calls this during STATE 5 of the inbound call:

```
POST /api/v1/tools/follow-ups
{
  "appointmentId": 101,
  "patientId": 42,
  "reminderType": "CALL",
  "minutesBefore": 60
}

Response 201:
{
  "success": true,
  "data": {
    "id": 15,
    "appointmentId": 101,
    "patientId": 42,
    "scheduledAt": "2026-05-20T08:00:00"
  }
}
```

---

## Part 6 — Cancel and Reschedule APIs (HOS Backend Contract)

The HOS backend team confirmed both APIs are ready. Here are the expected contracts for the AI engine tool definitions:

### 6.1  Cancel appointment

```
POST /api/v1/appointments/{appointmentId}/cancel
Body: { "reason": "PATIENT_REQUEST" }
Response 200: { "success": true, "data": { "status": "CANCELLED" } }
```

### 6.2  Reschedule appointment

```
PATCH /api/v1/appointments/{appointmentId}/reschedule
Body: { "doctorId": 1, "newAppointmentDate": "2026-05-22" }
Response 200:
{
  "success": true,
  "data": {
    "id": 102,
    "confirmationCode": "APT-X7K2",
    "startTime": "10:30:00",
    "serialNumber": 3
  }
}
```

---

## Part 7 — Implementation Checklist

### Phase 1 — Inbound follow-up opt-in (config only, no engine change)

- [ ] Add `save_followup_request` tool to `ai-agent.local.yaml`
- [ ] Add `cancel_appointment` tool to `ai-agent.local.yaml`
- [ ] Add `reschedule_appointment` tool to `ai-agent.local.yaml`
- [ ] Add all three to `contexts.default.in_call_http_tools`
- [ ] Update STATE 5 prompt block with follow-up question
- [ ] Add cancel/reschedule instructions to STATE 5 prompt
- [ ] Test: inbound call → booking → "Yes" to follow-up → verify POST hits `/api/v1/tools/follow-ups`
- [ ] Test: inbound call → "I want to cancel" → verify cancel API called

### Phase 2 — Outbound trigger API ✅ IMPLEMENTED

- [x] Created `admin_ui/backend/api/outbound_trigger.py` (new file, not added to `outbound.py`)
- [x] `POST /api/outbound/trigger` with `X-Api-Key` auth (no JWT)
- [x] ARI originate via direct `aiohttp` call — does not depend on engine's live ARIClient
- [x] `trigger_router` registered in `main.py` WITHOUT `Depends(get_current_user)`
- [x] `OUTBOUND_TRIGGER_API_KEY` added to `.env.example` with documentation
- [ ] Set `OUTBOUND_TRIGGER_API_KEY` in production `.env` (`openssl rand -hex 32`)
- [ ] Restart admin_ui container after setting the key
- [ ] Test with curl: `POST http://192.168.0.170:3003/api/outbound/trigger` with `X-Api-Key` header

### Phase 3 — Outbound context (config only)

- [ ] Add `outbound_reminder` context to `ai-agent.local.yaml`
- [ ] Add channel variable reading in `src/engine.py` StasisStart handler
- [ ] Test: manually trigger via API → outbound call arrives → Ava greets patient
- [ ] Test: patient says "cancel" → cancel API called → call ends

### Phase 4 — HOS backend (backend team)

- [ ] Create `follow_up_requests` table
- [ ] Implement `POST /api/v1/tools/follow-ups` endpoint
- [ ] Build scheduler that fires `POST /outbound/trigger` at T-60min
- [ ] Implement retry logic (max 3 attempts, 5-minute spacing)
- [ ] Handle status updates (SENT / FAILED)

### Phase 5 — Integration test

- [ ] End-to-end: Book appointment (inbound) → opt in to reminder → wait 1 hour → outbound call arrives → patient confirms → call ends
- [ ] Cancel flow: Outbound call → patient cancels → verify appointment status changes in HOS
- [ ] Reschedule flow: Outbound call → patient reschedules → verify new appointment created in HOS

---

## Part 8 — Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Who triggers outbound | HOS Java scheduler | HOS already has appointment data and scheduling logic. AI engine does not run a scheduler. |
| How context is passed to outbound Ava | Asterisk channel variables (no pre-call HTTP lookup) | Avoids an extra API call; all data already available in the trigger request |
| Cancel = single API call or cancel+rebook | Single API call (cancel_appointment) | Simpler flow; HOS has dedicated cancel endpoint |
| Reschedule = single API call or cancel+rebook | Single API call (reschedule_appointment) | HOS confirmed reschedule API is ready |
| Auth for /outbound/trigger | Shared API key (`X-Api-Key` / `OUTBOUND_TRIGGER_API_KEY`) ✅ | M2M calls don't suit JWT — no expiry, no login step, easy to rotate |
| ARI originate method | Direct `aiohttp` HTTP to ARI REST API | admin_ui and engine are separate processes — engine's live ARIClient is not accessible from admin_ui |
| Outbound dial endpoint | `Local/{phone}@from-internal` | Routes through FreePBX outbound dialplan; `AAVA_OUTBOUND_DIAL_CONTEXT` in `.env` controls the context |

---

## Part 9 — Asterisk Dialplan for Outbound Calls

Outbound calls originated by ARI (`Stasis`) skip the normal inbound dialplan. However, if the call is answered and the AI engine needs to do a regular stasis app, no extra dialplan is needed — ARI originate puts the channel directly into the Stasis app.

Confirm the PJSIP outbound trunk name in FreePBX:
- **Admin → Trunks → PJSIP Trunk** — note the trunk name
- Update the endpoint string in `/outbound/trigger`: `PJSIP/{phone_number}@<trunk_name>`

If the clinic uses a SIP trunk (not PJSIP), change to: `SIP/{phone_number}@<trunk_name>`

---

## Part 10 — Files Changed (Summary)

| File | Status | What changed |
|---|---|---|
| `admin_ui/backend/api/outbound_trigger.py` | ✅ Created | New file — `POST /api/outbound/trigger` with API key auth, direct ARI call via `aiohttp` |
| `admin_ui/backend/main.py` | ✅ Updated | Import `trigger_router`; register it WITHOUT `Depends(get_current_user)` |
| `.env.example` | ✅ Updated | Added `OUTBOUND_TRIGGER_API_KEY` section with generation instructions |
| `config/ai-agent.local.yaml` | ⏳ Pending | Add `save_followup_request`, `cancel_appointment`, `reschedule_appointment` tools; add `outbound_reminder` context; update STATE 5 prompt |
| `src/engine.py` | ⏳ Pending | Read outbound channel vars (`PATIENT_NAME`, `APPOINTMENT_ID`, etc.) at StasisStart and inject into prompt variables |
| HOS backend (Java) | ⏳ Pending | `follow_up_requests` table, save-followup API, scheduler, `POST /api/outbound/trigger` call with `X-Api-Key` |

---

## Appendix — API Quick Reference

| API | Method | URL | Caller |
|---|---|---|---|
| Save follow-up preference | POST | `/api/v1/tools/follow-ups` | AI engine (inbound, STATE 5) |
| Get next serial | GET | `/api/v1/appointments/next-serial?doctorId=&date=` | AI engine (in-call) |
| Book appointment | POST | `/api/v1/appointments` | AI engine (in-call) |
| Cancel appointment | POST | `/api/v1/appointments/{id}/cancel` | AI engine (in-call, both directions) |
| Reschedule appointment | PATCH | `/api/v1/appointments/{id}/reschedule` | AI engine (in-call, both directions) |
| Trigger outbound call | POST | `http://192.168.0.170:3003/api/outbound/trigger` — `X-Api-Key` header required | HOS Java scheduler |

---

## Appendix B — Outbound Trigger Quick Setup

```bash
# 1. Generate a strong API key
openssl rand -hex 32

# 2. Add to .env on the AI engine server
echo "OUTBOUND_TRIGGER_API_KEY=<generated-key>" >> .env

# 3. Restart admin_ui to pick up the new key
docker compose restart admin_ui

# 4. Test from any machine on the LAN
curl -s -X POST http://192.168.0.170:3003/api/outbound/trigger \
  -H "X-Api-Key: <generated-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+923001234567",
    "patient_id": "42",
    "patient_name": "Ahmed Khan",
    "appointment_id": "101",
    "doctor_name": "Dr. Hina Farooqi",
    "appointment_date": "2026-05-20",
    "start_time": "09:00",
    "context": "outbound_reminder"
  }'

# Expected response:
# {"ok":true,"channel_id":"Local/...","phone_number":"+923001234567","context":"outbound_reminder","message":"Outbound call initiated"}
```

---

*Last updated: 2026-05-19 — Part 3 updated to reflect actual implementation (API key auth, separate file, direct ARI call)*
