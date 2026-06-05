# Smart Doctor Clinic — Feature Gap Analysis
## AI Voice Agent — What's Built vs What's Needed

**Date:** 2026-05-25
**Author:** Murtuza Rahman
**Version:** 1.0
**Scope:** Product-level features missing from the current booking + reminder implementation

> **Note:** This document covers *missing product features*.
> For technical/security/reliability gaps see `SMART_DOCTOR_GAP_ANALYSIS.md`.

---

## Table of Contents

1. [What Is Built Today](#1-what-is-built-today)
2. [Feature Gap Summary](#2-feature-gap-summary)
3. [Patient Self-Service Features](#3-patient-self-service-features)
4. [Appointment Scheduling Features](#4-appointment-scheduling-features)
5. [Outbound & Notification Features](#5-outbound--notification-features)
6. [Clinic Operations Features](#6-clinic-operations-features)
7. [Patient Experience Features](#7-patient-experience-features)
8. [Analytics & Reporting Features](#8-analytics--reporting-features)
9. [Integration Features](#9-integration-features)
10. [Priority Roadmap](#10-priority-roadmap)
11. [Effort vs Impact Matrix](#11-effort-vs-impact-matrix)

---

## 1. What Is Built Today

```
INBOUND CALL (default context)
───────────────────────────────
✅ Identify patient by caller phone number
✅ Register new patient if not found
✅ Present available doctors by name and specialty
✅ Ask for preferred date
✅ Get next available serial number and estimated time
✅ Confirm and book the appointment
✅ Offer reminder call opt-in (1 hour before)
✅ Cancel the appointment just booked (same call)
✅ Reschedule the appointment just booked (same call)
✅ Warm farewell and hangup
✅ Post-call: log call to HOS backend

OUTBOUND CALL (outbound_reminder context)
──────────────────────────────────────────
✅ Triggered by HOS scheduler 1 hour before appointment
✅ Confirm patient identity
✅ Deliver appointment reminder (doctor, date, time)
✅ Handle patient confirmation ("I'll be there")
✅ Cancel appointment on patient request
✅ Reschedule appointment on patient request
✅ Handle busy / wrong time gracefully
✅ Hangup after every terminal action
```

**Total features working: 19**

---

## 2. Feature Gap Summary

| # | Feature | Category | Priority | Effort | Impact |
|---|---------|----------|----------|--------|--------|
| F01 | View existing appointments ("What do I have booked?") | Self-service | 🔴 High | Low | High |
| F02 | Cancel any existing appointment (not just the one just booked) | Self-service | 🔴 High | Low | High |
| F03 | Multiple reminder attempts if no answer | Outbound | 🔴 High | Medium | High |
| F04 | SMS / WhatsApp reminder as fallback | Outbound | 🔴 High | Medium | High |
| F05 | Booking confirmation SMS/email sent after booking | Notification | 🔴 High | Low | High |
| F06 | Day-before reminder call / SMS (not just 1 hour) | Outbound | 🔴 High | Low | High |
| F07 | Doctor availability filter — show only available doctors on chosen date | Scheduling | 🔴 High | Medium | High |
| F08 | "Fully booked" day handling — suggest next available date automatically | Scheduling | 🔴 High | Medium | High |
| F09 | Specialty-based doctor search ("I need a cardiologist") | Scheduling | 🟠 Medium | Medium | High |
| F10 | Time-of-day preference ("morning" or "after 3 PM") | Scheduling | 🟠 Medium | Medium | Medium |
| F11 | Urgent / same-day appointment path | Scheduling | 🟠 Medium | Low | High |
| F12 | Follow-up appointment booking ("book me again in 2 weeks with same doctor") | Scheduling | 🟠 Medium | Low | Medium |
| F13 | Waitlist — notify patient if a slot opens | Scheduling | 🟠 Medium | High | Medium |
| F14 | Transfer to human operator / receptionist | Patient Experience | 🔴 High | Low | High |
| F15 | Urdu language support (code-switching) | Patient Experience | 🟠 Medium | Medium | High |
| F16 | DTMF keypad fallback (press 1 to confirm, 2 to cancel) | Patient Experience | 🟠 Medium | Medium | Medium |
| F17 | "Please wait" filler during tool calls | Patient Experience | 🟠 Medium | Low | Medium |
| F18 | Clinic hours enforcement — no booking outside working hours | Operations | 🟠 Medium | Low | Medium |
| F19 | Public holiday calendar — block booking on holidays | Operations | 🟠 Medium | Medium | Medium |
| F20 | Missed appointment follow-up call | Outbound | 🟠 Medium | Medium | Medium |
| F21 | Post-appointment satisfaction survey call | Outbound | 🟢 Low | Medium | Medium |
| F22 | Multiple branches / clinic locations | Operations | 🟢 Low | High | High |
| F23 | Family member booking ("book for my wife") | Self-service | 🟢 Low | Medium | Medium |
| F24 | Appointment purpose / reason capture | Scheduling | 🟢 Low | Low | Medium |
| F25 | Returning patient personalisation ("Welcome back, Ahmed") | Patient Experience | 🟢 Low | Low | Medium |
| F26 | Check-in by phone ("I have arrived") | Operations | 🟢 Low | Medium | Low |
| F27 | Queue position update ("You are number 3, estimated 20 minutes") | Operations | 🟢 Low | High | Medium |
| F28 | Appointment history query ("When was my last visit?") | Self-service | 🟢 Low | Low | Low |
| F29 | Multi-appointment booking in one call | Self-service | 🟢 Low | Medium | Low |
| F30 | Call volume / booking analytics dashboard | Analytics | 🟢 Low | Medium | Medium |

**Total feature gaps: 30**

---

## 3. Patient Self-Service Features

### F01 🔴 — View Existing Appointments

**What patient says:** "What appointments do I have?" / "Do I have anything booked?"

**Current behaviour:**  
The agent has no tool to look up the patient's existing appointments. It can only
book new ones or cancel/reschedule the one just booked in the same call. A patient
calling back after hanging up has no way to check their booking.

**Required:**  
New tool `get_patient_appointments` + new HOS endpoint:
```
GET /api/v1/tools/patients/{patient_id}/appointments
Response: [{id, doctorName, appointmentDate, startTime, status, confirmationCode}]
```

**Prompt addition (STATE 1 or new STATE):**
```
If the patient asks about existing appointments:
  Call get_patient_appointments with patient_id.
  Read each appointment: "You have an appointment with Dr. [Name] on [Date] at [Time],
  confirmation code [Code]."
  Ask: "Would you like to do anything with these appointments?"
```

**Business Impact:**  
Patients currently have to call back and go through the full flow again just to
hear their own confirmation code. This is the most common re-call reason.

---

### F02 🔴 — Cancel Any Existing Appointment

**What patient says:** "I want to cancel my appointment tomorrow"

**Current behaviour:**  
`cancel_appointment` only works within the same call immediately after booking
(STATE 5), using the `appointment_id` variable set by `book_appointment`.
A patient calling a separate time (e.g., day before appointment) cannot cancel
because `appointment_id` is not available from a lookup.

**Required:**  
Combine F01 (get_patient_appointments) with the existing `cancel_appointment` tool.
Once the patient's appointments are listed, they pick the one to cancel, and
`appointment_id` is set from the list.

**Prompt addition:**
```
If the patient wants to cancel:
  Call get_patient_appointments to list their upcoming appointments.
  Ask which one they want to cancel.
  Confirm: "Are you sure you want to cancel your appointment with Dr. [Name] on [Date]?"
  On Yes: Call cancel_appointment with the selected appointment_id.
```

**Business Impact:**  
Without this, the cancellation feature only works during the booking call itself.
A patient who calls back to cancel gets frustrated and may just not show up (no-show).

---

### F23 🟢 — Family Member Booking

**What patient says:** "I want to book for my mother, Fatima Khan"

**Current behaviour:**  
The system assumes the caller IS the patient. If someone is booking for a family
member, `patient_id` from the lookup is the caller's ID, not the family member's.
The appointment is booked against the wrong patient.

**Required:**  
Add a "booking for yourself or someone else?" branch at STATE 1:
```
If patient says "for my [relation]" or "for someone else":
  Ask: "What is their full name?"
  Ask: "What is their phone number?" (or "are they registered with us?")
  Call name_look_up / register_patient with the family member's details.
  Proceed with family member's patient_id.
```

---

### F28 🟢 — Appointment History Query

**What patient says:** "When was my last appointment?" / "Have I seen Dr. Hina before?"

**Required:**  
`GET /api/v1/tools/patients/{patient_id}/appointments?status=COMPLETED&limit=5`

Simple lookup to answer history questions without booking anything.

---

### F29 🟢 — Multi-Appointment Booking in One Call

**What patient says:** "I need to book for Monday and then again in two weeks"

**Current behaviour:**  
After STATE 5, the flow only offers cancel/reschedule. There is no loop back to
book a second new appointment.

**Required:**  
In STATE 5 GENERAL section, after "Is there anything else":
```
- If patient wants another appointment → go back to STATE 2 (keep patient_id)
```

---

## 4. Appointment Scheduling Features

### F07 🔴 — Doctor Availability Filter

**Current behaviour:**  
`fetch_doctor_list` returns ALL doctors regardless of whether they are available
on the date the patient wants. The patient picks a doctor, then `get_next_serial`
may return nothing (fully booked or doctor not scheduled that day), leaving the
patient confused — "why did you offer me that doctor?"

**Required:**  
Two options:

**Option A — Filter at API level:**
```
GET /api/v1/tools/doctors?date=2026-05-26
Response: only doctors with available slots on that date
```
Change prompt: ask for preferred date BEFORE presenting doctors.

**Option B — Validate before showing (current structure kept):**
After patient picks a date in STATE 3, call `get_next_serial`. If 0 slots:
say "Dr. [Name] is not available on that date. Would you like a different date
or a different doctor?" and offer the list again.

**Revised STATE flow:**
```
STATE 2 → Ask for preferred date → fetch_doctor_list?date=X → show available doctors only
→ Patient picks → STATE 3 (date already confirmed, just double-check)
```

---

### F08 🔴 — "Fully Booked" Day — Suggest Next Available Date

**Current behaviour:**  
When `get_next_serial` returns 0 or null slots, the prompt says "apologize and
ask if they want a different date." The patient has no idea what dates ARE available.
They blindly guess — "how about Wednesday?" — until they find a free day.

**Required:**  
New tool `get_next_available_date`:
```
GET /api/v1/tools/doctors/{doctor_id}/next-available?from=2026-05-27
Response: { "nextAvailableDate": "2026-05-29", "nextSerial": 3, "estimatedTime": "11:00" }
```

**Prompt addition in STATE 3:**
```
If get_next_serial returns 0 or fails:
  Call get_next_available_date with doctor_id and tomorrow's date.
  Say: "Dr. [Name] is fully booked on that date. The next available date is
        [nextAvailableDate]. Would you like to book that instead?"
```

---

### F09 🟠 — Specialty-Based Doctor Search

**What patient says:** "I need to see a heart doctor" / "Do you have a skin specialist?"

**Current behaviour:**  
Ava reads the full doctor list and the patient must identify the right specialty
themselves. With 10+ doctors, this is a long list to read aloud.

**Required:**
```
GET /api/v1/tools/doctors?specialty=Cardiology
```

**Prompt addition in STATE 2:**
```
Ask: "Do you know which doctor you'd like to see, or would you like me to
      suggest based on your medical need?"
If patient mentions a condition or specialty:
  Filter fetch_doctor_list by specialty.
  Present only matching doctors.
```

---

### F10 🟠 — Time-of-Day Preference

**What patient says:** "I prefer mornings" / "Can I come after 4 PM?"

**Current behaviour:**  
`get_next_serial` returns the next available serial with no time filter.
If the next serial is at 3:00 PM and the patient can only come in mornings,
they confirm the serial without realising the time, and later miss the appointment.

**Required:**
```
GET /api/v1/tools/appointments/next-serial?doctorId=X&date=Y&preferredAfter=09:00&preferredBefore=13:00
```

**Prompt addition in STATE 3:**
```
Ask: "Do you have a time preference — morning or afternoon?"
Pass preferredAfter / preferredBefore to get_next_serial.
```

---

### F11 🟠 — Urgent / Same-Day Appointment

**What patient says:** "I need to see a doctor today, it's urgent"

**Current behaviour:**  
The patient says "today", Ava converts it to today's date (YYYY-MM-DD) using
`{today}` and calls `get_next_serial`. This technically works, but the prompt
has no special handling for urgency. There is no priority queue or urgent
slot type.

**Required:**  
Add `appointmentType: URGENT` to `book_appointment` body when patient indicates
urgency. Add a prompt branch:
```
If patient says "urgent", "emergency", "today", "right now":
  Acknowledge urgency: "I understand, let me check for the earliest available slot today."
  Call get_next_serial with today's date.
  If available: proceed with URGENT appointmentType.
  If not available today: "There are no slots today. The earliest is [next date].
    Shall I book that, or would you prefer to come to the clinic directly?"
```

---

### F12 🟠 — Follow-Up Appointment Booking

**What patient says:** "Book me again with the same doctor in 2 weeks"

**Current behaviour:**  
Not supported. Patient must go through the full flow again from STATE 2.

**Required:**  
In STATE 5 "Is there anything else" branch:
```
If patient asks for a follow-up:
  Confirm: "Same doctor, Dr. [Name], 2 weeks from today ([Date])?"
  Skip STATE 2 (doctor already known).
  Go to STATE 3 with doctor_id pre-filled and new date.
```

---

### F13 🟠 — Waitlist When Doctor Is Fully Booked

**What patient says:** "If anything opens up, please let me know"

**Current behaviour:**  
If the doctor is fully booked, Ava apologises and suggests a different date.
There is no way to register patient interest in a cancelled slot.

**Required:**  
New tool `join_waitlist`:
```
POST /api/v1/tools/appointments/waitlist
Body: { "patientId": X, "doctorId": Y, "preferredDate": "YYYY-MM-DD" }
```

When a cancellation occurs, HOS backend triggers an outbound call to the
next patient on the waitlist.

---

### F24 🟢 — Appointment Purpose / Reason Capture

**What patient says:** "I have a cough and fever" / "routine check-up"

**Current behaviour:**  
No reason is captured. The doctor has no pre-visit context.

**Required:**
```
Ask: "Could you briefly describe the reason for your visit?"
Add reason field to book_appointment body:
  "visitReason": "{visit_reason}"
```

Simple addition, low effort, high clinical value.

---

## 5. Outbound & Notification Features

### F03 🔴 — Multiple Reminder Attempts (Retry on No Answer)

**Current behaviour:**  
One outbound call attempt. If the patient does not answer (busy, driving, phone
on silent), the call is dropped after 60 seconds. No second attempt is made.
The patient receives no reminder at all.

**Required:**

**Attempt schedule (example):**
| Attempt | Time Before Appointment | Channel |
|---------|------------------------|---------|
| 1st | 24 hours | Voice call |
| 2nd (if no answer) | 1 hour | Voice call |
| 3rd (if still no answer) | 30 minutes | SMS |

**Implementation:**  
HOS backend schedules three separate trigger events. The AI engine adds an
outcome callback (G9 from technical gap analysis) so the HOS backend knows
whether to fire the next attempt.

---

### F04 🔴 — SMS / WhatsApp Reminder as Fallback

**Current behaviour:**  
Only voice calls. No SMS or WhatsApp channel.

For many patients — especially younger ones — SMS or WhatsApp is more reliable
than a voice call. Many also will not answer calls from unknown numbers but
will read a WhatsApp message.

**Required:**  
Integrate an SMS / WhatsApp gateway (e.g., Twilio, Infobip, or a local Pakistani
provider like Telenor messaging API).

**Message template:**
```
Assalam-o-Alaikum [patient_name],

This is Smart Doctor Clinic. You have an appointment with [doctor_name]
on [appointment_date] at [start_time].

Confirmation code: [confirmation_code]

Reply YES to confirm, NO to cancel, or call us at [clinic_number].
```

---

### F05 🔴 — Booking Confirmation SMS / Email

**Current behaviour:**  
After `book_appointment` succeeds, Ava reads the confirmation code aloud. That
is the only delivery mechanism. If the patient forgets or mishears, the code
is lost.

**Required:**  
After `book_appointment` succeeds, the HOS backend (or a webhook trigger from
the AI engine) automatically sends:
- **SMS:** "Your appointment is confirmed. Dr. [Name], [Date] at [Time]. Code: [Code]."
- **Email:** Full appointment card with calendar attachment (.ics file)

This is a HOS backend feature, not an AI change. The booking API response
should trigger it automatically.

---

### F06 🔴 — Day-Before Reminder

**Current behaviour:**  
Only one reminder: 1 hour before the appointment. Research consistently shows
that a day-before reminder reduces no-shows more effectively than a same-day
reminder, because the patient still has time to cancel and free the slot.

**Required:**  
HOS scheduler fires **two** outbound triggers:
1. **T-24 hours:** "Your appointment is tomorrow at [time] with Dr. [Name]."
   Patient can confirm, cancel, or reschedule.
2. **T-1 hour:** Current flow (already built).

The T-24 call uses the same `outbound_reminder` context — only the script
needs a small change. Add a `reminder_type` field to the trigger payload:
- `reminder_type: "day_before"` → "Your appointment is **tomorrow**..."
- `reminder_type: "same_day"` → "Your appointment is **today** in one hour..."

---

### F20 🟠 — Missed Appointment Follow-Up Call

**What the clinic needs:** "Patient didn't show up — call and ask why"

**Current behaviour:**  
No post-appointment outbound call. If the patient does not attend, there is no
automatic follow-up.

**Required:**  
New outbound context `outbound_missed_appointment`:
- Triggered by HOS backend when appointment status = `NO_SHOW`
- Script: "We noticed you missed your appointment with Dr. [Name] on [Date].
  Would you like to reschedule?"
- Captures rescheduling or records reason for missing.

---

### F21 🟢 — Post-Appointment Satisfaction Survey

**What the clinic needs:** "How was your experience?"

**Required:**  
New outbound context `outbound_satisfaction_survey`:
- Triggered 2 hours after appointment status = `COMPLETED`
- 2–3 question satisfaction survey (rate 1–5, any feedback)
- Results sent to HOS backend analytics endpoint

---

## 6. Clinic Operations Features

### F14 🔴 — Transfer to Human Operator

**Current behaviour:**  
If the AI cannot understand the patient, a tool fails repeatedly, or the patient
is confused / distressed, there is no escape hatch. The patient is stuck in a
loop with the AI until they hang up in frustration.

**Required:**  
Add `transfer_call` tool to both contexts. Add to the prompt:
```
EMERGENCY ESCAPE:
At any point, if the patient says "operator", "receptionist", "human", "agent",
"help me", "I want to talk to someone", or expresses repeated frustration:
  Say: "Of course, let me connect you with our reception desk right away."
  Call transfer_call with extension [clinic_reception_ext].
  Do NOT attempt to help further — transfer immediately.
```

This is the single most important UX safety net for a healthcare AI.

---

### F18 🟠 — Clinic Hours Enforcement

**Current behaviour:**  
No check. Patients can call at midnight and book appointments.
`get_next_serial` will return slots regardless of time of day.

**Required:**  
Add to prompt GENERAL RULES:
```
Clinic hours: Monday–Saturday, 9:00 AM – 6:00 PM (PKT).
If a patient calls outside clinic hours:
  Say: "Our clinic is currently closed. We are open Monday to Saturday,
        9 AM to 6 PM. I can still book your appointment — which date works for you?"
  Allow booking but do not suggest same-day slots if outside hours.
```

Also: add `clinicHolidays` list to config — dates when the clinic is closed.

---

### F19 🟠 — Public Holiday Calendar

**Current behaviour:**  
Eid, national holidays, and clinic-specific days off are invisible to the AI.
A patient could book an appointment on Eid-ul-Fitr and the system would accept it.

**Required:**  
1. HOS backend: add a holiday calendar endpoint:
   ```
   GET /api/v1/tools/clinic/holidays?from=2026-05-01&to=2026-06-30
   Response: ["2026-05-01", "2026-05-23"]
   ```
2. In the date selection state, after patient gives a date, call holiday check
   before `get_next_serial`. If it is a holiday:
   ```
   "That date is a clinic holiday. May I suggest the next working day, [Date]?"
   ```

---

### F22 🟢 — Multiple Branches / Clinic Locations

**Current behaviour:**  
Single clinic, single phone number, single set of doctors.

**Required:**  
If Smart Doctor expands to multiple branches (Lahore, Karachi, Islamabad):
- Patients call a central number and are routed to the correct branch
- `X-Tenant-ID` header already exists in all tool calls (currently hardcoded as `'1'`)
- The tenant ID should be set dynamically based on the dialed number (DID routing)

This is already partially architected — the `X-Tenant-ID` header is present.
Only the routing logic and per-tenant configuration are missing.

---

### F26 🟢 — Patient Check-In by Phone

**What patient says:** "I've arrived at the clinic"

**Required:**  
New in-call tool `patient_check_in`:
```
PATCH /api/v1/tools/appointments/{appointment_id}/check-in
Response: { "queuePosition": 3, "estimatedWaitMinutes": 15 }
```

Ava responds: "You are number 3 in the queue. Estimated wait is about 15 minutes.
Please take a seat in the waiting area."

---

### F27 🟢 — Queue Position Update

When the patient is waiting, they can call back and ask:
"How much longer?" → Ava queries current queue position for their appointment.

---

## 7. Patient Experience Features

### F15 🟠 — Urdu Language Support

**Current behaviour:**  
English only. Pakistan's patient population is predominantly Urdu-speaking.
Many older patients or those from smaller cities may struggle with English.

**Required:**  
- Deepgram supports Urdu (`ur`) and code-switched Urdu+English
- Add a language detection step at greeting
- Two context variants: `default_en` and `default_ur` (or detect and switch mid-call)
- Urdu prompt translations for all 6 states

**Language detection approach:**
```
Greeting (English): "Hello, welcome to Smart Doctor Clinic. You may speak in English or Urdu."
If first patient utterance is in Urdu → switch to Urdu prompt context
If English → continue as-is
```

**Deepgram config:**
```yaml
providers:
  deepgram:
    model: nova-2-general
    language: multi   # or detect + switch
```

---

### F16 🟠 — DTMF Keypad Fallback

**Current behaviour:**  
Voice-only. If Deepgram STT fails (noisy environment, poor connection, heavy
accent), the patient is stuck. They cannot use their keypad as a fallback.

**Required:**  
Map DTMF digits to key choices at each decision point:
```
STATE 4: "Press 1 to confirm, 2 to try a different date"
OUTBOUND: "Press 1 if you will attend, 2 to cancel, 3 to reschedule"
```

Asterisk sends DTMF as ARI events — the engine can listen for these and
inject them as a user utterance.

---

### F17 🟠 — "Please Wait" Filler During Tool Calls

**Current behaviour:**  
Silence for 1–3 seconds while the AI waits for tool call responses.
On the phone, silence = disconnected line. Patients hang up.

**Required:**  
Before every tool call, Ava says a contextual filler:

| Tool | Filler |
|------|--------|
| `fetch_doctor_list` | "Let me check our available doctors for you." |
| `get_next_serial` | "One moment while I check availability for that date." |
| `book_appointment` | "I am confirming your booking right now." |
| `cancel_appointment` | "Let me process that cancellation for you." |
| `name_look_up` | (pre-call, patient not connected yet) |

**Implementation:**  
Add `pre_tool_filler` to tool definitions in YAML, or handle in the prompt:
```
Before calling any tool, say a brief one-sentence filler relevant to the action.
Do NOT say "I am calling the tool" or mention tool names.
```

---

### F25 🟢 — Returning Patient Personalisation

**What patient hears now:** "Could I have your full name please?"  
**What they should hear:** "Welcome back, Ahmed! How can I help you today?"

**Current behaviour:**  
When `lookup_success = true`, Ava jumps directly to STATE 2 (doctor selection)
without acknowledging the returning patient by name.

**Required:**  
Add to STATE 1 success path:
```
If lookup_success = true:
  Say: "Welcome back, [patient_name]! Great to hear from you.
        Are you calling to book an appointment today?"
```

This is a one-line prompt change — no backend work needed.

---

## 8. Analytics & Reporting Features

### F30 🟢 — Call Volume & Booking Analytics Dashboard

**Current state:**  
`smart_doctor_call_log` posts call data to HOS backend after every call.
But there is no dashboard or report that answers:

| Question | Currently Available? |
|----------|---------------------|
| How many calls today? | ❌ |
| What % of calls resulted in a booking? | ❌ |
| What % of calls were cancellations? | ❌ |
| Which doctor is most booked by phone? | ❌ |
| What time of day are most calls? | ❌ |
| How many reminder calls were answered? | ❌ |
| What is the no-show rate for phone bookings? | ❌ |
| Average call duration? | ❌ (in call_log but not reported) |

**Required:**  
HOS backend analytics endpoints + Admin UI dashboard with:
- Daily call volume chart
- Booking conversion funnel (call → booking confirmed %)
- Cancellation / reschedule rate
- Outbound reminder answered / not answered rate
- Doctor-level booking breakdown

The call log data is already being sent (`smart_doctor_call_log`) — the
analytics queries just need to be built on the HOS side.

---

## 9. Integration Features

### SMS / WhatsApp Gateway Integration

**Required integrations (choose one per channel):**

| Channel | Providers | Estimated Cost |
|---------|-----------|----------------|
| SMS (Pakistan) | Twilio, Infobip, CM.com, Zong/Telenor direct | ~$0.01–0.05 per SMS |
| WhatsApp Business | Meta Cloud API, Twilio, Infobip | ~$0.01–0.08 per message |
| Email | SendGrid, AWS SES, Mailgun | ~$0.001 per email |

**Integration points:**
1. After `book_appointment` → send SMS/WhatsApp confirmation
2. T-24h before appointment → send reminder SMS/WhatsApp
3. When outbound call goes unanswered → send SMS fallback
4. After cancellation → send cancellation SMS

### EMR / EHR Integration

If Smart Doctor uses an Electronic Medical Record system, the AI should be
able to:
- Read patient medical history to personalise the call ("I see you last visited
  for hypertension — is this a follow-up?")
- Tag the appointment with a department code from the EMR

### Google / Outlook Calendar Sync

After booking, add the appointment to the patient's calendar (if they have
given email). Send an `.ics` calendar invite as an attachment in the confirmation
email.

---

## 10. Priority Roadmap

### Phase 1 — Complete Core Flow (Next 2 Weeks)

These gaps make the current feature set feel broken or incomplete. Fix these
before going to more patients.

| Feature | Why It Matters |
|---------|---------------|
| F14 — Transfer to human | Safety net — patients must always be able to reach a person |
| F01 — View existing appointments | Most common reason for a second call |
| F02 — Cancel any appointment | Cancellation only works same-call today |
| F05 — Booking confirmation SMS | Patients forget the confirmation code spoken aloud |
| F07 — Doctor availability filter | Avoids offering unavailable doctors |
| F08 — Next available date suggestion | Avoids "try a different date" dead-end loop |
| F25 — Returning patient greeting | One-line prompt fix, big experience improvement |
| F17 — Filler during tool calls | Prevents patients hanging up during silence |

---

### Phase 2 — Reminder Excellence (Weeks 3–6)

| Feature | Why It Matters |
|---------|---------------|
| F06 — Day-before reminder | Reduces no-shows more than same-day reminder |
| F03 — Multiple attempts | Single attempt misses patients who don't answer |
| F04 — SMS / WhatsApp fallback | Many patients won't answer unknown numbers |
| F11 — Urgent / same-day path | High patient demand, simple to add |
| F12 — Follow-up appointment booking | Keeps the patient in the system |
| F18 — Clinic hours enforcement | Prevents invalid bookings |
| F19 — Public holiday calendar | Prevents booking on closed days |
| F20 — Missed appointment follow-up | Recover no-shows, offer rescheduling |

---

### Phase 3 — Richer Experience (Month 2–3)

| Feature | Why It Matters |
|---------|---------------|
| F09 — Specialty search | Better UX for patients who don't know doctor names |
| F10 — Time-of-day preference | Reduces patients missing appointments due to inconvenient times |
| F15 — Urdu language support | Opens the product to the majority of the patient base |
| F13 — Waitlist | Recovers cancelled slots, fills doctor schedules |
| F16 — DTMF fallback | Accessibility for poor audio/noisy environments |
| F24 — Appointment reason capture | Gives doctors pre-visit context |
| F30 — Analytics dashboard | Clinic management visibility |

---

### Phase 4 — Scale & Expansion (Month 3+)

| Feature | Why It Matters |
|---------|---------------|
| F22 — Multiple branches | Needed for chain expansion |
| F23 — Family booking | Increases bookings per call |
| F21 — Satisfaction survey | Clinic quality measurement |
| F26 + F27 — Check-in / queue updates | Full clinic workflow integration |
| F28 — Appointment history | Personalisation and returning patient experience |
| F29 — Multi-appointment in one call | Efficiency for patients with multiple needs |

---

## 11. Effort vs Impact Matrix

```
HIGH IMPACT
│
│  F03  F04                    F07  F08
│  F05  F06    F15             F01  F02  F14
│         F09  F11  F12  F20
│              F10  F13        F18  F19
│  F21  F24  F16  F17  F25     F22
│       F26  F27  F28  F29  F30  F23
│
LOW IMPACT
└─────────────────────────────────────────
  LOW EFFORT                    HIGH EFFORT

Key: Left = quick wins, Right = bigger investments
     Top = high patient/clinic value, Bottom = nice-to-have
```

**Quick Wins (Low effort, High impact):**
- F14 — Transfer to human (add tool + 5 prompt lines)
- F25 — Welcome back greeting (1 prompt line)
- F17 — Filler during tool calls (3 prompt lines)
- F11 — Urgent appointment path (small prompt addition)
- F05 — Booking confirmation SMS (HOS backend trigger, no AI change)
- F06 — Day-before reminder (HOS scheduler + same outbound context, minor prompt tweak)

**Strategic Investments (High effort, High impact):**
- F15 — Urdu language support (Deepgram config + full prompt translation)
- F04 — SMS/WhatsApp gateway (third-party integration)
- F22 — Multi-branch support (multi-tenant architecture)

---

*Total features built: 19*
*Total feature gaps identified: 30*
*Quick wins requiring < 1 day of work: 8*
*Features requiring HOS backend changes: 16*
*Features requiring only AI prompt/config changes: 7*
