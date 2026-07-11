# Follow-up Reminders & Outbound Call Queue — Implementation Reference v3

**Last updated:** 2026-07-11  
**Status:** Fully implemented ✅  
**Changes from v2:** Dual-context outbound queue — `outbound_reminder` (patient/appointment) vs `outbound_lead` (lead). Each context is an independent serial queue with its own AI engine conversation, Asterisk dialplan, and result webhook routing.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Context Routing — The Core Change](#2-context-routing--the-core-change)
3. [Database Schema](#3-database-schema)
4. [Follow-up Reminder Flow (End-to-End)](#4-follow-up-reminder-flow-end-to-end)
5. [Outbound Call Queue — Serial Execution (Dual Context)](#5-outbound-call-queue--serial-execution-dual-context)
6. [Asterisk + AI Engine — Call Execution by Context](#6-asterisk--ai-engine--call-execution-by-context)
   - [6.1 outbound_reminder — Patient/Appointment Call](#61-outbound_reminder--patientappointment-call)
   - [6.2 outbound_lead — Lead Follow-up Call](#62-outbound_lead--lead-follow-up-call)
   - [6.3 AMD Detection (shared)](#63-amd-detection-shared)
   - [6.4 The 4 Call Scenarios (both contexts)](#64-the-4-call-scenarios-both-contexts)
7. [Result Reporting — Two Paths per Context](#7-result-reporting--two-paths-per-context)
8. [Webhook — Call Result](#8-webhook--call-result)
9. [Lead-Based Follow-ups (Staff UI)](#9-lead-based-follow-ups-staff-ui)
10. [Frontend Pages](#10-frontend-pages)
11. [API Reference](#11-api-reference)
12. [Configuration Reference](#12-configuration-reference)
13. [Status Lifecycles](#13-status-lifecycles)
14. [Edge Cases & Recovery](#14-edge-cases--recovery)
15. [Backend Module Map](#15-backend-module-map)

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  TWO ENTRY POINTS                                                                │
│                                                                                  │
│  A) INBOUND CALL — AI books appointment, patient opts in to reminder             │
│     AI → POST /api/v1/tools/follow-ups  { appointmentId, minutesBefore: 60 }    │
│     → follow_up_requests: appointment_id set, lead_id NULL                       │
│                                                                                  │
│  B) STAFF UI — staff schedules a follow-up for a lead                            │
│     Staff → POST /api/v1/follow-ups  { leadId, scheduledAt }                    │
│     → follow_up_requests: lead_id set, appointment_id NULL                       │
└───────────────────────────┬──────────────────────────────────────────────────────┘
                            │
                ┌───────────▼───────────────────────┐
                │  FollowUpScheduler (every 60 s)    │
                │  Polls PENDING rows due for trigger│
                └───────────┬───────────────────────┘
                            │
             ┌──────────────┴──────────────────┐
             │  lead_id != null?               │
             ▼ YES                             ▼ NO
    context = "outbound_lead"       context = "outbound_reminder"
             │                                 │
    ┌────────▼──────────────┐       ┌──────────▼──────────────┐
    │  Serial Queue         │       │  Serial Queue            │
    │  outbound_lead        │       │  outbound_reminder       │
    │  (independent)        │       │  (independent)           │
    └────────┬──────────────┘       └──────────┬──────────────┘
             │                                 │
    POST /api/outbound/trigger        POST /api/outbound/trigger
    { lead_id, patient_name,          { appointment_id, patient_id,
      context: "outbound_lead" }        doctor_name, ...,
             │                          context: "outbound_reminder" }
             │                                 │
    ┌────────▼──────────────┐       ┌──────────▼──────────────┐
    │  Asterisk             │       │  Asterisk               │
    │  [from-ai-outbound    │       │  [from-ai-outbound]     │
    │   -lead]              │       │                         │
    │  Extension:           │       │  Extension:             │
    │  PHONE_LEADID         │       │  PHONE_APPTID_PATID     │
    └────────┬──────────────┘       └──────────┬──────────────┘
             │  AMD detection (shared sub-amd-check)           │
             │                                 │
    ┌────────▼──────────────┐       ┌──────────▼──────────────┐
    │  Ava — outbound_lead  │       │  Ava — outbound_reminder│
    │  "Hi, I'm calling     │       │  "Hi, I'm calling to    │
    │  re: your interest    │       │  remind you of your     │
    │  in [service]"        │       │  appointment tomorrow"  │
    └────────┬──────────────┘       └──────────┬──────────────┘
             │                                 │
    call-result: { leadId, result }  call-result: { appointmentId, result }
             │                                 │
    HOS → markDoneForLead()          HOS → markDoneForAppointment()
    processQueue("outbound_lead")    processQueue("outbound_reminder")
```

---

## 2. Context Routing — The Core Change

The `follow_up_requests` row determines which context is used:

| Row type | `appointment_id` | `lead_id` | Outbound context | AI conversation |
|---|---|---|---|---|
| Patient reminder | NOT NULL | NULL | `outbound_reminder` | Appointment reminder + confirm/cancel/reschedule |
| Lead follow-up | NULL | NOT NULL | `outbound_lead` | Service interest confirmation + book evaluation |

The routing happens in `OutboundQueuePersistence.insert()`:
```java
boolean isLead = f.getLeadId() != null;
String context = isLead ? "outbound_lead" : "outbound_reminder";
```

The two queues are **completely independent** — they each have their own DB guard, engine guard, and `processQueue()` call. One lead call and one patient reminder call can execute simultaneously.

---

## 3. Database Schema

### `follow_up_requests` (V17 + V24 + V25)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | |
| `appointment_id` | BIGINT | NULL for lead-based rows |
| `patient_id` | BIGINT | NULL for lead-based rows |
| `lead_id` | BIGINT → `leads(id)` | NULL for appointment-based rows |
| `reminder_type` | VARCHAR(20) | `CALL` or `SMS` |
| `minutes_before` | INT | 60 for appointment-based; 0 for lead-based |
| `status` | VARCHAR(20) | `PENDING` → `SENT` / `FAILED` / `CANCELLED` |
| `scheduled_at` | TIMESTAMP | Computed (appt − minutesBefore) or staff-chosen |
| `triggered_at` | TIMESTAMP | Set when scheduler fires |
| `retry_count` | INT | Max 3 |
| `call_result` | VARCHAR(20) | `confirmed`, `no_answer`, etc. |
| `last_error` | TEXT | |
| `created_at` | TIMESTAMP | Auto |

**Constraints:**
- `chk_follow_up_source`: `appointment_id IS NOT NULL OR lead_id IS NOT NULL`
- `chk_minutes_before_pos`: `minutes_before >= 0`
- Unique index on `(appointment_id, reminder_type)` WHERE `appointment_id IS NOT NULL`
- Unique index on `(lead_id, reminder_type)` WHERE `lead_id IS NOT NULL`

---

### `outbound_call_queue` (V19 + V20 + V21 + **V26**)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | |
| `phone_number` | VARCHAR(20) NOT NULL | |
| `patient_id` | BIGINT | NULL for lead rows |
| `patient_name` | VARCHAR(100) | Lead name or patient name |
| `appointment_id` | BIGINT | NULL for lead rows |
| `lead_id` | BIGINT → `leads(id)` | **NEW (V26)** — NULL for appointment rows |
| `doctor_name` | VARCHAR(100) | NULL for lead rows |
| `appointment_date` | DATE | NULL for lead rows |
| `start_time` | TIME | NULL for lead rows |
| `context` | VARCHAR(50) NOT NULL | `outbound_reminder` or `outbound_lead` |
| `status` | VARCHAR(20) NOT NULL | `PENDING` → `TRIGGERED` → `DONE` / `FAILED` |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `triggered_at` | TIMESTAMPTZ | Set when call fires |
| `completed_at` | TIMESTAMPTZ | Set on DONE |
| `call_result` | VARCHAR(20) | From webhook or cron |
| `error_message` | TEXT | On FAILED |
| `retry_count` | INT NOT NULL | |

**V26 migration changes:**
- `patient_id`, `patient_name`, `appointment_id`, `doctor_name`, `appointment_date`, `start_time` → all changed from NOT NULL to nullable
- Added `lead_id BIGINT REFERENCES leads(id) ON DELETE CASCADE`
- Added `idx_outbound_queue_lead_id` index

---

## 4. Follow-up Reminder Flow (End-to-End)

### Step 1 — Create follow-up row

**Path A — AI voice agent during inbound call (appointment-based):**
```json
POST /api/v1/tools/follow-ups   (X-API-Key auth)
{ "appointmentId": 101, "patientId": 42, "reminderType": "CALL", "minutesBefore": 60 }
```
`FollowUpService.save()` computes `scheduledAt = appointmentTime − 60 min`, saves with `appointment_id` set.

**Path B — Staff UI for a lead:**
```json
POST /api/v1/follow-ups   (JWT auth)
{ "leadId": 9, "scheduledAt": "2026-07-12T04:00:00Z" }
```
`FollowUpService.saveLeadFollowUp()` saves with `lead_id` set, `minutesBefore = 0`.

---

### Step 2 — Scheduler polls due rows

`FollowUpScheduler.fireReminders()` — every 60 seconds:

```java
@Scheduled(fixedDelayString = "${app.followup.scheduler-fixed-delay-ms:60000}")
public void fireReminders() {
    List<FollowUpReminderView> due = followUpService.findPendingDueForTrigger();
    for (FollowUpReminderView f : due) {
        outboundQueueService.enqueue(f);      // inserts PENDING row + calls processQueue(context)
        followUpService.markSent(f.getId());  // follow_up_requests → SENT
    }
}
```

The native query now selects `fur.lead_id AS leadId` so the view carries the lead reference.

---

### Step 3 — enqueue() determines context and routes

```java
// OutboundQueuePersistence.insert()
boolean isLead = f.getLeadId() != null;
item.setContext(isLead ? "outbound_lead" : "outbound_reminder");
item.setLeadId(f.getLeadId());
// appointment/doctor/date/time fields left NULL for lead rows

// OutboundQueueService.enqueue()
processQueue(item.getContext());  // passes "outbound_lead" or "outbound_reminder"
```

---

## 5. Outbound Call Queue — Serial Execution (Dual Context)

`processQueue(context)` is context-scoped — the two queues never block each other:

```
processQueue("outbound_lead")              processQueue("outbound_reminder")
│                                          │
├─ DB guard: TRIGGERED for "outbound_lead"?├─ DB guard: TRIGGERED for "outbound_reminder"?
├─ Engine guard: GET /context-status       ├─ Engine guard: GET /context-status
│   ?context=outbound_lead                 │   ?context=outbound_reminder
├─ SELECT FOR UPDATE SKIP LOCKED           ├─ SELECT FOR UPDATE SKIP LOCKED
│   WHERE context='outbound_lead'          │   WHERE context='outbound_reminder'
└─ POST /api/outbound/trigger              └─ POST /api/outbound/trigger
   { lead_id, context: "outbound_lead" }      { appointment_id, context: "outbound_reminder" }
```

**Recovery cron** (`recoverStuckItems` — every 5 min) advances **both** contexts after resolving stuck items:
```java
processQueue(OUTBOUND_REMINDER);
processQueue(OUTBOUND_LEAD);
```

---

## 6. Asterisk + AI Engine — Call Execution by Context

### 6.1 outbound_reminder — Patient/Appointment Call

**Trigger payload from HOS:**
```json
{
  "phone_number":     "6002",
  "patient_id":       "3",
  "patient_name":     "Jalilur Rahman",
  "appointment_id":   "29",
  "doctor_name":      "Dr. Nusrat Jahan",
  "appointment_date": "2026-07-12",
  "start_time":       "09:00",
  "context":          "outbound_reminder"
}
```

**ARI originate extension:**
```
Local/6002_29_3@from-ai-outbound
       │    │  └─ patient_id     = 3
       │    └──── appointment_id = 29
       └───────── phone          = 6002
```

**Asterisk context:** `[from-ai-outbound]`

**SHELL curl on no_answer/busy:**
```bash
--data '{"appointmentId":"29","result":"no_answer","patientId":"3"}'
```

**Ava conversation goal:** Remind patient of tomorrow's appointment → confirm / cancel / reschedule.

---

### 6.2 outbound_lead — Lead Follow-up Call

**Trigger payload from HOS:**
```json
{
  "phone_number": "6001",
  "lead_id":      "9",
  "patient_name": "Sarah Ahmed",
  "context":      "outbound_lead"
}
```

**ARI originate extension:**
```
Local/6001_9@from-ai-outbound-lead
       │   └─ lead_id = 9
       └───── phone   = 6001
```

**Asterisk context:** `[from-ai-outbound-lead]` (new context — same AMD, different SHELL curl)

**SHELL curl on no_answer/busy:**
```bash
--data '{"leadId":"9","result":"no_answer"}'
```

**Ava conversation goal:** Confirm lead's interest in the service → offer to book a service evaluation appointment.

**Asterisk dialplan for `[from-ai-outbound-lead]`:**
```asterisk
[from-ai-outbound-lead]
exten => _X.,1,NoOp(AI Outbound Lead Call - exten=${EXTEN})
 same => n,Set(DIAL_NUMBER=${CUT(EXTEN,_,1)})
 same => n,Set(LEAD_ID=${CUT(EXTEN,_,2)})
 same => n,Dial(PJSIP/${DIAL_NUMBER},20,U(sub-amd-check,s,1))
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,Set(CALL_RESULT=${IF($["${DIALSTATUS}"="BUSY"]?busy:no_answer)})
 same => n,Set(IGNORED=${SHELL(curl -s -X POST http://168.144.27.225/api/v1/tools/call-result \
   -H 'Content-Type: application/json' -H 'X-Tenant-ID: 1' \
   -H 'X-API-Key: dev-api-key-replace-in-production' \
   --data '{"leadId":"${LEAD_ID}","result":"${CALL_RESULT}"}' --max-time 5)})
 same => n(done),Hangup()

exten => h,1,GotoIf($["${CALL_RESULT}" != ""]?done)
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,GotoIf($["${LEAD_ID}" = ""]?done)
 same => n,Set(CALL_RESULT=no_answer)
 same => n,Set(IGNORED=${SHELL(curl -s -X POST http://168.144.27.225/api/v1/tools/call-result \
   -H 'Content-Type: application/json' -H 'X-Tenant-ID: 1' \
   -H 'X-API-Key: dev-api-key-replace-in-production' \
   --data '{"leadId":"${LEAD_ID}","result":"${CALL_RESULT}"}' --max-time 5)})
 same => n(done),NoOp(Hangup handler done)
```

---

### 6.3 AMD Detection (shared)

The `[sub-amd-check]` subroutine is **identical for both contexts** — no changes needed:

```
AMDCAUSE starts with "TOOLONG"         → HUMAN → bridge to Ava
AMDCAUSE starts with "INITIALSILENCE"  → HUMAN → bridge to Ava
AMDSTATUS = "HUMAN"                    → HUMAN → bridge to Ava
AMDSTATUS = "MACHINE"                  → Hangup silently → 5-min cron recovers
AMDSTATUS = "NOTSURE"                  → Hangup silently → 5-min cron recovers
```

---

### 6.4 The 4 Call Scenarios (both contexts)

| Scenario | Who fires result | Payload |
|---|---|---|
| No answer (20 s timeout) | Asterisk SHELL curl | `{ appointmentId/leadId, result: "no_answer" }` |
| Busy / declined | Asterisk SHELL curl | `{ appointmentId/leadId, result: "busy" }` |
| Voicemail (AMD MACHINE) | HOS 5-min recovery cron | Marks DONE `no_answer` by context |
| Patient answers | AI Engine call-logs webhook | `POST /tools/call-logs { context_name: "outbound_reminder/outbound_lead" }` → HOS sets `answered` |

---

## 7. Result Reporting — Two Paths per Context

### Path A — Asterisk SHELL curl (no_answer / busy)

Fired directly by Asterisk after the call fails. Payload differs by context:

**outbound_reminder:**
```bash
--data '{"appointmentId":"29","result":"no_answer","patientId":"3"}'
```

**outbound_lead:**
```bash
--data '{"leadId":"9","result":"no_answer"}'
```

HOS routes in `ToolOrchestrationService.saveCallResult()`:
```java
if (req.leadId() != null) {
    outboundQueueService.markDoneWithResultForLeadAndProcessNext(req.leadId(), req.result());
    followUpService.updateLeadCallResult(req.leadId(), req.result());
} else if (req.appointmentId() != null) {
    outboundQueueService.markDoneWithResultAndProcessNext(req.appointmentId(), req.result());
    followUpService.updateCallResult(req.appointmentId(), req.result());
}
```

---

### Path B — AI Engine call-logs webhook (answered)

Fired after the patient answers and the call transcript is ready.

`ToolOrchestrationService.saveCallLog()`:
```java
// Patient answered a reminder call
if ("outbound_reminder".equals(contextName) && appointmentId != null) {
    outboundQueueService.markDoneWithResultAndProcessNext(appointmentId, "answered");
    followUpService.updateCallResult(appointmentId, "answered");
}
// Lead answered a follow-up call (no appointmentId in payload — find by context)
else if ("outbound_lead".equals(contextName)) {
    outboundQueueService.markDoneWithResultByContextAndProcessNext("outbound_lead", "answered");
}
```

---

### Path C — Recovery cron (voicemail / silent failure)

Runs every 5 minutes. Finds TRIGGERED items older than `stuck-timeout-minutes` → marks DONE `no_answer` → advances **both** queues:

```java
processQueue(OUTBOUND_REMINDER);
processQueue(OUTBOUND_LEAD);
```

---

## 8. Webhook — Call Result

`POST /api/v1/tools/call-result` (X-API-Key auth):

**Appointment-based (unchanged):**
```json
{ "appointmentId": "29", "patientId": "3", "result": "no_answer" }
```

**Lead-based (new):**
```json
{ "leadId": "9", "result": "no_answer" }
```

`CallResultRequest` record fields:
- `appointmentId` — optional (was required in v1/v2)
- `leadId` — optional (new in v3)
- `patientId` — optional
- `result` — required (`confirmed`, `cancelled`, `rescheduled`, `no_answer`, `busy`, `voicemail`)

At least one of `appointmentId` or `leadId` must be present (validated in service).

---

## 9. Lead-Based Follow-ups (Staff UI)

Staff schedules from the Leads page:

```json
POST /api/v1/follow-ups  (JWT auth)
{ "leadId": 9, "scheduledAt": "2026-07-12T04:00:00Z" }
```

`FollowUpService.saveLeadFollowUp()`:
- `minutesBefore = 0` (no appointment to offset from)
- Idempotent: if `(leadId, CALL)` already exists → updates `scheduledAt`, resets `status = PENDING`

When due, scheduler fires with `context = "outbound_lead"`. Asterisk uses `[from-ai-outbound-lead]` context.

---

## 10. Frontend Pages

### `/follow-ups` — Follow-up Reminders

| Tab | Filter |
|---|---|
| All | All rows |
| Appointment | `appointmentId != null` |
| Leads | `leadId != null AND appointmentId == null` |

Customer Type column: "Lead" (purple) when `leadId != null`, "Patient" (blue) otherwise.

### `/outbound-queue` — Live Queue

Shows PENDING + TRIGGERED items for **both** contexts. The `context` column distinguishes patient vs lead calls.

### `/leads` — Schedule Follow-up

- "Schedule" column hidden at `< xl` breakpoint; available via `⋮` dropdown on smaller screens
- Saves via `POST /api/v1/follow-ups { leadId, scheduledAt }`

---

## 11. API Reference

### Staff-facing (JWT + `X-Tenant-ID`)

| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/follow-ups` | Paginated history |
| POST | `/api/v1/follow-ups` | Create / reschedule (appointment or lead) |
| PATCH | `/api/v1/follow-ups/{id}` | Update status / scheduledAt |
| GET | `/api/v1/outbound-queue` | Live queue (PENDING + TRIGGERED, both contexts) |

### AI-facing (X-API-Key + `X-Tenant-ID`)

| Method | URL | Description |
|---|---|---|
| POST | `/api/v1/tools/follow-ups` | AI opts patient in to reminder (appointment-based) |
| POST | `/api/v1/tools/call-result` | Call outcome — accepts `appointmentId` OR `leadId` |
| POST | `/api/v1/tools/call-logs` | Transcript — `context_name` drives queue advancement |

### AI Engine (called by HOS)

| Method | URL | Notes |
|---|---|---|
| POST | `/api/outbound/trigger` | `X-Api-Key` auth; payload differs by context |
| GET | `/outbound/context-status?context=X` | Works for both `outbound_reminder` and `outbound_lead` |

---

## 12. Configuration Reference

```properties
# Follow-up scheduler
app.followup.enabled=true
app.followup.scheduler-fixed-delay-ms=60000
app.followup.timezone=Asia/Dhaka
app.followup.outbound-trigger-url=              # http://<engine>:3003/api/outbound/trigger
app.followup.outbound-trigger-api-key=          # matches OUTBOUND_TRIGGER_API_KEY in engine .env

# Outbound queue
app.outbound-queue.engine-context-status-url=   # http://<engine>:3003/outbound/context-status
app.outbound-queue.engine-health-token=         # matches HEALTH_API_TOKEN in engine .env
app.outbound-queue.stuck-timeout-minutes=10
app.outbound-queue.max-retries=3
```

**AI Engine `.env` additions for outbound_lead:**

```env
AAVA_OUTBOUND_LEAD_DIAL_CONTEXT=from-ai-outbound-lead   # new Asterisk context for lead calls
```

---

## 13. Status Lifecycles

### `follow_up_requests.status`

```
PENDING ──(scheduler fires)──────────────────► SENT
        ──(scheduler fails 3× retries)───────► FAILED
        ──(appointment cancelled)─────────────► CANCELLED
```

### `outbound_call_queue.status` (both contexts)

```
PENDING ──(processQueue picks it)──► TRIGGERED ──(webhook/call-logs)──► DONE
                                          │
                                          ├─(trigger HTTP fails)──────► FAILED
                                          └─(5-min cron, stuck)───────► DONE (no_answer)
```

### `outbound_call_queue.call_result` by source

| Value | Who sets it | Applies to |
|---|---|---|
| `no_answer` | Asterisk SHELL curl | Both contexts |
| `busy` | Asterisk SHELL curl | Both contexts |
| `answered` | HOS (from call-logs handler, by context) | Both contexts |
| `no_answer` *(fallback)* | HOS 5-min recovery cron | Both contexts |

---

## 14. Edge Cases & Recovery

| Scenario | Handling |
|---|---|
| Lead call and patient call both due at same time | Each processed independently — `processQueue("outbound_lead")` and `processQueue("outbound_reminder")` do not share a lock. Both can execute concurrently. |
| Voicemail on a lead call (AMD MACHINE) | `recoverStuckItems` marks TRIGGERED lead item DONE `no_answer` → calls `processQueue("outbound_lead")`. |
| `call-result` arrives with neither `appointmentId` nor `leadId` | `saveCallResult` logs a warning and skips. Queue is not advanced. 5-min cron recovers. |
| Lead call answered — call-logs has no `leadId` | `markDoneWithResultByContextAndProcessNext("outbound_lead", "answered")` finds the one TRIGGERED item by context. Safe because only one can be TRIGGERED at a time per context. |
| `outbound_lead` queue backs up while `outbound_reminder` is busy | No blocking — they are separate queues. Lead calls proceed normally. |
| Staff reschedules lead follow-up while it's PENDING in queue | `saveLeadFollowUp` updates `follow_up_requests` `scheduledAt` and resets to PENDING. The already-enqueued queue row stays PENDING with the old timing — the next scheduler tick will fire it; the extra row completes harmlessly with `no_answer` via cron. |
| Two HOS instances | `SELECT FOR UPDATE SKIP LOCKED` per context prevents double-triggering in both queues. |
| Engine down at trigger time | `isEngineBusy()` errors → assumes free → trigger attempted. If trigger also fails → queue item marked FAILED. Recovery cron clears it. |

---

## 15. Backend Module Map

| Module | Responsibility |
|---|---|
| `hos-appointment` | `FollowUpRequest` entity + `FollowUpService` (both paths) + `FollowUpRequestRepository` (includes `findFirstByLeadIdOrderByIdDesc`) + `FollowUpReminderView` (includes `getLeadId()`) |
| `hos-notification` | `FollowUpScheduler`, `OutboundQueueService` (dual-context: `markDoneWithResultForLeadAndProcessNext`, `markDoneWithResultByContextAndProcessNext`, recovery cron for both), `OutboundQueuePersistence` (context routing in `insert`, lead + context markDone variants), `OutboundCallQueue` entity (`leadId` field, nullable appointment columns) |
| `hos-tools` | `CallResultRequest` (accepts `appointmentId` OR `leadId`), `ToolOrchestrationService.saveCallResult` (routes by leadId/appointmentId), `ToolOrchestrationService.saveCallLog` (handles `outbound_lead` context) |
| `hos-app` | Flyway migrations V17–V26, `application.properties` |

---

## Migrations Applied

| Version | Description |
|---|---|
| V17 | Create `follow_up_requests` table |
| V24 | Add `lead_id` to `follow_up_requests`, make `appointment_id` / `patient_id` nullable, partial unique indexes |
| V25 | Relax `minutes_before` constraint to `>= 0` (was `> 0`) |
| V19 | Create `outbound_call_queue` table |
| V26 | Add `lead_id` to `outbound_call_queue`, make appointment/patient columns nullable |

---

*See also:*
- [`OUTBOUND_REMINDER_CALL_FLOW.md`](OUTBOUND_REMINDER_CALL_FLOW.md) — full Asterisk dialplan for `outbound_reminder` + AMD parameters + `.env` variables
- [`OUTBOUND_QUEUE_DESIGN.md`](OUTBOUND_QUEUE_DESIGN.md) — original queue design doc
- [`APPOINTMENT_REMINDER_FLOW.md`](APPOINTMENT_REMINDER_FLOW.md) — inbound booking + patient reminder opt-in flow
