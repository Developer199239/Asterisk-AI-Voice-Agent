# Follow-up Reminders & Outbound Call Queue — Implementation Reference v2

**Last updated:** 2026-07-11  
**Status:** Fully implemented ✅  
**Changes from v1:** Added full Asterisk + AI Engine execution detail (4 call scenarios, AMD detection, extension encoding, dual result-reporting paths, engine tools)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Database Schema](#2-database-schema)
3. [Follow-up Reminder Flow (End-to-End)](#3-follow-up-reminder-flow-end-to-end)
4. [Outbound Call Queue — Serial Execution](#4-outbound-call-queue--serial-execution)
5. [Asterisk + AI Engine — Call Execution Detail](#5-asterisk--ai-engine--call-execution-detail)
   - [5.1 Extension Encoding Format](#51-extension-encoding-format)
   - [5.2 Asterisk Dialplan Flow](#52-asterisk-dialplan-flow)
   - [5.3 AMD (Answering Machine Detection)](#53-amd-answering-machine-detection)
   - [5.4 The 4 Call Scenarios](#54-the-4-call-scenarios)
   - [5.5 AI Engine — Outbound Conversation](#55-ai-engine--outbound-conversation)
6. [Result Reporting — Two Paths](#6-result-reporting--two-paths)
7. [Webhook — Call Result](#7-webhook--call-result)
8. [Lead-Based Follow-ups (Staff UI)](#8-lead-based-follow-ups-staff-ui)
9. [Frontend Pages](#9-frontend-pages)
10. [API Reference](#10-api-reference)
11. [Configuration Reference](#11-configuration-reference)
12. [Status Lifecycles](#12-status-lifecycles)
13. [Edge Cases & Recovery](#13-edge-cases--recovery)
14. [Backend Module Map](#14-backend-module-map)

---

## 1. System Overview

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  INBOUND CALL  (Patient calls clinic)                                          │
│  Phone → Asterisk ARI → AI Engine (Deepgram/Ava)                              │
│                                                                                │
│  STATE 5 (booking confirmed):                                                  │
│  Ava: "Would you like a reminder call 1 hour before?"                         │
│  Patient: "Yes"                                                                │
│  AI → POST /api/v1/tools/follow-ups  (X-API-Key auth)                         │
└──────────────────────┬─────────────────────────────────────────────────────────┘
                       │  Saves row in follow_up_requests
                       │  status = PENDING, scheduled_at = appt_time − 60 min
                       │
               ┌───────▼──────────────────────────┐
               │  HOS Backend — FollowUpScheduler  │
               │  Polls every 60 seconds            │
               └───────┬──────────────────────────┘
                       │  PENDING rows where scheduled_at ≤ NOW
                       │  → enqueue() to outbound_call_queue
                       │  → markSent() follow_up_requests → SENT
                       │
               ┌───────▼────────────────────────────────────────────────────────┐
               │  HOS Backend — OutboundQueueService (serial executor)          │
               │  1. DB guard: any TRIGGERED item? → skip                       │
               │  2. Engine guard: GET /outbound/context-status → busy? skip    │
               │  3. SELECT FOR UPDATE SKIP LOCKED → mark oldest PENDING        │
               │     → TRIGGERED                                                 │
               │  4. POST /api/outbound/trigger → AI Engine                     │
               └───────┬────────────────────────────────────────────────────────┘
                       │
               ┌───────▼────────────────────────────────────────────────────────┐
               │  AI Engine Admin UI (Node.js)                                  │
               │  Receives trigger → ARI originate                              │
               │  Local/PHONE_APPTID_PATID@from-ai-outbound                     │
               └───────┬────────────────────────────────────────────────────────┘
                       │
               ┌───────▼────────────────────────────────────────────────────────┐
               │  Asterisk PBX                                                  │
               │  Dials patient (20 s timeout) → runs AMD sub-routine           │
               │                                                                 │
               │  MACHINE / NOTSURE → hang up silently (5-min cron handles)    │
               │  HUMAN / INITIALSILENCE / TOOLONG → bridge to AI Engine       │
               │  NO ANSWER / BUSY → SHELL curl → /tools/call-result           │
               └───────┬────────────────────────────────────────────────────────┘
                       │  Audio bridged via AudioSocket (TCP 8090)
               ┌───────▼────────────────────────────────────────────────────────┐
               │  AI Engine — Ava (Deepgram Voice Agent)                        │
               │  context: outbound_reminder                                    │
               │  Greets patient → Confirm / Cancel / Reschedule / Hang up     │
               │  After call: POST /api/v1/tools/call-logs (transcript)         │
               │              → HOS backend sets call_result = "answered"       │
               └───────┬────────────────────────────────────────────────────────┘
                       │
               ┌───────▼────────────────────────────────────────────────────────┐
               │  Staff UI  (hospital-os-web)                                   │
               │  /follow-ups      — full reminder history (appointment + lead) │
               │  /outbound-queue  — live PENDING + TRIGGERED items             │
               └────────────────────────────────────────────────────────────────┘
```

---

## 2. Database Schema

### `follow_up_requests` (V17 + V24 + V25)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | Multi-tenant scope |
| `appointment_id` | BIGINT → `appointments(id)` | NULL for lead-based rows |
| `patient_id` | BIGINT → `patients(id)` | NULL for lead-based rows |
| `lead_id` | BIGINT → `leads(id)` | NULL for appointment-based rows |
| `reminder_type` | VARCHAR(20) | `CALL` or `SMS` |
| `minutes_before` | INT | 60 for appointment-based; 0 for lead-based |
| `status` | VARCHAR(20) | `PENDING` → `SENT` / `FAILED` / `CANCELLED` |
| `scheduled_at` | TIMESTAMP | Computed (appt − minutes_before) or staff-chosen |
| `triggered_at` | TIMESTAMP | Set when scheduler fires the call |
| `retry_count` | INT | Incremented on each failure (max 3) |
| `call_result` | VARCHAR(20) | `confirmed`, `cancelled`, `no_answer`, etc. |
| `last_error` | TEXT | Error detail on failure |
| `created_at` | TIMESTAMP | Auto |

**Constraints:**
- `chk_follow_up_source`: `appointment_id IS NOT NULL OR lead_id IS NOT NULL`
- `chk_minutes_before_pos`: `minutes_before >= 0`
- Unique index on `(appointment_id, reminder_type)` WHERE `appointment_id IS NOT NULL`
- Unique index on `(lead_id, reminder_type)` WHERE `lead_id IS NOT NULL`

---

### `outbound_call_queue` (V19 + V20 + V21)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | |
| `phone_number` | VARCHAR(20) | Patient's phone |
| `patient_id` | BIGINT | |
| `patient_name` | VARCHAR(100) | |
| `appointment_id` | BIGINT | |
| `doctor_name` | VARCHAR(100) | |
| `appointment_date` | DATE | |
| `start_time` | TIME | |
| `context` | VARCHAR(50) | Always `outbound_reminder` |
| `status` | VARCHAR(20) | `PENDING` → `TRIGGERED` → `DONE` / `FAILED` |
| `created_at` | TIMESTAMPTZ | |
| `triggered_at` | TIMESTAMPTZ | Set when call is fired |
| `completed_at` | TIMESTAMPTZ | Set on DONE |
| `call_result` | VARCHAR(20) | From webhook / voicemail timeout |
| `error_message` | TEXT | On FAILED |
| `retry_count` | INT | |

---

## 3. Follow-up Reminder Flow (End-to-End)

### Step 1 — Patient opts in during inbound call

AI Engine calls `POST /api/v1/tools/follow-ups` (X-API-Key auth) at STATE 5 of the booking flow:

```json
{
  "appointmentId": 101,
  "patientId": 42,
  "reminderType": "CALL",
  "minutesBefore": 60
}
```

**`FollowUpService.save()`:**
1. Looks up the appointment to get its date + time
2. Computes `scheduledAt = appointmentDateTime − minutesBefore`
3. Idempotency check: if `(appointmentId, reminderType)` already exists → returns existing record (safe for AI retries)
4. Saves new `FollowUpRequest` with `status = PENDING`

---

### Step 2 — Scheduler polls for due reminders

`FollowUpScheduler.fireReminders()` — every 60 seconds:

```java
@Scheduled(fixedDelayString = "${app.followup.scheduler-fixed-delay-ms:60000}")
public void fireReminders() {
    List<FollowUpReminderView> due = followUpService.findPendingDueForTrigger();
    for (FollowUpReminderView f : due) {
        outboundQueueService.enqueue(f);      // → outbound_call_queue PENDING
        followUpService.markSent(f.getId());  // follow_up_requests → SENT
    }
}
```

**Query criteria:** `status = 'PENDING'` AND `scheduled_at <= NOW() + 30 seconds`

The query LEFT JOINs `appointments`, `patients`, `doctors`, and `leads` — full outbound payload in one shot.

---

### Step 3 — OutboundQueueService processes the queue

After `enqueue()` inserts the row, it immediately calls `processQueue("outbound_reminder")` — see [Section 4](#4-outbound-call-queue--serial-execution).

---

## 4. Outbound Call Queue — Serial Execution

Only **one** outbound call runs at a time. `processQueue()` enforces this with two layered guards:

```
processQueue("outbound_reminder")
│
├─ 1. DB guard: SELECT count(*) FROM outbound_call_queue WHERE status='TRIGGERED'
│       └─ > 0 → return early (webhook will advance when call ends)
│
├─ 2. Engine guard: GET /outbound/context-status?context=outbound_reminder
│       └─ busy → return early
│       └─ HTTP error → assume free, continue
│
├─ 3. OutboundQueuePersistence.pickAndMarkTriggered()
│       SELECT id FROM outbound_call_queue
│       WHERE status='PENDING' AND context='outbound_reminder'
│       ORDER BY created_at ASC
│       LIMIT 1 FOR UPDATE SKIP LOCKED
│       → UPDATE status='TRIGGERED', triggered_at=NOW()
│       (Separate @Transactional bean to avoid Spring proxy self-call bypass)
│
└─ 4. doTriggerHttp(item)
        POST /api/outbound/trigger
        X-Api-Key: <OUTBOUND_TRIGGER_API_KEY>
        { phone_number, patient_id, patient_name, appointment_id,
          doctor_name, appointment_date, start_time, context }
        └─ HTTP fails → mark item FAILED
```

**Why `SELECT FOR UPDATE SKIP LOCKED`?** Prevents two concurrent HOS instances from picking the same queue row when running in a cluster.

**Why a separate `@Transactional` bean (`OutboundQueuePersistence`)?** Spring proxies only intercept calls between beans. A `@Transactional` method calling another `@Transactional` method on `this` bypasses the proxy — the inner transaction never starts. Splitting into a separate bean guarantees the `SELECT FOR UPDATE` runs in its own real transaction.

### Recovery cron

`recoverStuckItems()` — every 5 minutes:
- Finds TRIGGERED items older than `stuck-timeout-minutes` (default: 5 min)
- Marks them DONE with `call_result = 'no_answer'`
- Calls `processQueue()` to advance to the next caller

Handles AMD-detected voicemail and engine crashes where no webhook ever fires.

---

## 5. Asterisk + AI Engine — Call Execution Detail

### 5.1 Extension Encoding Format

The AI Engine sends an ARI originate for a **Local channel** that encodes three values in the extension string:

```
Local/6002_29_3@from-ai-outbound
       │    │  └─ patient_id     = 3
       │    └──── appointment_id = 29
       └───────── phone_number   = 6002
```

**Why encode in the extension?** A Local channel has two legs: `Local;1` (enters Stasis/AI engine) and `Local;2` (runs the dialplan). ARI channel variables only reach the `Local;1` side. The dialplan side (`Local;2`) reads the appointment and patient IDs via `CUT(EXTEN,_,2)` and `CUT(EXTEN,_,3)` so it can include them in the result webhook curl.

---

### 5.2 Asterisk Dialplan Flow

**Context:** `[from-ai-outbound]` | **Pattern:** `_X.` (matches `6002_29_3` format)

```asterisk
[from-ai-outbound]
exten => _X.,1,NoOp(AI Outbound Reminder - exten=${EXTEN})
 same => n,Set(DIAL_NUMBER=${CUT(EXTEN,_,1)})
 same => n,Set(APPOINTMENT_ID=${CUT(EXTEN,_,2)})
 same => n,Set(PATIENT_ID=${CUT(EXTEN,_,3)})
 same => n,Dial(PJSIP/${DIAL_NUMBER},20,U(sub-amd-check,s,1))
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,Set(CALL_RESULT=${IF($["${DIALSTATUS}"="BUSY"]?busy:no_answer)})
 same => n,Set(IGNORED=${SHELL(curl -s -X POST .../call-result ...)})
 same => n(done),Hangup()

; Hangup handler — safety net if Local;1 (engine) disconnects mid-dial
exten => h,1,GotoIf($["${CALL_RESULT}" != ""]?done)
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,GotoIf($["${APPOINTMENT_ID}" = ""]?done)
 same => n,Set(CALL_RESULT=no_answer)
 same => n,Set(IGNORED=${SHELL(curl -s -X POST .../call-result ...)})
 same => n(done),NoOp(Hangup handler done)
```

Key dial option: `U(sub-amd-check,s,1)` — runs the AMD subroutine **on the called party's channel** immediately after they answer, before audio is bridged to the AI engine.

---

### 5.3 AMD (Answering Machine Detection)

**Parameters:** `AMD(2000, 2000, 1000, 5000)`

| Parameter | Value | Meaning |
|---|---|---|
| Initial silence | 2000 ms | Max silence before first word |
| Greeting | 2000 ms | Max greeting duration |
| After-greeting silence | 1000 ms | Silence after greeting → classified as human |
| Total analysis time | 5000 ms | Hard cutoff |

**Decision logic (in `[sub-amd-check]`):**

```
AMDCAUSE starts with "TOOLONG"         → treat as HUMAN  (long greeting = live person)
AMDCAUSE starts with "INITIALSILENCE"  → treat as HUMAN  (patient picked up, waiting silently)
AMDSTATUS = "HUMAN"                    → treat as HUMAN  → Return() → audio bridges to Ava
AMDSTATUS = "MACHINE"                  → Hangup()        → no webhook fired
AMDSTATUS = "NOTSURE"                  → Hangup()        → no webhook fired
```

> **Why INITIALSILENCE = HUMAN?** When a patient answers but hasn't spoken yet, AMD classifies it as `MACHINE` with cause `INITIALSILENCE`. This is actually a human waiting to hear who is calling. The dialplan overrides this to connect them to Ava instead of hanging up.

When AMD hangs up silently (MACHINE/NOTSURE), no webhook fires. The **5-minute stuck recovery cron** in `OutboundQueueService` handles these rows.

---

### 5.4 The 4 Call Scenarios

#### Scenario A — No Answer (patient doesn't pick up)

```
HOS Backend
 └─ POST /api/outbound/trigger → AI Engine Admin UI
     └─ ARI originate Local/6002_29_3@from-ai-outbound
         └─ Asterisk dials PJSIP/6002  (20 s timeout)
             └─ [rings 20 s, no answer]
                 └─ DIALSTATUS = NOANSWER
                     └─ Asterisk SHELL curl → POST /tools/call-result { result: "no_answer" }
                         └─ HOS: outbound_call_queue DONE, call_result = no_answer
                                 processQueue() → fires next PENDING item
```

#### Scenario B — Busy / Declined

```
HOS Backend
 └─ POST /api/outbound/trigger → AI Engine Admin UI
     └─ ARI originate Local/6002_29_3@from-ai-outbound
         └─ Asterisk dials PJSIP/6002
             └─ [patient declines / line busy]
                 └─ DIALSTATUS = BUSY
                     └─ Asterisk SHELL curl → POST /tools/call-result { result: "busy" }
                         └─ HOS: outbound_call_queue DONE, call_result = busy
                                 processQueue() → fires next PENDING item
```

#### Scenario C — Voicemail (machine detected)

```
HOS Backend
 └─ POST /api/outbound/trigger → AI Engine Admin UI
     └─ ARI originate Local/6002_29_3@from-ai-outbound
         └─ Asterisk dials PJSIP/6002
             └─ [voicemail picks up after ~4 rings]
                 └─ AMD detects MACHINE
                     └─ Asterisk hangs up immediately — NO WEBHOOK FIRED
                         └─ HOS 5-minute stuck recovery cron
                             └─ Finds TRIGGERED item older than stuck-timeout-minutes
                                 └─ Marks DONE, call_result = no_answer
                                         processQueue() → fires next PENDING item
```

#### Scenario D — Patient Answers (human detected)

```
HOS Backend
 └─ POST /api/outbound/trigger → AI Engine Admin UI
     └─ ARI originate Local/6002_29_3@from-ai-outbound
         └─ Asterisk dials PJSIP/6002
             └─ [patient picks up]
                 └─ AMD detects HUMAN (or INITIALSILENCE / TOOLONG → overridden to HUMAN)
                     └─ Call bridged to AI Engine via AudioSocket (TCP 8090)
                         └─ Ava greets patient and delivers appointment reminder
                             └─ [conversation ends, call hangs up]
                                 └─ AI Engine fires POST /api/v1/tools/call-logs
                                     { context_name: "outbound_reminder", appointmentId, ... }
                                     └─ HOS: saves transcript
                                             call_result = "answered" set internally
                                             processQueue() → fires next PENDING item
```

---

### 5.5 AI Engine — Outbound Conversation

**Context:** `outbound_reminder`  
**Provider:** Deepgram Voice Agent  
**Transport:** AudioSocket (TCP port 8090)

When Asterisk bridges to the engine, the engine:
1. Receives patient data (name, doctor, appointment date/time) from the Local channel arguments
2. Injects them into Ava's system prompt as `APPOINTMENT DETAILS`
3. Ava opens: *"Hello, may I speak with [patient_name]?"*
4. Handles conversation branches:

| Patient response | Ava action |
|---|---|
| Confirms appointment | *"Great! See you then."* → `hangup_call` |
| Cancels appointment | Calls `cancel_appointment` tool → confirms cancellation → `hangup_call` |
| Wants to reschedule | Calls reschedule flow via API tools |
| Wrong person / no response | *"I apologize for the disturbance."* → `hangup_call` |

**Tools available to Ava during outbound call:**

| Tool | Purpose |
|---|---|
| `cancel_appointment` | Cancels the appointment if patient requests |
| `hangup_call` | Ends the call cleanly |
| `transfer` | Transfers to reception desk if needed |

After the call ends, the engine fires `POST /api/v1/tools/call-logs` with the full transcript and `context_name: "outbound_reminder"`.

---

## 6. Result Reporting — Two Paths

There are **two distinct paths** by which a call result reaches HOS — they handle different scenarios:

### Path A — Asterisk dialplan SHELL curl (no_answer / busy)

Fired **by Asterisk** directly, immediately after the call fails without connecting to Ava:

```bash
curl -s -X POST http://168.144.27.225/api/v1/tools/call-result \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-ID: 1' \
  -H 'X-API-Key: dev-api-key-replace-in-production' \
  --data '{"appointmentId":"29","result":"no_answer","patientId":"3"}' \
  --max-time 5
```

Scenarios: `no_answer` (20 s timeout) and `busy` (patient declined)

The **hangup handler** (`exten => h`) fires as a safety net if the Local;1 (AI engine) side disconnects while Dial() is still running — also fires `no_answer`.

---

### Path B — AI Engine call-logs webhook (answered)

Fired **by the AI Engine** after the conversation transcript is ready:

```json
POST /api/v1/tools/call-logs
X-API-Key: <secret>
X-Tenant-ID: 1

{
  "sessionId":       "Local/6002_29_3@from-ai-outbound-00000007;1",
  "callerPhone":     "6002",
  "patientId":       "3",
  "appointmentId":   "29",
  "context_name":    "outbound_reminder",
  "status":          "completed",
  "startedAt":       "2026-06-19T09:00:00Z",
  "endedAt":         "2026-06-19T09:02:30Z",
  "durationSeconds": 150,
  "transcript":      [ ... ]
}
```

HOS backend detects `context_name = "outbound_reminder"` → internally sets `call_result = "answered"` on the queue item.

---

### Path C — Stuck recovery cron (voicemail / silent failure)

When AMD detects a machine, Asterisk hangs up **without firing any webhook**. The 5-minute cron (`recoverStuckItems`) detects the TRIGGERED queue item has been sitting too long and marks it DONE with `call_result = 'no_answer'`.

| Result | Who fires it | When |
|---|---|---|
| `no_answer` | Asterisk SHELL curl | 20 s ring timeout |
| `busy` | Asterisk SHELL curl | Patient declined / line busy |
| `answered` | HOS backend (from call-logs handler) | Patient answered, Ava spoke to them |
| `no_answer` *(fallback)* | HOS 5-min recovery cron | Voicemail (AMD) / engine crash |

---

## 7. Webhook — Call Result

`POST /api/v1/tools/call-result` (X-API-Key auth):

```json
{
  "appointmentId": "29",
  "patientId": "3",
  "result": "no_answer"
}
```

Valid `result` values: `no_answer`, `busy`, `answered`, `confirmed`, `cancelled`, `rescheduled`, `voicemail`

**`ToolOrchestrationService.saveCallResult()` steps:**
1. Updates `follow_up_requests.call_result` for the appointment
2. Updates `appointments.last_call_result` + `last_call_at`
3. Calls `outboundQueueService.markDoneWithResultAndProcessNext(appointmentId, result)`:
   - Finds the TRIGGERED queue item → sets `status = DONE`, `call_result`, `completed_at`
   - Calls `processQueue("outbound_reminder")` → picks next PENDING item and fires it

This webhook is the **primary queue advancement mechanism** for answered and declined calls.

---

## 8. Lead-Based Follow-ups (Staff UI)

Added in V24/V25. Leads don't have appointments — staff choose the `scheduledAt` time directly.

### Staff schedules from the Leads page

```json
POST /api/v1/follow-ups
Authorization: Bearer <JWT>
X-Tenant-ID: 1

{
  "leadId": 9,
  "scheduledAt": "2026-07-12T04:00:00.000Z"
}
```

**`FollowUpService.saveLeadFollowUp()`:**
- `scheduledAt` taken directly (no appointment to compute from)
- `minutesBefore = 0`
- Idempotency: if `(leadId, CALL)` row already exists → updates `scheduledAt`, resets status to `PENDING`

When the scheduler fires a lead-based follow-up, the trigger payload uses `leads.phone` and `leads.name` instead of patient fields. The call itself runs through the same Asterisk + AMD + AI Engine path as appointment-based calls.

---

## 9. Frontend Pages

### `/follow-ups` — Follow-up Reminders

- **Source:** `GET /api/v1/follow-ups?page=0&size=20&sort=scheduledAt,desc`
- **Tabs:** All / Appointment / Leads
  - "Appointment" tab: rows where `appointmentId != null`
  - "Leads" tab: rows where `leadId != null AND appointmentId == null`
- **Customer Type column:** "Lead" (purple) or "Patient" (blue) based on `leadId != null`

Key file: [`frontend/hospital-os-web/src/pages/follow-ups/FollowUpsPage.tsx`](../frontend/hospital-os-web/src/pages/follow-ups/FollowUpsPage.tsx)

---

### `/outbound-queue` — Live Queue

- **Source:** `GET /api/v1/outbound-queue` (PENDING + TRIGGERED only)
- Shows who is waiting, who is currently being called

Key file: [`frontend/hospital-os-web/src/pages/outbound-queue/`](../frontend/hospital-os-web/src/pages/outbound-queue/)

---

### `/leads` — Schedule Follow-up Button

- "Schedule" column visible only at `>= xl` breakpoint; use `⋮` dropdown on smaller screens
- Modal → date picker → `POST /api/v1/follow-ups { leadId, scheduledAt }`
- React Query key `['lead-follow-ups']` invalidated on success

---

## 10. API Reference

### Staff-facing (JWT + `X-Tenant-ID`)

| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/follow-ups` | Paginated history (`status`, `page`, `size`, `sort`) |
| GET | `/api/v1/follow-ups/{id}` | Single record |
| POST | `/api/v1/follow-ups` | Create / reschedule (appointment-based or lead-based) |
| PATCH | `/api/v1/follow-ups/{id}` | Update `status`, `scheduledAt`, `retryCount`, `minutesBefore` |
| GET | `/api/v1/outbound-queue` | Live queue (PENDING + TRIGGERED) |

### AI-facing (X-API-Key + `X-Tenant-ID`)

| Method | URL | Description |
|---|---|---|
| POST | `/api/v1/tools/follow-ups` | AI opts patient into reminder (appointment-based) |
| POST | `/api/v1/tools/call-result` | Call outcome webhook → advances queue |
| POST | `/api/v1/tools/call-logs` | Save call transcript; sets `answered` if `context_name = outbound_reminder` |

### AI Engine (called by HOS)

| Method | URL | Auth |
|---|---|---|
| POST | `/api/outbound/trigger` | `X-Api-Key: OUTBOUND_TRIGGER_API_KEY` |
| GET | `/outbound/context-status?context=outbound_reminder` | `Authorization: Bearer HEALTH_API_TOKEN` |

---

## 11. Configuration Reference

```properties
# Follow-up scheduler (hos-app/application.properties)
app.followup.enabled=true
app.followup.scheduler-fixed-delay-ms=60000    # poll every 60 s
app.followup.timezone=Asia/Dhaka               # ZoneId for scheduled_at
app.followup.outbound-trigger-url=             # http://<engine>:3003/api/outbound/trigger
app.followup.outbound-trigger-api-key=         # matches OUTBOUND_TRIGGER_API_KEY in engine .env

# Outbound queue
app.outbound-queue.engine-context-status-url=  # http://<engine>:3003/outbound/context-status
app.outbound-queue.engine-health-token=        # matches HEALTH_API_TOKEN in engine .env
app.outbound-queue.stuck-timeout-minutes=10    # voicemail/crash recovery window
app.outbound-queue.max-retries=3
```

**Key AI Engine `.env` variables (on the engine server):**

```env
OUTBOUND_TRIGGER_API_KEY=<shared-secret>        # HOS sends this in X-Api-Key
HEALTH_API_TOKEN=<token>                        # HOS sends this in Authorization: Bearer
AAVA_OUTBOUND_DIAL_CONTEXT=from-ai-outbound     # Asterisk dialplan context
ASTERISK_HOST=127.0.0.1
ASTERISK_ARI_PORT=8088
ASTERISK_ARI_USERNAME=asterisk
ASTERISK_ARI_PASSWORD=<password>
AUDIOSOCKET_HOST=<engine-IP>                    # Asterisk must reach this
AUDIOSOCKET_PORT=8090
DEEPGRAM_API_KEY=<key>
AAVA_OUTBOUND_EXTENSION_IDENTITY=+923001234567  # Caller ID shown to patient
```

> **Dev mode:** Leave `app.followup.outbound-trigger-url` blank. Scheduler still fires and marks rows `SENT`; no actual HTTP call is made.

---

## 12. Status Lifecycles

### `follow_up_requests.status`

```
PENDING ──(scheduler fires)──────────────────► SENT
        ──(scheduler fails 3× retries)───────► FAILED
        ──(appointment cancelled)─────────────► CANCELLED
        ──(admin PATCH reset)─────────────────► PENDING  (from FAILED)
```

### `outbound_call_queue.status`

```
PENDING ──(processQueue picks it)──► TRIGGERED ──(call-result webhook)──► DONE
                                          │
                                          ├─(trigger HTTP fails)──────────► FAILED
                                          └─(5-min cron, stuck)───────────► DONE (no_answer)
```

### `outbound_call_queue.call_result` values

| Value | Set by | Scenario |
|---|---|---|
| `no_answer` | Asterisk SHELL curl | 20 s ring, nobody answered |
| `busy` | Asterisk SHELL curl | Patient declined / line busy |
| `answered` | HOS backend (call-logs handler) | Patient answered, Ava spoke to them |
| `no_answer` | HOS 5-min recovery cron | Voicemail (AMD machine detection) or unknown failure |

---

## 13. Edge Cases & Recovery

| Scenario | Handling |
|---|---|
| Engine down when scheduler fires | `isEngineBusy()` catches error → assumes free → trigger attempted. If trigger HTTP also fails → queue item marked `FAILED`. |
| Engine busy when scheduler fires | `processQueue` returns early — item stays `PENDING`. Call-result webhook from the active call advances the queue. |
| Voicemail / AMD detects MACHINE | Asterisk hangs up silently — no webhook. Recovery cron (5 min) marks stuck TRIGGERED item as `DONE (no_answer)` → `processQueue`. |
| INITIALSILENCE (patient picks up silently) | Dialplan overrides AMD's `MACHINE` verdict → treated as `HUMAN` → Ava greets patient. |
| Engine restarts mid-call | Call ends eventually → Asterisk fires SHELL curl (`no_answer`) or engine fires call-logs → queue advances normally. |
| Hangup handler fires (engine disconnects during Dial) | `exten => h` fires → if `CALL_RESULT` not yet set and `APPOINTMENT_ID` known → fires `no_answer` webhook as safety net. |
| Two HOS instances running | `SELECT FOR UPDATE SKIP LOCKED` in `pickAndMarkTriggered` prevents double-trigger. |
| Lead-based row has no patient/appointment | Scheduler LEFT JOINs `leads`; phone + name come from `leads` table; Asterisk extension uses lead phone number. |
| Staff reschedules a lead follow-up | `saveLeadFollowUp` finds existing `(leadId, CALL)` row → updates `scheduledAt`, resets `status = PENDING`. |
| Appointment follow-up already exists | `save()` returns existing record (idempotent — safe for AI to retry on network error). |
| Asterisk IP or API key changes in dialplan | Update `168.144.27.225` and `dev-api-key-replace-in-production` in `extensions_custom.conf` → `asterisk -rx "dialplan reload"`. |

---

## 14. Backend Module Map

| Module | Responsibility |
|---|---|
| `hos-appointment` | `FollowUpRequest` entity, `FollowUpService`, `FollowUpRequestRepository`, `SaveFollowUpRequest` DTO, `FollowUpSummary` / `FollowUpResponse` DTOs |
| `hos-notification` | `FollowUpScheduler`, `OutboundQueueService`, `OutboundQueuePersistence` (separate `@Transactional` bean), `OutboundCallQueue` entity, `OutboundQueueController` |
| `hos-tools` | `ToolController`: `POST /tools/follow-ups`, `POST /tools/call-result`, `POST /tools/call-logs`; `ToolOrchestrationService` delegates to domain services |
| `hos-app` | Flyway migrations V17–V25, `application.properties` config keys |

---

*See also:*
- [`doc/OUTBOUND_REMINDER_CALL_FLOW.md`](OUTBOUND_REMINDER_CALL_FLOW.md) — Asterisk dialplan listing + AMD parameters + environment variables
- [`doc/OUTBOUND_QUEUE_DESIGN.md`](OUTBOUND_QUEUE_DESIGN.md) — original queue design doc
- [`doc/APPOINTMENT_REMINDER_FLOW.md`](APPOINTMENT_REMINDER_FLOW.md) — inbound booking + reminder opt-in flow
