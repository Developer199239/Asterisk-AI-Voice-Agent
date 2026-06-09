# Smart Doctor Clinic — Parent IVR Design Guide
## Multi-Level AI IVR Tree: Extension 7000 → Sub-Agents

**Date:** 2026-06-09
**Author:** Murtuza Rahman
**Version:** 1.0

> **What this document covers:**
> How to build a multi-level AI IVR tree where a parent agent (7000)
> routes callers to specialist sub-agents (7001–7008) using the
> `transfer_call` tool and Asterisk dialplan context switching.

---

## Table of Contents

1. [IVR Tree Overview](#1-ivr-tree-overview)
2. [How Agent-to-Agent Transfer Works](#2-how-agent-to-agent-transfer-works)
3. [Extension Map](#3-extension-map)
4. [FreePBX Dialplan (extensions_custom.conf)](#4-freepbx-dialplan-extensionscustomconf)
5. [Transfer Tool Configuration (ai-agent.local.yaml)](#5-transfer-tool-configuration-ai-agentlocalyaml)
6. [AI Context Definitions](#6-ai-context-definitions)
   - [7000 — Main IVR Parent](#7000--main-ivr-parent)
   - [7001 — Appointment Sub-Menu](#7001--appointment-sub-menu)
   - [7002 — New Appointment Agent](#7002--new-appointment-agent)
   - [7003 — Reschedule Appointment Agent](#7003--reschedule-appointment-agent)
   - [7004 — Cancel Appointment Agent](#7004--cancel-appointment-agent)
   - [7007 — Appointment Query Agent](#7007--appointment-query-agent)
   - [7008 — Doctor Information Agent](#7008--doctor-information-agent)
   - [7005 — Diagnostic Menu](#7005--diagnostic-menu)
   - [7006 — Admission Menu](#7006--admission-menu)
7. [Complete Dialog Scripts](#7-complete-dialog-scripts)
8. [How Patient Data Passes Between Agents](#8-how-patient-data-passes-between-agents)
9. [Setup Checklist](#9-setup-checklist)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. IVR Tree Overview

> **Design decision (v1.1):** The `ivr_appointments` sub-menu (7001) has been
> merged directly into `ivr_main` (7000). When the patient says "Appointments",
> the main agent presents the appointment sub-menu **inline** — no transfer hop.
> This removes one round-trip, one Stasis re-entry, and one greeting.

```
CALLER DIALS CLINIC NUMBER
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  EXT 7000 — MAIN IVR (ivr_main)                               │
│                                                               │
│  STEP 1 — Top menu:                                           │
│    "Appointments [1] / Diagnostics [2] / Admissions [3]"      │
│                                                               │
│  STEP 2 — If patient says "Appointments":                     │
│    Inline sub-menu (NO transfer to 7001):                     │
│    "New [1] / Reschedule [2] / Cancel [3] /                   │
│     Check [4] / Doctors [5] / Back [0]"                       │
└───┬──────────┬──────────┬──────────┬──────────┬──────────────┘
    │          │          │          │          │
  New[1]  Resched[2]  Cancel[3]  Check[4]  Doctors[5]
    │          │          │          │          │
    ▼          ▼          ▼          ▼          ▼
┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐
│ 7002  │ │ 7003  │ │ 7004  │ │ 7007  │ │ 7008  │
│  NEW  │ │RESCHED│ │CANCEL │ │QUERY  │ │DOCTOR │
│ APPT  │ │  APPT │ │ APPT  │ │ APPTS │ │ INFO  │
└───────┘ └───────┘ └───────┘ └───────┘ └───────┘

Press 2 (Diagnostics) → EXT 7005 (ivr_diagnostics)
Press 3 (Admissions)  → EXT 7006 (ivr_admission)
"Receptionist"        → EXT 100  (human reception)
```

---

## 2. How Agent-to-Agent Transfer Works

This is the most important concept. When one AI agent transfers to another,
**three things happen in sequence:**

```
┌──────────────────────────────────────────────────────────────────┐
│                    TRANSFER SEQUENCE                             │
│                                                                  │
│  1. AI Agent calls transfer_call("appointment_menu")             │
│     └─► Engine: ARI continueInDialplan(channel, "from-ai-7001") │
│                                                                  │
│  2. Asterisk dialplan [from-ai-7001] runs:                       │
│     └─► Set(AI_CONTEXT=ivr_appointment_menu)                    │
│     └─► Stasis(asterisk-ai-voice-agent)   ← new Stasis entry    │
│                                                                  │
│  3. Engine: NEW StasisStart event                                │
│     └─► New CallSession created                                 │
│     └─► Pre-call tools run again (name_look_up re-fires)        │
│     └─► Patient data loaded fresh from HOS backend              │
│     └─► New AI session starts with ivr_appointment_menu context │
└──────────────────────────────────────────────────────────────────┘
```

**Key facts:**
- The caller stays on the same phone call — they never hear a ring or disconnect
- The **caller's phone number** (CALLERID) is preserved on the channel — so `name_look_up` automatically re-identifies the patient on every sub-agent
- Each sub-agent gets a **fresh AI session** with its own context/prompt
- You do NOT need to pass `patient_id` manually — the pre-call lookup handles it

---

## 3. Extension Map

| Extension | Context Name | Agent Role | Transfers To |
|-----------|-------------|------------|-------------|
| **7000** | `ivr_main` | Main IVR — top menu **+ inline appointment sub-menu** | 7002, 7003, 7004, 7005, 7006, 7007, 7008, 100 |
| ~~7001~~ | ~~`ivr_appointments`~~ | ~~Appointment sub-menu~~ | ⛔ Merged into 7000 — no longer needed as a transfer hop |
| **7002** | `default` | New appointment booking | — (existing flow) |
| **7003** | `ivr_reschedule` | Reschedule existing appointment | — |
| **7004** | `ivr_cancel` | Cancel existing appointment | — |
| **7005** | `ivr_diagnostics` | Diagnostic services menu | — |
| **7006** | `ivr_admission` | Admission inquiries menu | — |
| **7007** | `ivr_appt_query` | Appointment query / view bookings | — |
| **7008** | `ivr_doctor_info` | Doctor information | — |

---

## 4. FreePBX Dialplan (extensions_custom.conf)

> **How it works in FreePBX:** All extension definitions go into `[from-internal-custom]`.
> FreePBX automatically includes this inside `[from-internal]` via `#include`.
> The transfer tool uses `extension_context: from-internal` so every transfer
> lands in `[from-internal]` → finds the extension in `[from-internal-custom]` →
> reads `AI_CONTEXT` → starts the correct sub-agent.

Go to **Admin → Config Edit → extensions_custom.conf** in FreePBX.
Add or update the `[from-internal-custom]` block below. Click **Save** then **Apply Config**.

```asterisk
; ─────────────────────────────────────────────────────────────────────────────
; SMART DOCTOR CLINIC — AI IVR TREE
;
; [from-internal-custom] is auto-included inside [from-internal] by FreePBX.
; All AI-to-AI transfers use extension_context: from-internal (YAML setting),
; so Asterisk finds these extensions here.
;
; Pattern for every extension:
;   1. Set(AI_CONTEXT=<context_name>)  ← tells the engine which prompt to load
;   2. Set(AI_PROVIDER=deepgram)
;   3. Stasis(asterisk-ai-voice-agent) ← engine starts fresh AI session
;   4. Hangup()                        ← fallback if Stasis exits
; ─────────────────────────────────────────────────────────────────────────────
[from-internal-custom]

; 7000 — Main IVR parent (entry point from inbound DID)
exten => 7000,1,NoOp(Smart Doctor - Main IVR)
 same => n,Set(AI_CONTEXT=ivr_main)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; 7001 — Appointment sub-menu
exten => 7001,1,NoOp(Smart Doctor - Appointment Menu)
 same => n,Set(AI_CONTEXT=ivr_appointments)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; 7002 — New appointment booking
exten => 7002,1,NoOp(Smart Doctor - New Appointment)
 same => n,Set(AI_CONTEXT=default)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; 7003 — Reschedule appointment
exten => 7003,1,NoOp(Smart Doctor - Reschedule Appointment)
 same => n,Set(AI_CONTEXT=ivr_reschedule)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; 7004 — Cancel appointment
exten => 7004,1,NoOp(Smart Doctor - Cancel Appointment)
 same => n,Set(AI_CONTEXT=ivr_cancel)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; 7005 — Diagnostic menu
exten => 7005,1,NoOp(Smart Doctor - Diagnostic Menu)
 same => n,Set(AI_CONTEXT=ivr_diagnostics)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; 7006 — Admission menu
exten => 7006,1,NoOp(Smart Doctor - Admission Menu)
 same => n,Set(AI_CONTEXT=ivr_admission)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; 7007 — Appointment query
exten => 7007,1,NoOp(Smart Doctor - Appointment Query)
 same => n,Set(AI_CONTEXT=ivr_appt_query)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

; 7008 — Doctor information
exten => 7008,1,NoOp(Smart Doctor - Doctor Information)
 same => n,Set(AI_CONTEXT=ivr_doctor_info)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()
```

### How the Dialplan Routing Works

When `transfer_call("appointment_menu")` is called by any AI agent:
1. Engine reads `tools.transfer.extension_context` → `from-internal`
2. Engine runs: `ARI POST /channels/{id}/continue` with `context=from-internal, extension=7001`
3. Asterisk routes into `[from-internal]` → finds extension 7001 defined in `[from-internal-custom]`
4. `Set(AI_CONTEXT=ivr_appointments)` sets the channel variable
5. `Stasis(asterisk-ai-voice-agent)` → channel re-enters Stasis
6. Engine detects re-entry after transfer → waits for old session cleanup → starts fresh `ivr_appointments` session

---

## 5. Transfer Tool Configuration (ai-agent.local.yaml)

> **Key setting:** `extension_context: from-ai-subagents`
> This is the **one global setting** that controls which dialplan context the
> transfer tool uses for ALL extension transfers. The transfer tool does NOT
> support a per-destination dial context — only one global context.

The YAML already has these destinations configured in `config/ai-agent.local.yaml`.
Verify it looks like this:

```yaml
tools:
  transfer:
    enabled: true
    # ── CRITICAL: must match where sub-agent extensions are defined ───────────
    # [from-internal-custom] is auto-included in [from-internal] by FreePBX.
    # So extension_context: from-internal finds them correctly.
    extension_context: from-internal
    destinations:
      main_menu:
        type: extension
        target: '7000'
        description: Main IVR menu
        live_agent: false
      appointment_menu:
        type: extension
        target: '7001'
        description: Appointment sub-menu
        live_agent: false
      new_appointment:
        type: extension
        target: '7002'
        description: New appointment booking
        live_agent: false
      reschedule_appointment:
        type: extension
        target: '7003'
        description: Reschedule an appointment
        live_agent: false
      cancel_appointment_agent:
        type: extension
        target: '7004'
        description: Cancel an appointment
        live_agent: false
      diagnostics_menu:
        type: extension
        target: '7005'
        description: Diagnostic services
        live_agent: false
      admission_menu:
        type: extension
        target: '7006'
        description: Admission inquiries
        live_agent: false
      appointment_query:
        type: extension
        target: '7007'
        description: Check existing appointments
        live_agent: false
      doctor_info:
        type: extension
        target: '7008'
        description: Doctor information
        live_agent: false
      reception:
        type: extension
        target: '100'
        description: Human receptionist
        live_agent: true
```

---

## 6. AI Context Definitions

Add all of the following contexts to your `config/ai-agent.local.yaml` under
the `contexts:` section.

---

### 7000 — Main IVR Parent

> **v1.1:** The appointment sub-menu is now handled **inline** inside this
> context. There is no transfer to 7001. When the patient says "Appointments",
> Ava presents the sub-menu directly and waits for the sub-choice before
> transferring to the actual task agent (7002–7008).

```yaml
contexts:

  ivr_main:
    provider: deepgram
    greeting: ''
    prompt: |
      You are Ava, the AI receptionist for Smart Doctor Clinic.
      Your job is to greet the patient, understand their need, and route them
      to the correct service. Be warm, brief, and efficient.

      =========================================================
      PATIENT CONTEXT (injected before call):
      - lookup_success: {lookup_success}
      - patient_name:   {patient_name}
      =========================================================

      =========================================================
      STEP 1 — GREETING
      =========================================================
      If {lookup_success} is "true" and {patient_name} is not empty:
        Say: "Welcome back, {patient_name}! How can I help you today?"
      Else:
        Say: "Welcome to Smart Doctor Clinic. How can I help you today?"

      Then say:
        "For appointments, say Appointments or press 1.
         For diagnostic services, say Diagnostics or press 2.
         For admission inquiries, say Admissions or press 3.
         To speak with our receptionist, say Receptionist at any time."

      =========================================================
      STEP 2 — MAIN MENU ROUTING
      =========================================================
      Listen for the patient's top-level choice.

      - "diagnostics" / "diagnostic" / "lab" / "test" / "2" / "two"
          -> Say: "Connecting you to our diagnostic services."
          -> Call transfer_call with destination "diagnostics_menu"

      - "admission" / "admissions" / "admit" / "ward" / "3" / "three"
          -> Say: "Connecting you to our admissions team."
          -> Call transfer_call with destination "admission_menu"

      - "receptionist" / "operator" / "human" / "agent" / "help"
          -> Say: "Connecting you to our reception desk."
          -> Call transfer_call with destination "reception"

      - "appointments" / "appointment" / "book" / "schedule" / "1" / "one"
          -> Do NOT transfer yet. Go to STEP 3.

      - Patient is confused or gives 2 wrong inputs:
          -> Re-read the top-level menu options once.
          -> If still unclear: transfer to "reception".

      =========================================================
      STEP 3 — APPOINTMENT SUB-MENU (inline — no transfer needed)
      =========================================================
      The patient wants appointment services. Present the sub-menu directly:

      Say:
        "For a new appointment, say New or press 1.
         To reschedule an appointment, say Reschedule or press 2.
         To cancel an appointment, say Cancel or press 3.
         To check your existing appointments, say Check or press 4.
         For doctor information, say Doctors or press 5.
         To go back to the main menu, say Back or press 0."

      Then listen and route:

      - "new" / "book" / "new appointment" / "1" / "one"
          -> Say: "Taking you to our booking service."
          -> Call transfer_call with destination "new_appointment"

      - "reschedule" / "change" / "move" / "2" / "two"
          -> Say: "Taking you to our rescheduling service."
          -> Call transfer_call with destination "reschedule_appointment"

      - "cancel" / "3" / "three"
          -> Say: "Taking you to our cancellation service."
          -> Call transfer_call with destination "cancel_appointment_agent"

      - "check" / "query" / "existing" / "what appointments" / "4" / "four"
          -> Say: "Let me pull up your appointments."
          -> Call transfer_call with destination "appointment_query"

      - "doctor" / "doctors" / "information" / "specialist" / "5" / "five"
          -> Say: "Let me get you our doctor information."
          -> Call transfer_call with destination "doctor_info"

      - "back" / "main menu" / "0" / "zero"
          -> Go back to STEP 1 and re-read the main menu options.

      - "receptionist" / "operator" / "human" / "help"
          -> Say: "Connecting you to our reception desk."
          -> Call transfer_call with destination "reception"

      - Patient is confused or gives 2 wrong inputs in the sub-menu:
          -> Re-read the appointment sub-menu options once.
          -> If still unclear: transfer to "reception".

      =========================================================
      GENERAL RULES
      =========================================================
      - Never mention tool names or technical terms to the patient.
      - Do NOT transfer to appointment_menu (7001) — handle appointments inline.
      - If the patient says goodbye at any point, say farewell and use hangup_call.

    pre_call_tools:
      - name_look_up

    tools:
      - transfer
      - hangup_call
```

---

### 7001 — Appointment Sub-Menu

```yaml
  ivr_appointments:
    provider: deepgram
    prompt: |
      You are Ava, the AI appointment assistant for Smart Doctor Clinic.
      You have just been transferred from the main menu.
      The patient wants appointment services. Present the options and
      route them to the correct specialist agent.

      =========================================================
      PATIENT CONTEXT:
      - lookup_success: {lookup_success}
      - patient_name:   {patient_name}
      =========================================================

      If {patient_name} is not empty:
        Say: "Hello {patient_name}, I can help you with appointments."
      Else:
        Say: "I can help you with appointments."

      Then say:
        "For a new appointment, say New or press 1.
         To reschedule an appointment, say Reschedule or press 2.
         To cancel an appointment, say Cancel or press 3.
         To check your existing appointments, say Check or press 4.
         For doctor information, say Doctors or press 5.
         To go back to the main menu, say Back or press 0."

      =========================================================
      ROUTING RULES
      =========================================================
      Transfer IMMEDIATELY after the patient's first valid choice.

      - "new" / "book" / "new appointment" / "1" / "one"
          -> Say: "Taking you to our booking service."
          -> Call transfer_call with destination "new_appointment"

      - "reschedule" / "change" / "move" / "2" / "two"
          -> Say: "Taking you to our rescheduling service."
          -> Call transfer_call with destination "reschedule_appointment"

      - "cancel" / "3" / "three"
          -> Say: "Taking you to our cancellation service."
          -> Call transfer_call with destination "cancel_appointment_agent"

      - "check" / "query" / "existing" / "what appointments" / "4" / "four"
          -> Say: "Let me pull up your appointments."
          -> Call transfer_call with destination "appointment_query"

      - "doctor" / "doctors" / "information" / "specialist" / "5" / "five"
          -> Say: "Let me get you our doctor information."
          -> Call transfer_call with destination "doctor_info"

      - "back" / "main menu" / "0" / "zero"
          -> Call transfer_call with destination "main_menu"

      - "receptionist" / "operator" / "human" / "help"
          -> Say: "Connecting you to our reception desk."
          -> Call transfer_call with destination "reception"

      GENERAL RULES:
      - Do not ask for any personal information in this menu.
      - Do not attempt to book, cancel, or reschedule here — just route.
      - If the patient says goodbye, say farewell and use hangup_call.

    pre_call_tools:
      - name_look_up

    tools:
      - transfer_call
      - hangup_call
```

---

### 7002 — New Appointment Agent

> **This is the existing `default` context** — no new context needed.
> The dialplan `[from-ai-7002]` sets `AI_CONTEXT=default` and the
> full 6-state booking flow runs exactly as before.

If you want a custom greeting when arriving from the IVR (versus a direct
inbound call), create a separate context:

```yaml
  ivr_new_appointment:
    provider: deepgram
    prompt: |
      You are Ava, the AI appointment assistant for Smart Doctor Clinic.
      The patient has been transferred here to book a new appointment.
      Skip the welcome and go directly into the booking flow.

      =========================================================
      PATIENT CONTEXT (injected before call):
      - lookup_success: {lookup_success}
      - patient_name:   {patient_name}
      - patient_id:     {patient_id}
      =========================================================

      [Use the full 6-state booking flow from the default context.
       Replace this line with the full default context prompt.]

    pre_call_tools:
      - name_look_up

    in_call_http_tools:
      - name_look_up
      - register_patient
      - fetch_doctor_list
      - get_next_serial
      - book_appointment
      - save_followup_request
      - cancel_appointment
      - reschedule_appointment

    post_call_tools:
      - smart_doctor_call_log

    tools:
      - hangup_call
      - transfer_call
```

> **Recommendation:** Update `[from-ai-7002]` to set `AI_CONTEXT=default`
> so you reuse the exact booking flow already built and tested.

---

### 7003 — Reschedule Appointment Agent

> **Requires:** `get_patient_appointments` tool (Feature F01 from gap analysis).
> This tool needs a new HOS backend endpoint.
>
> **HOS backend endpoint needed:**
> ```
> GET /api/v1/tools/patients/{patient_id}/appointments?status=UPCOMING
> Response: [{ id, doctorName, appointmentDate, startTime, confirmationCode, status }]
> ```

```yaml
  ivr_reschedule:
    provider: deepgram
    prompt: |
      You are Ava, the AI appointment assistant for Smart Doctor Clinic.
      The patient has been transferred here to RESCHEDULE an existing appointment.
      Be warm, efficient, and guide them step by step.

      =========================================================
      PATIENT CONTEXT (injected before call):
      - lookup_success: {lookup_success}
      - patient_name:   {patient_name}
      - patient_id:     {patient_id}
      =========================================================

      =========================================================
      RESCHEDULE FLOW
      =========================================================

      STEP 1 - IDENTIFY PATIENT
      If {lookup_success} is "true" and {patient_id} is known:
        Say: "Hello {patient_name}, I can help you reschedule your appointment."
        Go to STEP 2.
      Else:
        Ask: "Could I have your full name please?"
        Call register_patient or use name_look_up result to find patient_id.
        Go to STEP 2.

      STEP 2 - LIST APPOINTMENTS
      Call get_patient_appointments with patient_id = {patient_id}.
      If no upcoming appointments found:
        Say: "I do not see any upcoming appointments for you. Would you like
              to book a new one?"
        If yes: Call transfer_call with destination "new_appointment".
        If no: Say farewell and use hangup_call.

      If appointments found, read each one:
        "You have an appointment with Dr. [doctorName] on [appointmentDate]
         at [startTime], confirmation code [confirmationCode]."
      Ask: "Which appointment would you like to reschedule?"
      Store the chosen appointment_id and doctor_id.

      STEP 3 - GET NEW DATE
      Ask: "What date would you like to reschedule to?"
      Convert to YYYY-MM-DD format. Today is {today}.
      Call get_next_serial with doctor_id and new date.
      If no slots available:
        Say: "Dr. [Name] is fully booked on that date."
        Ask: "Would you like to try a different date?" and repeat STEP 3.

      STEP 4 - CONFIRM AND RESCHEDULE
      Say: "I can reschedule you to [new date] at [estimatedTime].
            Shall I confirm that?"
      Wait for Yes or No.
        - No  -> Ask for a different date. Back to STEP 3.
        - Yes -> Call reschedule_appointment with appointment_id,
                 doctor_id, and new_appointment_date.

      STEP 5 - CONFIRM SUCCESS
      On success:
        Say: "Done! Your appointment has been rescheduled to [new date]
              at [new_start_time] with Dr. [Name].
              Is there anything else I can help you with?"
        If nothing: farewell and hangup_call.
      On failure:
        Say: "I am sorry, I could not reschedule right now.
              Please call the clinic directly or I can connect you."
        If they want help: transfer_call to "reception".
        Else: hangup_call.

      GENERAL RULES:
      - Never invent appointment details. Use only data from get_patient_appointments.
      - Do not read raw IDs aloud.
      - Say times naturally: "9:00 AM" not "09:00:00".

    pre_call_tools:
      - name_look_up

    in_call_http_tools:
      - get_patient_appointments
      - get_next_serial
      - reschedule_appointment

    post_call_tools:
      - smart_doctor_call_log

    tools:
      - transfer_call
      - hangup_call
```

**New tool needed — add to `in_call_tools` section:**

```yaml
in_call_tools:
  get_patient_appointments:
    kind: in_call_http_lookup
    phase: in_call
    enabled: true
    is_global: false
    timeout_ms: 5000
    url: http://168.144.27.225/api/v1/tools/patients/{patient_id}/appointments
    method: GET
    headers:
      Content-Type: application/json
      X-Tenant-ID: '1'
      X-API-Key: dev-api-key-replace-in-production
    query_params:
      status: UPCOMING
    output_variables:
      appointments_list: data.content
      appointments_count: data.totalElements
    description: >-
      Fetches the list of upcoming appointments for the identified patient.
      Call this when the patient wants to reschedule, cancel, or query
      their existing appointments. Requires patient_id from pre-call lookup.
    parameters:
      - name: patient_id
        type: string
        description: The patient ID from pre-call lookup or registration
        required: true
    return_raw_json: false
    error_message: I am sorry, I could not retrieve your appointments right now.
```

---

### 7004 — Cancel Appointment Agent

> **Requires:** Same `get_patient_appointments` tool as 7003.

```yaml
  ivr_cancel:
    provider: deepgram
    prompt: |
      You are Ava, the AI appointment assistant for Smart Doctor Clinic.
      The patient has been transferred here to CANCEL an existing appointment.

      =========================================================
      PATIENT CONTEXT (injected before call):
      - lookup_success: {lookup_success}
      - patient_name:   {patient_name}
      - patient_id:     {patient_id}
      =========================================================

      =========================================================
      CANCELLATION FLOW
      =========================================================

      STEP 1 - IDENTIFY PATIENT
      If {lookup_success} is "true":
        Say: "Hello {patient_name}, I can help you cancel an appointment."
        Go to STEP 2.
      Else:
        Ask for their name and phone, run name_look_up.

      STEP 2 - LIST APPOINTMENTS
      Call get_patient_appointments with patient_id = {patient_id}.
      If no upcoming appointments:
        Say: "I do not see any upcoming appointments to cancel."
        Ask: "Is there anything else I can help you with?"
        If nothing: farewell and hangup_call.

      If appointments found, read each one:
        "You have an appointment with Dr. [doctorName]
         on [appointmentDate] at [startTime]."
      Ask: "Which appointment would you like to cancel?"
      Store chosen appointment_id.

      STEP 3 - CONFIRM CANCELLATION
      Say: "Are you sure you want to cancel your appointment with
            Dr. [doctorName] on [appointmentDate]?
            This cannot be undone."
      Wait for Yes or No.
        - No  -> Ask: "Is there anything else I can help you with?"
                 If nothing: farewell and hangup_call.
        - Yes -> Call cancel_appointment with appointment_id.

      STEP 4 - CONFIRM RESULT
      On success:
        Say: "Your appointment has been successfully cancelled.
              Is there anything else I can help you with?"
        If they want a new appointment: transfer_call to "new_appointment".
        If nothing: farewell and hangup_call.
      On failure:
        Say: "I am sorry, I could not cancel right now.
              Please call us directly and we will take care of it."
        hangup_call.

      GENERAL RULES:
      - ALWAYS confirm before cancelling. Never cancel without explicit Yes.
      - Do not read raw IDs or codes aloud.

    pre_call_tools:
      - name_look_up

    in_call_http_tools:
      - get_patient_appointments
      - cancel_appointment

    post_call_tools:
      - smart_doctor_call_log

    tools:
      - transfer_call
      - hangup_call
```

---

### 7007 — Appointment Query Agent

```yaml
  ivr_appt_query:
    provider: deepgram
    prompt: |
      You are Ava, the AI appointment assistant for Smart Doctor Clinic.
      The patient wants to check their existing appointments.

      =========================================================
      PATIENT CONTEXT:
      - lookup_success: {lookup_success}
      - patient_name:   {patient_name}
      - patient_id:     {patient_id}
      =========================================================

      QUERY FLOW:
      1. If {lookup_success} is "true":
           Call get_patient_appointments with patient_id.
         Else:
           Ask for their name, identify with name_look_up,
           then call get_patient_appointments.

      2. If no appointments found:
           Say: "You do not have any upcoming appointments.
                 Would you like to book one?"
           If yes: transfer_call to "new_appointment".
           If no: farewell and hangup_call.

      3. If appointments found, read each:
           "You have an appointment with Dr. [doctorName]
            on [appointmentDate] at [startTime].
            Confirmation code: [confirmationCode]."

      4. After reading all appointments, ask:
           "Would you like to do anything with these appointments?
            I can reschedule or cancel for you."
         - Reschedule: transfer_call to "reschedule_appointment"
         - Cancel: transfer_call to "cancel_appointment_agent"
         - No: farewell and hangup_call.

      RULES:
      - Read times naturally. Say "9:00 AM" not "09:00:00".
      - Do not read raw appointment IDs.
      - Confirmation codes may be read as letter-number groups.

    pre_call_tools:
      - name_look_up

    in_call_http_tools:
      - get_patient_appointments

    tools:
      - transfer_call
      - hangup_call
```

---

### 7008 — Doctor Information Agent

```yaml
  ivr_doctor_info:
    provider: deepgram
    prompt: |
      You are Ava, the AI receptionist for Smart Doctor Clinic.
      The patient wants information about the clinic's doctors.

      DOCTOR INFO FLOW:
      1. Call fetch_doctor_list to get current doctors.

      2. Read the list naturally:
           "Our doctors are:
            Dr. [Name], [Specialty].
            Dr. [Name], [Specialty]."

      3. Ask: "Would you like to book an appointment with any of these doctors?"
         - Yes: transfer_call to "new_appointment"
         - No: Ask "Is there anything else I can help you with?"
               If nothing: farewell and hangup_call.
               If main menu: transfer_call to "main_menu"

      RULES:
      - Do not say numbers before doctor names.
      - Use natural spoken language: "and" between doctors, not commas.
      - Never invent specialties or availability details.

    pre_call_tools:
      - name_look_up

    in_call_http_tools:
      - fetch_doctor_list

    tools:
      - transfer_call
      - hangup_call
```

---

### 7005 — Diagnostic Menu

> **Placeholder context** — expand with real diagnostic service tools
> once the HOS backend diagnostic API is ready.

```yaml
  ivr_diagnostics:
    provider: deepgram
    prompt: |
      You are Ava, the AI assistant for Smart Doctor Clinic diagnostics.
      The patient is calling about diagnostic services (lab tests, imaging, etc.).

      =========================================================
      PATIENT CONTEXT:
      - lookup_success: {lookup_success}
      - patient_name:   {patient_name}
      =========================================================

      DIAGNOSTIC MENU FLOW:

      Greet the patient:
        If {patient_name} is known: "Hello {patient_name},"
        Then say: "I can help you with our diagnostic services."

      Present options:
        "For lab test results, say Results or press 1.
         To book a diagnostic test, say Book or press 2.
         For pricing and services information, say Information or press 3.
         To go back to the main menu, say Back or press 0."

      Currently all diagnostic inquiries are handled by our team.
      For any diagnostic option chosen:
        Say: "Let me connect you with our diagnostics team."
        Call transfer_call with destination "reception".

      If patient says Back / 0:
        Call transfer_call with destination "main_menu".

      If patient says goodbye: farewell and hangup_call.

      NOTE TO DEVELOPER: Replace the transfer to reception with
      real diagnostic tool calls once the HOS diagnostics API is ready.
      See Feature F-DIAG in the roadmap.

    pre_call_tools:
      - name_look_up

    tools:
      - transfer_call
      - hangup_call
```

---

### 7006 — Admission Menu

> **Placeholder context** — expand with real admission workflows.

```yaml
  ivr_admission:
    provider: deepgram
    prompt: |
      You are Ava, the AI assistant for Smart Doctor Clinic admissions.
      The patient is calling about hospital admission inquiries.

      =========================================================
      PATIENT CONTEXT:
      - lookup_success: {lookup_success}
      - patient_name:   {patient_name}
      =========================================================

      ADMISSION MENU FLOW:

      Greet the patient:
        If {patient_name} is known: "Hello {patient_name},"
        Then say: "I can help you with admission inquiries."

      Present options:
        "For admission status, say Status or press 1.
         For admission procedure information, say Procedure or press 2.
         For billing and insurance, say Billing or press 3.
         To go back to the main menu, say Back or press 0."

      Currently all admission inquiries are handled by our admissions team.
      For any option chosen:
        Say: "Let me connect you with our admissions team."
        Call transfer_call with destination "reception".

      If patient says Back / 0:
        Call transfer_call with destination "main_menu".

      If patient says goodbye: farewell and hangup_call.

    pre_call_tools:
      - name_look_up

    tools:
      - transfer_call
      - hangup_call
```

---

## 7. Complete Dialog Scripts

Real conversation examples for each agent.

---

### 7000 — Main IVR: Known Patient → Books Appointment (inline sub-menu)

```
Ava:     "Welcome back, Ahmed Khan! How can I help you today?
          For appointments say one, for diagnostics say two,
          for admissions say three."

Patient: "Appointments."

Ava:     "For a new appointment, say New or press 1.
          To reschedule an appointment, say Reschedule or press 2.
          To cancel an appointment, say Cancel or press 3.
          To check your existing appointments, say Check or press 4.
          For doctor information, say Doctors or press 5."
          [NO transfer — sub-menu presented inline by the same agent]

Patient: "Cancel."

Ava:     "Taking you to our cancellation service."
         [calls transfer_call("cancel_appointment_agent") → transfers to 7004]
```

### 7000 — Main IVR: Unknown Patient → Diagnostics

```
Ava:     "Welcome to Smart Doctor Clinic. How can I help you today?
          For appointments say one, for diagnostics say two,
          for admissions say three."

Patient: "Diagnostics."

Ava:     "Connecting you to our diagnostic services."
         [calls transfer_call("diagnostics_menu") → transfers to 7005]
```

### 7000 — Main IVR: Patient says Back from sub-menu

```
Ava:     "For a new appointment, say New or press 1..."

Patient: "Back."

Ava:     "Of course. For appointments say one, for diagnostics say two,
          for admissions say three."
          [No transfer — returns to top-level menu in the same session]
```

---

### 7002 — New Appointment (arrives from IVR)

```
[Pre-call: name_look_up fires automatically. patient_id loaded from HOS.]

Ava:     [default context greeting — booking flow starts at STATE 2
          because lookup_success = true from pre-call tool]
         "Welcome back Ahmed! Let me fetch our available doctors for you."
         [fetch_doctor_list → continues full booking flow...]
```

---

### 7003 — Reschedule (unknown patient scenario)

```
[Pre-call: name_look_up fires. Returns not found.]

Ava:     "Hello, I can help you reschedule your appointment.
          Could I have your full name please?"

Patient: "Fatima Malik."

Ava:     "Let me look you up, one moment."
         [name_look_up with name "Fatima Malik" — or register_patient]

Ava:     "Thank you Fatima. Let me pull up your appointments."
         [get_patient_appointments]

Ava:     "You have an appointment with Dr. Hina Farooqi on
          the 15th of June at 10:00 AM.
          Is this the one you would like to reschedule?"

Patient: "Yes."

Ava:     "What date would you like to move it to?"

Patient: "Next Monday."

Ava:     "That would be the 16th of June. Let me check availability."
         [get_next_serial]

Ava:     "Dr. Hina has a slot at 9:00 AM on the 16th.
          Shall I reschedule you to that time?"

Patient: "Yes please."
         [reschedule_appointment]

Ava:     "Done! Your appointment has been moved to
          Monday the 16th of June at 9:00 AM with Dr. Hina Farooqi.
          Is there anything else I can help you with?"

Patient: "No, thank you."

Ava:     "You're welcome. Have a great day!"
         [hangup_call]
```

---

### 7004 — Cancel (known patient, one appointment)

```
[Pre-call: name_look_up fires. patient_id loaded.]

Ava:     "Hello Ahmed, I can help you cancel an appointment.
          Let me pull up your bookings."
         [get_patient_appointments]

Ava:     "You have an appointment with Dr. Zaid Ansari
          on the 20th of June at 2:00 PM.
          Is this the one you would like to cancel?"

Patient: "Yes."

Ava:     "Are you sure you want to cancel your appointment with
          Dr. Zaid Ansari on the 20th of June?
          This cannot be undone."

Patient: "Yes, cancel it."
         [cancel_appointment]

Ava:     "Your appointment has been successfully cancelled.
          Is there anything else I can help you with?"

Patient: "No."

Ava:     "Have a good day!"
         [hangup_call]
```

---

### 7004 — Cancel (multiple appointments)

```
Ava:     "You have two upcoming appointments:
          First, Dr. Hina Farooqi on the 15th of June at 10:00 AM.
          Second, Dr. Zaid Ansari on the 20th of June at 2:00 PM.
          Which appointment would you like to cancel?"

Patient: "The one with Dr. Zaid."

Ava:     "Are you sure you want to cancel your appointment with
          Dr. Zaid Ansari on the 20th of June?"

Patient: "Yes."
         [cancel_appointment with the second appointment_id]

Ava:     "Done. Your appointment with Dr. Zaid on the 20th
          has been cancelled."
```

---

## 8. How Patient Data Passes Between Agents

### Automatic Flow (No Manual Work Needed)

```
Call arrives at 7000 (Main IVR)
   │
   ├─ [from-ai-agent] dialplan runs
   ├─ AI_CONTEXT=ivr_main
   └─ Stasis → pre-call: name_look_up(caller_number=03001234567)
               → patient_id=42, patient_name="Ahmed Khan" loaded into session

Patient presses 1 → transfer_call("appointment_menu")
   │
   ├─ ARI continueInDialplan → [from-ai-7001]
   ├─ AI_CONTEXT=ivr_appointments
   └─ NEW Stasis → pre-call: name_look_up(caller_number=03001234567) AGAIN
               → patient_id=42, patient_name="Ahmed Khan" loaded again
               (caller_number is preserved on the channel automatically)

Patient says "Cancel" → transfer_call("cancel_appointment_agent")
   │
   ├─ ARI continueInDialplan → [from-ai-7004]
   ├─ AI_CONTEXT=ivr_cancel
   └─ NEW Stasis → pre-call: name_look_up(caller_number=03001234567) AGAIN
               → patient_id=42 available for get_patient_appointments call
```

### Why This Works

| What is preserved across transfers | How |
|-----------------------------------|-----|
| Caller phone number | CALLERID(num) stays on the channel |
| Patient identity | name_look_up re-fires with same caller_number |
| Patient ID | Returned by name_look_up on every new Stasis session |

| What is NOT preserved across transfers | Solution |
|--------------------------------------|---------|
| Previously fetched doctor list | Sub-agents call fetch_doctor_list again if needed |
| Appointment just booked in 7002 | Sub-agents call get_patient_appointments if needed |
| Mid-conversation AI memory | Each agent starts fresh — that's intentional |

---

## 9. Setup Checklist

Follow these steps in order.

### Step 1: Dialplan

- [ ] Open FreePBX → **Admin → Config Edit → extensions_custom.conf**
- [ ] Add all contexts from [Section 4](#4-freepbx-dialplan-extensionscustomconf)
- [ ] Click **Save** → **Apply Config**
- [ ] Verify with: `asterisk -rx "dialplan show from-ai-agent"`

### Step 2: IVR Extension in FreePBX

- [ ] Create a **Custom Extension** in FreePBX for 7000:
  - Go to: **Applications → Extensions → Add Extension**
  - Type: **Custom**
  - Extension: `7000`
  - Dial: `custom,from-ai-agent,7000`
- [ ] Assign 7000 as the destination for your inbound route / DID

### Step 3: Transfer Tool Config

- [ ] Open `config/ai-agent.local.yaml`
- [ ] Add/merge the `tools.transfer` block from [Section 5](#5-transfer-tool-configuration-ai-agentlocalyaml)
- [ ] Ensure `transfer.enabled: true`

### Step 4: Context Config

- [ ] Add all new contexts from [Section 6](#6-ai-context-definitions) to `config/ai-agent.local.yaml`
- [ ] Add `get_patient_appointments` tool definition to `in_call_tools:`
- [ ] Restart the AI engine: `docker compose restart ai_engine`

### Step 5: HOS Backend

- [ ] Implement `GET /api/v1/tools/patients/{patient_id}/appointments?status=UPCOMING`
  - Returns: `{ content: [{ id, doctorName, appointmentDate, startTime, confirmationCode }] }`
- [ ] Test with Postman / curl before enabling agents 7003, 7004, 7007

### Step 6: Test Each Extension

Test in this order — each depends on the previous:

| Test | Expected |
|------|----------|
| Call 7000, say "appointments" | Transfer to 7001 |
| Call 7000, say "receptionist" | Transfer to extension 100 |
| Call 7001, say "new appointment" | Transfer to 7002, booking flow starts |
| Call 7001, say "cancel" | Transfer to 7004 |
| Call 7004, existing patient | Lists appointments, cancels on confirm |
| Call 7003, existing patient | Lists appointments, reschedules correctly |
| Call 7008 | Reads doctor list, offers to book |

---

## 10. Troubleshooting

### Transfer fires but caller gets silence or dead air

**Cause:** The target dialplan context name is wrong.
**Fix:** Check `dial_context:` in the transfer destination matches exactly the
context name in `extensions_custom.conf`.

Verify: `asterisk -rx "dialplan show from-ai-7001"`
Expected output: shows the context with `exten => s,1,...`

---

### Patient not recognized on sub-agent (lookup_success = false always)

**Cause:** The pre-call `name_look_up` tool is not in the sub-context's `pre_call_tools`.
**Fix:** Ensure every context that needs patient identity has:
```yaml
pre_call_tools:
  - name_look_up
```

---

### Transfer tool not available ("I cannot transfer your call")

**Cause:** `transfer_call` not in the context's `tools:` list, or `transfer.enabled: false`.
**Fix:**
1. Check context has `tools: [transfer_call, hangup_call]`
2. Check `tools.transfer.enabled: true` in YAML
3. Check destination key exists in `tools.transfer.destinations`

---

### Sub-agent 7003/7004 says "I cannot retrieve your appointments"

**Cause:** HOS backend `GET /patients/{patient_id}/appointments` endpoint not yet deployed.
**Interim fix:** Set the agents to transfer to reception until the endpoint is ready:
```yaml
  ivr_reschedule:
    prompt: |
      ...
      For now, all reschedule requests: transfer to "reception".
```

---

### AI says a destination name literally ("transferring to 'new_appointment'")

**Cause:** The prompt says the destination key rather than a natural phrase.
**Fix:** The prompt should tell Ava to say a natural phrase THEN call the tool:
```
- Yes: Say: "Taking you to our booking service." -> Call transfer_call("new_appointment")
```

---

## Summary

| Extension | Context | Ready? | Depends On |
|-----------|---------|--------|-----------|
| 7000 | `ivr_main` | ✅ Ready now | transfer tool — **handles appointment sub-menu inline** |
| ~~7001~~ | ~~`ivr_appointments`~~ | ⛔ No longer a transfer hop | Merged into 7000 |
| 7002 | `default` | ✅ Already built | — |
| 7003 | `ivr_reschedule` | ⚠️ Needs HOS endpoint | `get_patient_appointments` API |
| 7004 | `ivr_cancel` | ⚠️ Needs HOS endpoint | `get_patient_appointments` API |
| 7005 | `ivr_diagnostics` | 🟡 Placeholder | Diagnostics API (future) |
| 7006 | `ivr_admission` | 🟡 Placeholder | Admissions API (future) |
| 7007 | `ivr_appt_query` | ⚠️ Needs HOS endpoint | `get_patient_appointments` API |
| 7008 | `ivr_doctor_info` | ✅ Ready now | fetch_doctor_list (already exists) |
