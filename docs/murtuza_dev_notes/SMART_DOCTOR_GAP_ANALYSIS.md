# Smart Doctor Clinic — Gap Analysis
## Appointment Booking & Reminder Voice Agent

**Date:** 2026-05-25  
**Author:** Murtuza Rahman  
**Version:** 1.0  
**Scope:** Inbound appointment booking (default context) + Outbound reminder call (outbound_reminder context)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Is Working Now](#2-what-is-working-now)
3. [Gap Summary Table](#3-gap-summary-table)
4. [Critical Gaps](#4-critical-gaps-must-fix-before-production)
5. [High Priority Gaps](#5-high-priority-gaps-fix-soon)
6. [Medium Priority Gaps](#6-medium-priority-gaps-next-sprint)
7. [Low Priority Gaps](#7-low-priority-gaps-future-roadmap)
8. [Bug Tracker](#8-bug-tracker-confirmed-bugs)
9. [Recommendations by Area](#9-recommendations-by-area)

---

## 1. Executive Summary

The core booking and reminder flows are functional and tested. The AI correctly books appointments, saves reminder requests, and handles outbound reminder calls. However, several gaps exist across security, reliability, business logic, and UX that must be addressed before the system handles real patients at scale.

**Total gaps found: 32**

| Priority | Count |
|----------|-------|
| 🔴 Critical | 4 |
| 🟠 High | 10 |
| 🟡 Medium | 11 |
| 🟢 Low | 7 |

---

## 2. What Is Working Now

| Feature | Status | Notes |
|---------|--------|-------|
| Inbound call — patient identification | ✅ Working | Lookup by caller_number, register if not found |
| Doctor list presentation | ✅ Working | Natural spoken format, no numbers/dashes |
| Date selection and get_next_serial | ✅ Working | Confirms availability before proceeding |
| Appointment booking (book_appointment) | ✅ Working | Returns confirmation_code, start_time, serial_number |
| Reminder call request (save_followup_request) | ✅ Working | Patient opts in after booking |
| Cancel appointment (inbound) | ✅ Working | With double-confirm before calling cancel_appointment |
| Reschedule appointment (inbound) | ✅ Working | Goes back to STATE 3 with same doctor |
| Outbound trigger API | ✅ Working | POST /api/outbound/trigger with X-Api-Key |
| Outbound patient data via appArgs | ✅ Working | Zero race condition, no channel var reads |
| Outbound reminder conversation | ✅ Working | Confirm / cancel / reschedule / busy branches |
| Post-call call log | ✅ Working | smart_doctor_call_log fires after every call |
| AI context routing | ✅ Working | default vs outbound_reminder correctly selected |

---

## 3. Gap Summary Table

| # | Priority | Category | Gap | File(s) Affected |
|---|----------|----------|-----|-----------------|
| G1 | 🔴 Critical | Security | All API calls use plain HTTP — patient PII unencrypted | `ai-agent.local.yaml` |
| G2 | 🔴 Critical | Security | `dev-api-key-replace-in-production` in all tool headers | `ai-agent.local.yaml` |
| G3 | 🔴 Critical | Reliability | `_outbound_reminder_vars` is in-memory — lost on engine restart | `engine.py` |
| G4 | 🔴 Critical | Bug | call_log `appointmentId` field sends `call_id` instead of `appointment_id` | `ai-agent.local.yaml` |
| G5 | 🟠 High | Reliability | No cleanup of stale `_outbound_reminder_vars` entries (memory leak) | `engine.py` |
| G6 | 🟠 High | Business Logic | No doctor availability filter — shows all doctors even if fully booked | `ai-agent.local.yaml` |
| G7 | 🟠 High | Business Logic | No duplicate appointment prevention | Backend API (HOS) |
| G8 | 🟠 High | Outbound | No retry / voicemail if patient does not answer | `engine.py`, `outbound_trigger.py` |
| G9 | 🟠 High | Outbound | No callback to HOS backend with call outcome (answered / not answered) | `outbound_trigger.py` |
| G10 | 🟠 High | Business Logic | `doctor_id` not available in outbound context for reschedule | `ai-agent.local.yaml`, `engine.py` |
| G11 | 🟠 High | Security | No rate limiting on `/api/outbound/trigger` | `outbound_trigger.py` |
| G12 | 🟠 High | Reliability | `timeout_ms: 2000` for name_look_up is too tight for Java backend under load | `ai-agent.local.yaml` |
| G13 | 🟠 High | Dead Code | `check_doctor_slots` and `get_existing_appointments` defined but not used in any context | `ai-agent.local.yaml` |
| G14 | 🟠 High | Business Logic | No response when get_next_serial returns "no slots available" (fully booked day) | `ai-agent.local.yaml` |
| G15 | 🟡 Medium | Reliability | No idempotency key on book_appointment — network retry could double-book | Backend API (HOS) |
| G16 | 🟡 Medium | Integration | `reschedule_appointment` URL uses `/api/v1/appointments/` (not `/api/v1/tools/`) — inconsistent base path | `ai-agent.local.yaml` |
| G17 | 🟡 Medium | Security | Patient PII (name, phone, IDs) visible in Asterisk logs via appArgs | `outbound_trigger.py`, `engine.py` |
| G18 | 🟡 Medium | UX | No "please wait" signal while tool calls are running (silence feels like dead air) | `engine.py` |
| G19 | 🟡 Medium | UX | No transfer to human / operator fallback | `ai-agent.local.yaml` |
| G20 | 🟡 Medium | Business Logic | No clinic hours check — patients could book at midnight | `ai-agent.local.yaml` |
| G21 | 🟡 Medium | Business Logic | No appointment conflict check for same patient same time different doctor | Backend API (HOS) |
| G22 | 🟡 Medium | Reliability | Admin UI save re-compacts YAML to escaped format — manual edits lost on next UI save | Admin UI backend |
| G23 | 🟡 Medium | Monitoring | No Prometheus metrics or alerting for tool call success/failure rates | `engine.py` |
| G24 | 🟡 Medium | Reliability | No circuit breaker on HOS backend calls — cascading failure if backend is slow | `engine.py` |
| G25 | 🟡 Medium | UX | No DTMF fallback — if STT fails, patient cannot use keypad | `engine.py`, dialplan |
| G26 | 🟡 Medium | Config | `sample_gohighlevel_pre_call_lookup: null` — leftover dead config entry | `ai-agent.local.yaml` |
| G27 | 🟢 Low | UX | No specialty-based doctor search ("I need a cardiologist") | `ai-agent.local.yaml`, Backend |
| G28 | 🟢 Low | UX | No time-of-day preference ("morning" or "afternoon" slot) | `ai-agent.local.yaml` |
| G29 | 🟢 Low | Feature | No SMS / email confirmation after booking | Backend (HOS) |
| G30 | 🟢 Low | Feature | No appointment history query ("what appointments do I have?") | Backend (HOS), `ai-agent.local.yaml` |
| G31 | 🟢 Low | Feature | No multi-language support | `engine.py`, Deepgram config |
| G32 | 🟢 Low | Feature | No family booking ("I want to book for my mother") | `ai-agent.local.yaml`, Backend |

---

## 4. Critical Gaps (Must Fix Before Production)

---

### G1 🔴 — Plain HTTP for All HOS Backend Calls

**Category:** Security  
**File:** `config/ai-agent.local.yaml` — all tool URLs

**Problem:**  
Every tool call (name_look_up, book_appointment, cancel_appointment, etc.) sends
patient data over plain HTTP to `http://168.144.27.225`. This exposes:
- Patient full name and phone number (name_look_up, register_patient)
- Appointment IDs and confirmation codes (book_appointment)
- Call transcripts (smart_doctor_call_log)

All of this data is transmitted in the clear on the network.

**Current:**
```yaml
url: http://168.144.27.225/api/v1/tools/patients/lookup
```

**Fix:**
```yaml
url: https://168.144.27.225/api/v1/tools/patients/lookup
# Or use a domain name with valid TLS certificate:
url: https://api.smartdoctor.pk/api/v1/tools/patients/lookup
```

Also add to the HOS backend `.env`:
```
AAVA_HOS_BASE_URL=https://api.smartdoctor.pk
```

**Effort:** Low (URL change + TLS cert on HOS backend)  
**Impact:** High — HIPAA/PDPA compliance, patient data protection

---

### G2 🔴 — API Key Hardcoded as Development Value

**Category:** Security  
**File:** `config/ai-agent.local.yaml` — all tool headers

**Problem:**  
Every tool header contains:
```yaml
X-API-Key: dev-api-key-replace-in-production
```
This is committed to the YAML and is the same key in every tool. If the file is
ever exposed (logs, backup, accidental git commit), all API access is compromised.
The key has no expiry and cannot be rotated without editing every tool definition.

**Fix:**  
1. Move the API key to `.env`:
   ```
   HOS_API_KEY=your-production-key-here
   ```
2. Reference it as a variable in tool headers (if the engine supports env var
   interpolation in headers):
   ```yaml
   X-API-Key: "{HOS_API_KEY}"
   ```
   OR change to a single shared header defined in the base config rather than
   repeating it in every tool definition.

**Effort:** Medium (engine header interpolation may need code change)  
**Impact:** High — prevents key rotation, single point of credential exposure

---

### G3 🔴 — `_outbound_reminder_vars` Lost on Engine Restart

**Category:** Reliability  
**File:** `src/engine.py` — `_handle_stasis_start`

**Problem:**  
Patient data parsed from appArgs is cached in `self._outbound_reminder_vars[channel_id]`
on the engine Python object. If the engine restarts (crash, deploy, OOM kill) after
ARI has originated the call but before StasisStart fires, the dict is gone. The
outbound call proceeds with no patient data — Ava says the literal text
`{patient_name}`, `{doctor_name}`, etc.

There is also no cleanup: if a channel enters Stasis but crashes before
`_handle_caller_stasis_start_hybrid` pops the entry, the dict grows indefinitely.

**Current code:**
```python
if not hasattr(self, "_outbound_reminder_vars"):
    self._outbound_reminder_vars: dict = {}
self._outbound_reminder_vars[channel_id] = _parsed_data
```

**Fix options (choose one):**
- **Option A (simple):** Use Redis or SQLite to persist the dict between restarts.
- **Option B (best):** Add a cleanup task that deletes entries older than 5 minutes.
  ```python
  import time
  # Store with timestamp: {"data": {...}, "ts": time.time()}
  # Cleanup: remove entries where time.time() - entry["ts"] > 300
  ```
- **Option C (architectural):** Pass appArgs directly through to the AI session
  as pre_call_results without caching — parse in `_handle_caller_stasis_start_hybrid`
  directly from `args[]`.

**Effort:** Low–Medium  
**Impact:** High — prevents silent template variable failure on restart

---

### G4 🔴 — call_log Bug: `appointmentId` Sends `call_id` Instead of `appointment_id`

**Category:** Bug  
**File:** `config/ai-agent.local.yaml` — `smart_doctor_call_log.payload_template`

**Problem:**  
The post-call webhook payload has:
```json
"appointmentId": "{call_id}"
```
It should be:
```json
"appointmentId": "{appointment_id}"
```
`call_id` is the Asterisk channel UUID (e.g. `1716234567.42`). The HOS backend
receives a random string instead of the actual appointment ID, making it impossible
to link the call log to the correct appointment.

**Fix:**
```yaml
payload_template: |
  {
    "sessionId":        "{call_id}",
    "callerPhone":      "{caller_number}",
    "patientId":        "{patient_id}",
    "appointmentId":    "{appointment_id}",   # ← fix here
    ...
  }
```

**Effort:** Trivial (one-line YAML change)  
**Impact:** High — call logs cannot be linked to appointments without this fix

---

## 5. High Priority Gaps (Fix Soon)

---

### G5 🟠 — Memory Leak in `_outbound_reminder_vars`

**Category:** Reliability  
**File:** `src/engine.py`

**Problem:**  
Entries are added to `_outbound_reminder_vars` when the ARI originate fires.
They are removed (`.pop()`) when `_handle_caller_stasis_start_hybrid` runs.
If the call fails to enter Stasis (Asterisk rejects, timeout, channel error),
the entry is never popped. Over time this leaks memory — especially if the
HOS scheduler fires many reminders.

**Fix:**
```python
# Add a periodic cleanup task (every 10 minutes)
async def _cleanup_outbound_reminder_vars(self):
    while True:
        await asyncio.sleep(600)
        now = time.time()
        stale = [k for k, v in self._outbound_reminder_vars.items()
                 if now - v.get("_ts", now) > 300]
        for k in stale:
            self._outbound_reminder_vars.pop(k, None)
        if stale:
            logger.info("Cleaned up %d stale outbound_reminder_vars entries", len(stale))
```

**Effort:** Low  
**Impact:** Medium (production stability over time)

---

### G6 🟠 — No Doctor Availability Filter

**Category:** Business Logic  
**File:** `ai-agent.local.yaml`, Backend (HOS)

**Problem:**  
`fetch_doctor_list` returns **all** doctors in the system regardless of whether
they are working on the date the patient wants. The patient might choose a doctor
who has no slots that day, causing:
1. `get_next_serial` to fail or return nothing
2. Confusion — Ava offered a doctor who is not available
3. Wasted conversation time re-selecting a doctor

**Current flow:**
```
STATE 2 → fetch_doctor_list (all doctors) → patient picks → STATE 3 (get_next_serial may fail)
```

**Better flow:**
```
STATE 2 → ask for preferred date first → fetch_doctor_list?date=YYYY-MM-DD (available only)
       → patient picks from available list → STATE 3 (guaranteed slot exists)
```

**Fix options:**
- Add `date` query parameter to `fetch_doctor_list` (HOS backend change)
- Or: move date question before doctor question in the prompt state machine

**Effort:** Medium (backend API change + prompt state machine reorder)  
**Impact:** High — fewer dead-end conversations

---

### G7 🟠 — No Duplicate Appointment Prevention

**Category:** Business Logic  
**File:** Backend (HOS)

**Problem:**  
Nothing prevents a patient from booking the same doctor on the same day multiple
times in the same call (or across calls). The AI state machine moves forward
after each booking but there is no check at the API level.

**Fix:**  
HOS backend `book_appointment` endpoint should check for existing appointments
for the same `patientId + doctorId + appointmentDate` and return a 409 Conflict
if one exists. Ava should handle the error response:
```
"It looks like you already have an appointment with that doctor on that date."
```

**Effort:** Low (backend validation change)  
**Impact:** High — prevents duplicate bills, scheduling chaos

---

### G8 🟠 — No Retry / Voicemail for Unanswered Outbound Calls

**Category:** Outbound  
**File:** `admin_ui/backend/api/outbound_trigger.py`, `engine.py`

**Problem:**  
When the outbound call is originated and the patient does not answer:
- Asterisk rings for 60 seconds (timeout) then drops the channel
- No second attempt is made
- HOS backend has no way to know the call was not answered
- No voicemail message is left

A significant percentage of patients will not answer their first reminder call
(busy, driving, phone silenced). Currently those patients get no reminder at all.

**Fix options:**
- **Retry:** HOS scheduler re-triggers after 15 minutes if no callback is received
  from G9 (outcome webhook)
- **Voicemail (AMD):** Use Asterisk `AMD()` dialplan application to detect
  answering machines and play a recorded message
- **SMS fallback:** If call not answered, send SMS (requires SMS gateway integration)

**Effort:** Medium–High  
**Impact:** High — core purpose of reminder calls

---

### G9 🟠 — No Outcome Callback to HOS Backend

**Category:** Outbound  
**File:** `outbound_trigger.py`, `engine.py`

**Problem:**  
After the outbound trigger fires, HOS backend gets a `200 OK` with a `channel_id`.
It has no way to know:
- Did the patient answer?
- Was the appointment confirmed, cancelled, or rescheduled?
- Did the call fail (no answer, busy, error)?

The `smart_doctor_call_log` post-call webhook fires but it goes to `/api/v1/tools/call-logs`
which is a generic log — it is not tied back to the outbound trigger.

**Fix:**  
Add an `outcome_webhook_url` optional field to `OutboundTriggerRequest`.
After the call ends, post the outcome:
```json
POST {outcome_webhook_url}
{
  "appointment_id": "123",
  "outcome": "confirmed" | "cancelled" | "rescheduled" | "no_answer" | "busy" | "error",
  "called_at": "2026-05-25T09:00:00Z",
  "duration_seconds": 45
}
```

**Effort:** Medium  
**Impact:** High — HOS backend needs this to manage follow-up actions

---

### G10 🟠 — `doctor_id` Not Available in Outbound Reschedule Flow

**Category:** Business Logic  
**File:** `ai-agent.local.yaml`, `outbound_trigger.py`

**Problem:**  
When a patient on an outbound reminder call says "I want to reschedule", Ava
needs to call `reschedule_appointment` with `doctor_id`. But the outbound trigger
only sends:
```
patient_name, doctor_name, appointment_date, start_time, appointment_id, patient_id
```
`doctor_id` (the integer ID, not the name) is **not passed**. Ava has `doctor_name`
but not `doctor_id`, so `get_next_serial` and `reschedule_appointment` cannot be
called correctly.

**Current prompt fallback:**
```
"use the doctor from context if available, otherwise ask the patient to call the clinic"
```
This means reschedule silently fails if `doctor_id` is not in context.

**Fix:**  
Add `doctor_id` to `OutboundTriggerRequest` and include it in appArgs:

In `outbound_trigger.py`:
```python
class OutboundTriggerRequest(BaseModel):
    ...
    doctor_id: str = Field(..., description="Doctor ID — needed for reschedule flow")
```

In `ai-agent.local.yaml` outbound prompt — add to APPOINTMENT DETAILS block:
```
- Doctor ID: {doctor_id}
```

**Effort:** Low  
**Impact:** High — reschedule feature is broken without this

---

### G11 🟠 — No Rate Limiting on `/api/outbound/trigger`

**Category:** Security  
**File:** `admin_ui/backend/api/outbound_trigger.py`

**Problem:**  
A bug in the HOS Java scheduler (or a replay attack with a stolen API key) could
send thousands of trigger requests in seconds. Each request originates a real
Asterisk channel. This could:
- Flood the patient with calls
- Exhaust Asterisk channel capacity
- Create thousands of appointments/cancellations

**Fix:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@trigger_router.post("/trigger")
@limiter.limit("60/minute")  # max 60 outbound calls per minute from any single IP
async def trigger_outbound_call(req: OutboundTriggerRequest, ...):
    ...
```

Also add per-patient dedup: reject a second trigger for the same `appointment_id`
within a 30-minute window.

**Effort:** Low  
**Impact:** High — prevents runaway billing and patient harassment

---

### G12 🟠 — `name_look_up` Timeout Too Tight (2000ms)

**Category:** Reliability  
**File:** `config/ai-agent.local.yaml` — `name_look_up` tool

**Problem:**  
`timeout_ms: 2000` (2 seconds) for the pre-call lookup. If the HOS Java backend
is under load, JVM GC pause, or cold-starting, it may take 2–4 seconds to respond.
A timeout causes `lookup_success = false`, which forces the patient through the
full registration flow even if they are already registered. This creates duplicate
patient records and a worse experience for returning patients.

**Fix:**
```yaml
name_look_up:
  timeout_ms: 5000   # match other tools
```

**Effort:** Trivial  
**Impact:** High — prevents false "new patient" registrations for existing patients

---

### G13 🟠 — `check_doctor_slots` and `get_existing_appointments` Are Dead Code

**Category:** Dead Code  
**File:** `config/ai-agent.local.yaml`

**Problem:**  
Two tools are fully defined with URLs, parameters, and output_variables but are
not listed in any context's `in_call_http_tools`:
- `check_doctor_slots` — checks slot availability
- `get_existing_appointments` — lists booked appointments for a doctor+date

The AI cannot call tools it does not have access to. These tools are effectively
dead weight in the config.

**Fix — Option A (enable them):**  
Add to the `default` context `in_call_http_tools` if the HOS backend endpoints
are working and you want to use them for conflict checking.

**Fix — Option B (remove them):**  
Delete both tool definitions from `ai-agent.local.yaml` to reduce config size
and avoid confusion.

**Effort:** Trivial  
**Impact:** Medium — config clarity; slot checking is a real gap (related to G6)

---

### G14 🟠 — No "Fully Booked" Handling in Prompt

**Category:** Business Logic  
**File:** `config/ai-agent.local.yaml` — default context prompt STATE 3

**Problem:**  
The prompt tells Ava: "If get_next_serial fails, apologize and ask if they want
a different date." But it does not cover the case where `get_next_serial` succeeds
but returns 0 serials (doctor fully booked for that day). Ava may try to proceed
with `next_serial = 0` and `estimated_time = null`, reading "Your serial number
will be 0" to the patient.

**Fix — add to STATE 3 prompt:**
```
- If next_serial is 0 or null:
  Say: "I am sorry, Dr. [Name] is fully booked on that date.
        Would you like to try a different date?"
  Stay in STATE 3.
```

**Effort:** Trivial (prompt change)  
**Impact:** High — prevents "serial 0" being read to patients

---

## 6. Medium Priority Gaps (Next Sprint)

---

### G15 🟡 — No Idempotency Key on `book_appointment`

**Category:** Reliability  
**File:** Backend (HOS)

If the engine sends `book_appointment` and the backend processes it but the
HTTP response is lost (network blip), the engine may retry — creating two
bookings for the same patient. The HOS backend should accept an idempotency
key header (`X-Idempotency-Key`) and return the existing booking if the same
key is seen twice.

---

### G16 🟡 — `reschedule_appointment` URL Path Inconsistency

**Category:** Integration  
**File:** `config/ai-agent.local.yaml`

All tools use the base path `/api/v1/tools/...`:
```
/api/v1/tools/appointments
/api/v1/tools/appointments/cancel
/api/v1/tools/follow-ups
```

But reschedule uses a different base:
```
/api/v1/appointments/{appointment_id}/reschedule
```

This suggests it may be a different HOS backend controller and may behave
differently (different auth, different response format). Verify this endpoint
exists and returns the expected fields before relying on it.

---

### G17 🟡 — Patient PII Visible in Asterisk Logs via appArgs

**Category:** Security  
**File:** `outbound_trigger.py`, `engine.py`

ARI appArgs are logged by Asterisk at INFO level. The current format:
```
appArgs=outbound_reminder,patient_name=Ahmed Khan|doctor_name=Dr. Hina|appointment_id=456
```
means every patient name, appointment ID, and doctor name appears in Asterisk
log files in plain text. Log files may be shipped to monitoring systems,
stored indefinitely, or accessed by system administrators without healthcare
data access.

**Fix:**  
- Encrypt the payload in appArgs (base64 + AES), decrypt in engine.py.
- Or use a short-lived token: store data in Redis with a UUID key, pass only
  the UUID in appArgs, engine fetches data from Redis by UUID.

---

### G18 🟡 — No "Please Wait" While Tool Calls Run

**Category:** UX  
**File:** `engine.py`, Deepgram config

When Ava calls `book_appointment` or `fetch_doctor_list`, there is 1–3 seconds
of complete silence from the AI. To a patient on the phone, silence sounds like
the call dropped. A filler phrase should be spoken before the tool call:
- "One moment while I check availability..."
- "Let me book that for you right now..."

This requires the provider to support a "thinking filler" or the engine to
play a pre-recorded audio file during tool execution.

---

### G19 🟡 — No Transfer to Human / Operator Fallback

**Category:** UX  
**File:** `config/ai-agent.local.yaml`

If the patient becomes frustrated, the AI cannot understand them, or an error
occurs repeatedly, there is no way to escalate to a human operator. Best practice
for healthcare voice bots is to always offer "press 0 or say operator to speak
with someone."

**Fix:**  
Add `transfer_call` to the context tools and add to the prompt:
```
If the patient says "operator", "human", "agent", "help", or becomes frustrated:
  Say: "Let me transfer you to our reception desk."
  Call transfer_call with the clinic reception extension.
```

---

### G20 🟡 — No Clinic Hours Validation

**Category:** Business Logic  
**File:** `config/ai-agent.local.yaml`

A patient can call and book an appointment at 2:00 AM (if the AI engine is
running 24/7). The date selection has no check for clinic opening hours or
days off. `get_next_serial` will return a real serial number even for a
Sunday if the doctor has no schedule block.

**Fix:**  
Add clinic hours to the prompt's GENERAL RULES section:
```
Clinic hours: Monday–Saturday, 9:00 AM – 6:00 PM (PKT).
If the patient requests a date that falls on a Sunday or a public holiday,
say: "Our clinic is closed on that day. May I suggest the next available day?"
```

---

### G21 🟡 — No Patient Appointment Conflict Check

**Category:** Business Logic  
**File:** Backend (HOS)

If a patient already has an appointment at 10:00 AM with Dr. A and tries to
book with Dr. B also at 10:00 AM on the same day, the system will accept both.
The HOS backend should validate for patient-level time conflicts.

---

### G22 🟡 — Admin UI Save Re-Compacts the YAML

**Category:** Config Management  
**File:** Admin UI backend (YAML serializer)

Every time the config is saved through the Admin UI, the entire
`ai-agent.local.yaml` is serialized by PyYAML's default serializer, which
converts block scalars back to single-line escaped strings with `\n`, `\"`,
and `—` escapes. Manual edits to keep the file human-readable are lost
after one Admin UI save.

**Fix:**  
In the Admin UI backend YAML save path, use a YAML dumper with `width=9999`
and `default_flow_style=False`:
```python
import yaml

class LiteralString(str): pass

def literal_representer(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(str, literal_representer)
yaml.dump(config, stream, allow_unicode=True, default_flow_style=False, width=9999)
```

---

### G23 🟡 — No Tool Call Metrics / Alerting

**Category:** Monitoring  
**File:** `engine.py`

There are no Prometheus counters for tool call success/failure rates. If
`book_appointment` starts returning errors (HOS backend down), there is no alert.
Operators only find out when patients call to complain.

**Fix:**  
Add counters around tool call execution:
```python
tool_call_counter = Counter('aava_tool_calls_total', 'Tool calls', ['tool_name', 'status'])
# status = 'success' | 'error' | 'timeout'
```

---

### G24 🟡 — No Circuit Breaker on HOS Backend Calls

**Category:** Reliability  
**File:** `engine.py`

If the HOS backend becomes slow (e.g., DB lock), every tool call takes 5 seconds
to timeout. With 10 concurrent calls, this creates 10 × 8 tools = 80 pending
HTTP connections. The engine may exhaust its connection pool and crash.

**Fix:**  
Use a circuit breaker pattern (e.g., `pybreaker` library). After 5 consecutive
failures, open the circuit for 30 seconds and fail fast with a friendly message.

---

### G25 🟡 — No DTMF Fallback

**Category:** UX  
**File:** `engine.py`, dialplan

If the patient's microphone is muffled, they are in a noisy environment, or
Deepgram STT fails repeatedly, there is no fallback. The patient cannot press
`1` to confirm or `2` to cancel. Healthcare voice bots commonly use DTMF as
a fallback for accessibility.

---

### G26 🟡 — Dead Config Entry

**Category:** Config  
**File:** `config/ai-agent.local.yaml`

```yaml
sample_gohighlevel_pre_call_lookup: null
```
This is a leftover entry from the base template. It serves no purpose and
adds noise to the config file.

**Fix:** Delete this line.

---

## 7. Low Priority Gaps (Future Roadmap)

---

### G27 🟢 — No Specialty-Based Doctor Search

Patients often say "I need to see a cardiologist" rather than a doctor name.
Currently, the AI reads the entire doctor list and relies on the patient to
match specialties mentally. A better UX would filter by specialty first.

**Fix:** Add an optional `specialty` filter to `fetch_doctor_list` API and
add prompt logic: "If the patient mentions a specialty, filter the list."

---

### G28 🟢 — No Time-of-Day Preference

Patients often have preferences ("morning only" or "after 3 PM"). `get_next_serial`
returns the next available serial but does not filter by time window. Add
optional `preferredTimeFrom` and `preferredTimeTo` query parameters.

---

### G29 🟢 — No SMS / Email Confirmation

After booking, patients expect a confirmation message (SMS or email) with the
confirmation code, doctor name, date, and time. Currently there is no mechanism
for this. The HOS backend should send a confirmation after `book_appointment`
succeeds.

---

### G30 🟢 — No Appointment History Query

A patient calling back might ask "What appointments do I have?" There is no
`get_patient_appointments` tool. Add a `GET /api/v1/tools/patients/{id}/appointments`
endpoint and corresponding tool.

---

### G31 🟢 — No Multi-Language Support

The clinic likely serves Urdu and English speaking patients. Currently the
prompt and greeting are English-only. Deepgram supports Urdu and mixed
Urdu/English (code-switching). A language detection step at STATE 1 could
switch to the appropriate language prompt.

---

### G32 🟢 — No Family Booking

Patients sometimes call to book for a family member ("I want to book for my
wife, Fatima Khan"). The current flow assumes the caller is the patient. A
"booking for someone else" branch would need to collect the family member's
name separately and look them up (or register them) before booking.

---

## 8. Bug Tracker (Confirmed Bugs)

These are confirmed code-level bugs, distinct from the feature gaps above.

| # | Severity | Description | File | Fix |
|---|----------|-------------|------|-----|
| B1 | 🔴 High | `appointmentId` in call_log payload sends `call_id` (channel UUID) instead of `appointment_id` | `ai-agent.local.yaml` line ~551 | Change `"{call_id}"` to `"{appointment_id}"` |
| B2 | 🟠 Medium | `_outbound_reminder_vars` entries never cleaned up if channel fails to enter Stasis | `engine.py` | Add TTL-based cleanup task |
| B3 | 🟡 Low | `get_existing_appointments` has an empty parameter entry (`name: ''`) — was likely added by UI accident | `ai-agent.local.yaml` | Remove the blank parameter |
| B4 | 🟡 Low | `name_look_up` `body_template` in current file has extra blank lines inside JSON body | `ai-agent.local.yaml` | Already fixed in latest rewrite |

---

## 9. Recommendations by Area

### Immediate (This Week)

1. **Fix G4** — Change `appointmentId` in call_log from `call_id` to `appointment_id` — one line change
2. **Fix G12** — Increase `name_look_up` timeout from 2000ms to 5000ms — one line change  
3. **Fix G10** — Add `doctor_id` to outbound trigger request and appArgs
4. **Fix G14** — Add "fully booked day" handling to STATE 3 prompt
5. **Fix G13** — Remove or enable dead tools (`check_doctor_slots`, `get_existing_appointments`)
6. **Fix B3** — Remove empty parameter from `get_existing_appointments`
7. **Fix G26** — Remove `sample_gohighlevel_pre_call_lookup: null`

### Short Term (Next 2 Weeks)

8. **Fix G1** — Migrate all HOS API URLs to HTTPS
9. **Fix G2** — Move API key to environment variable
10. **Fix G3 + G5** — Add TTL-based cleanup for `_outbound_reminder_vars`
11. **Fix G8 + G9** — Design outbound call outcome webhook (HOS backend + engine)
12. **Fix G11** — Add rate limiting on `/api/outbound/trigger`
13. **Fix G19** — Add `transfer_call` to contexts with "say operator" handler
14. **Fix G20** — Add clinic hours to prompt GENERAL RULES

### Medium Term (Next Month)

15. **Fix G6** — Doctor availability filter (HOS backend + prompt flow change)
16. **Fix G7** — Duplicate appointment prevention (HOS backend validation)
17. **Fix G15** — Idempotency key on book_appointment
18. **Fix G22** — Admin UI YAML serializer — preserve block scalars on save
19. **Fix G23** — Prometheus metrics for tool call success/failure
20. **Fix G18** — "Please wait" filler audio during tool calls

### Future Roadmap (Q3 2026)

21. G27 — Specialty-based doctor search  
22. G28 — Time-of-day preference  
23. G29 — SMS/email confirmation  
24. G30 — Appointment history query  
25. G31 — Multi-language (Urdu) support  
26. G32 — Family booking flow  

---

*This document should be reviewed and updated after each sprint.*  
*Priority ratings assume a production clinic environment with real patient data.*
