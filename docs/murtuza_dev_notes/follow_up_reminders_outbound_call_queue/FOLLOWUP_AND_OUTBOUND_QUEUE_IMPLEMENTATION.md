# Follow-up Reminders & Outbound Call Queue — Implementation Reference

**Last updated:** 2026-07-11  
**Status:** Fully implemented ✅

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Database Schema](#2-database-schema)
3. [Follow-up Reminder Flow (End-to-End)](#3-follow-up-reminder-flow-end-to-end)
4. [Outbound Call Queue — Serial Execution](#4-outbound-call-queue--serial-execution)
5. [Webhook — Call Result](#5-webhook--call-result)
6. [Lead-Based Follow-ups (Staff UI)](#6-lead-based-follow-ups-staff-ui)
7. [Frontend Pages](#7-frontend-pages)
8. [API Reference](#8-api-reference)
9. [Configuration Reference](#9-configuration-reference)
10. [Status Lifecycles](#10-status-lifecycles)
11. [Edge Cases & Recovery](#11-edge-cases--recovery)

---

## 1. System Overview

```
┌────────────────────────────────────────────────────────────────────┐
│  INBOUND CALL  (Patient calls clinic)                              │
│  Phone → Asterisk ARI → AI Engine (Deepgram/Ava)                  │
│                                                                    │
│  STATE 5 (booking confirmed):                                      │
│  Ava: "Would you like a reminder call 1 hour before?"             │
│  Patient: "Yes"                                                    │
│  AI → POST /api/v1/tools/follow-ups  (X-API-Key auth)             │
└──────────────────────┬─────────────────────────────────────────────┘
                       │  Saves row in follow_up_requests
                       │  status = PENDING, scheduled_at = appt_time − 60 min
                       │
               ┌───────▼──────────────────────┐
               │  HOS Backend (Spring Boot)    │
               │  FollowUpScheduler            │
               │  Polls every 60 seconds       │
               └───────┬──────────────────────┘
                       │  Finds PENDING rows where scheduled_at ≤ NOW
                       │  Inserts into outbound_call_queue
                       │  Marks follow_up_requests row → SENT
                       │
               ┌───────▼──────────────────────────────────────────────┐
               │  OutboundQueueService (serial executor)              │
               │  1. Checks: is any item already TRIGGERED?           │
               │  2. Checks: GET /outbound/context-status (engine)    │
               │  3. Picks oldest PENDING row → marks TRIGGERED        │
               │  4. POST /api/outbound/trigger (AI Engine, X-Api-Key) │
               └───────┬──────────────────────────────────────────────┘
                       │  Engine dials patient via Asterisk ARI
                       │
               ┌───────▼──────────────────────────────────────────────┐
               │  OUTBOUND CALL (AI Engine, context: outbound_reminder)│
               │  Patient: Confirm / Cancel / Reschedule              │
               │  AI calls: /tools/call-result  (before hangup)       │
               └───────┬──────────────────────────────────────────────┘
                       │  POST /api/v1/tools/call-result
                       │  Marks queue item DONE
                       │  Advances queue → triggers next caller
                       │
               ┌───────▼──────────────────────────────────────────────┐
               │  Staff UI  (hospital-os-web)                         │
               │  /follow-ups  — full history with lead/patient view  │
               │  /outbound-queue — live PENDING + TRIGGERED items    │
               └──────────────────────────────────────────────────────┘
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
- Unique index on `(appointment_id, reminder_type)` WHERE appointment_id IS NOT NULL
- Unique index on `(lead_id, reminder_type)` WHERE lead_id IS NOT NULL

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

AI Engine calls `POST /api/v1/tools/follow-ups` with API key auth during STATE 5:

```json
POST /api/v1/tools/follow-ups
X-API-Key: <key>
X-Tenant-ID: 1

{
  "appointmentId": 101,
  "patientId": 42,
  "reminderType": "CALL",
  "minutesBefore": 60
}
```

**What happens in `FollowUpService.save()`:**
1. Looks up the appointment to get its date + time
2. Computes `scheduledAt = appointmentDateTime − minutesBefore`
3. Idempotency check: if `(appointmentId, reminderType)` already exists → returns existing record
4. Saves new `FollowUpRequest` with status `PENDING`

---

### Step 2 — Scheduler polls for due reminders

`FollowUpScheduler.fireReminders()` runs every 60 seconds (configurable):

```java
// hos-notification/scheduler/FollowUpScheduler.java
@Scheduled(fixedDelayString = "${app.followup.scheduler-fixed-delay-ms:60000}")
public void fireReminders() {
    List<FollowUpReminderView> due = followUpService.findPendingDueForTrigger();
    for (FollowUpReminderView f : due) {
        outboundQueueService.enqueue(f);   // → outbound_call_queue
        followUpService.markSent(f.getId()); // follow_up_requests → SENT
    }
}
```

**Query:** Finds all `follow_up_requests` rows where:
- `status = 'PENDING'`
- `scheduled_at <= NOW() + 30 seconds`

The query LEFT JOINs `appointments`, `patients`, `doctors`, and `leads` so the scheduler has the full outbound trigger payload in one shot.

---

### Step 3 — OutboundQueueService triggers the call

`OutboundQueueService.enqueue()` → `processQueue("outbound_reminder")`:

```
1. Is outboundTriggerUrl configured?
   └─ No  → skip (dev mode, no call fired)
   └─ Yes → continue

2. Does outbound_call_queue have a TRIGGERED item for this context?
   └─ Yes → return (webhook will advance the queue when call ends)
   └─ No  → continue

3. Is AI engine busy? (GET /outbound/context-status?context=outbound_reminder)
   └─ Busy   → return (webhook will advance)
   └─ Free   → continue

4. SELECT FOR UPDATE SKIP LOCKED — pick oldest PENDING item → mark TRIGGERED
5. POST /api/outbound/trigger (AI engine, X-Api-Key)
   Body: { phone_number, patient_id, patient_name, appointment_id,
           doctor_name, appointment_date, start_time, context }
```

The `SELECT FOR UPDATE SKIP LOCKED` prevents two HOS instances from picking the same row simultaneously.

---

## 4. Outbound Call Queue — Serial Execution

Only **one** outbound reminder call runs at a time. This is enforced by two guards:

| Guard | How |
|---|---|
| **DB guard** | Checks `outbound_call_queue` for an existing `TRIGGERED` row before picking the next PENDING |
| **Engine guard** | `GET /outbound/context-status?context=outbound_reminder` — asks the AI engine if a call is already active |

The DB guard is primary and cheaper. The engine guard catches calls triggered outside HOS (e.g. manually).

### Queue state machine

```
PENDING ──(processQueue picks it)──► TRIGGERED ──(webhook fires)──► DONE
                                          │
                                          └─(trigger HTTP fails)──► FAILED
                                          └─(5-min voicemail cron)─► DONE (call_result=no_answer)
```

### Recovery cron

`OutboundQueueService.recoverStuckItems()` runs every 5 minutes:
- Finds TRIGGERED items older than `stuck-timeout-minutes` (default: 5 min)
- Marks them DONE with `call_result = 'no_answer'`
- Calls `processQueue()` to advance to next caller

This handles AMD-detected voicemail and engine crashes where no webhook fires.

---

## 5. Webhook — Call Result

When the outbound call ends, the AI Engine calls:

```json
POST /api/v1/tools/call-result
X-API-Key: <key>
X-Tenant-ID: 1

{
  "appointment_id": "29",
  "patient_id": "3",
  "result": "confirmed"
}
```

Possible `result` values: `confirmed`, `cancelled`, `rescheduled`, `no_answer`, `busy`, `voicemail`

**What happens in `ToolOrchestrationService.saveCallResult()`:**
1. Updates `follow_up_requests.call_result` for the appointment
2. Updates `appointments.last_call_result` + `last_call_at`
3. Calls `outboundQueueService.markDoneWithResultAndProcessNext(appointmentId, callResult)`:
   - Finds the TRIGGERED queue item for this appointment → sets status `DONE`, records `call_result`, sets `completed_at`
   - Calls `processQueue("outbound_reminder")` → picks next PENDING item and fires it

This is the primary queue advancement mechanism.

---

## 6. Lead-Based Follow-ups (Staff UI)

Added in V24/V25. Leads don't have appointments, so the flow is different.

### Staff schedules a follow-up from Leads page

```json
POST /api/v1/follow-ups
Authorization: Bearer <JWT>
X-Tenant-ID: 1

{
  "leadId": 9,
  "scheduledAt": "2026-07-12T04:00:00.000Z"
}
```

**What happens in `FollowUpService.saveLeadFollowUp()`:**
- `scheduledAt` is taken directly (not computed from appointment)
- `minutesBefore` = 0 (no appointment to offset from)
- Idempotency: if `(leadId, reminderType)` already exists → updates `scheduledAt`, resets status to `PENDING`

> **Note:** The scheduler's `findPendingDueForTrigger()` query LEFT JOINs `leads` table, so lead-based follow-ups will also fire outbound calls when their `scheduled_at` is due. The trigger payload uses `leads.phone` and `leads.name` instead of `patients.phone` and `patients.full_name`.

---

## 7. Frontend Pages

### `/follow-ups` — Follow-up Reminders

- **Source:** `GET /api/v1/follow-ups?page=0&size=20&sort=scheduledAt,desc`
- **Auth:** JWT (staff-facing)
- **Tabs:** All / Appointment / Leads
  - "Appointment" tab: rows where `appointmentId != null`
  - "Leads" tab: rows where `leadId != null AND appointmentId == null`
- **Customer Type column:** shows "Lead" (purple) or "Patient" (blue) based on `leadId != null`

Key file: [`frontend/hospital-os-web/src/pages/follow-ups/FollowUpsPage.tsx`](../frontend/hospital-os-web/src/pages/follow-ups/FollowUpsPage.tsx)

---

### `/outbound-queue` — Live Outbound Queue

- **Source:** `GET /api/v1/outbound-queue` (returns only PENDING + TRIGGERED items)
- **Auth:** JWT (staff-facing)
- Shows the live call queue — who is waiting, who is currently being called

Key file: [`frontend/hospital-os-web/src/pages/outbound-queue/`](../frontend/hospital-os-web/src/pages/outbound-queue/)

---

### `/leads` — Schedule Follow-up Button

The "Schedule" button on the Leads table opens a date picker modal.  
On confirm it calls `POST /api/v1/follow-ups` with `{ leadId, scheduledAt }`.

- On smaller screens (`< xl` breakpoint) the Schedule column is hidden — use the `⋮` dropdown → "Schedule Follow-up" instead.
- React Query key: `['lead-follow-ups']` — invalidated after a successful save.

---

## 8. API Reference

### Staff-facing (JWT + `X-Tenant-ID`)

| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/follow-ups` | Paginated follow-up history (`status`, `page`, `size`, `sort`) |
| GET | `/api/v1/follow-ups/{id}` | Get single follow-up record |
| POST | `/api/v1/follow-ups` | Create/reschedule follow-up (appointment-based or lead-based) |
| PATCH | `/api/v1/follow-ups/{id}` | Update `status`, `scheduledAt`, `retryCount`, `minutesBefore` |
| GET | `/api/v1/outbound-queue` | Live queue (PENDING + TRIGGERED only) |

### AI-facing (X-API-Key + `X-Tenant-ID`)

| Method | URL | Description |
|---|---|---|
| POST | `/api/v1/tools/follow-ups` | AI opts patient in to reminder (appointment-based only) |
| POST | `/api/v1/tools/call-result` | Webhook: call outcome → advances queue |
| POST | `/api/v1/tools/call-logs` | Save call session + transcript |

### AI Engine (called by HOS)

| Method | URL | Description |
|---|---|---|
| POST | `/api/outbound/trigger` | Fire an outbound call (`X-Api-Key` header) |
| GET | `/outbound/context-status?context=outbound_reminder` | Check if engine is busy (`Authorization: Bearer <HEALTH_API_TOKEN>`) |

---

## 9. Configuration Reference

All in `application.properties` (base) — override in environment or `application-prod.properties`:

```properties
# Follow-up scheduler
app.followup.enabled=true
app.followup.scheduler-fixed-delay-ms=60000     # poll every 60 s
app.followup.timezone=Asia/Dhaka                # ZoneId for scheduled_at comparisons
app.followup.outbound-trigger-url=              # http://<engine>:3003/api/outbound/trigger
app.followup.outbound-trigger-api-key=          # matches OUTBOUND_TRIGGER_API_KEY in engine .env

# Outbound queue
app.outbound-queue.engine-context-status-url=   # http://<engine>:3003/outbound/context-status
app.outbound-queue.engine-health-token=         # matches HEALTH_API_TOKEN in engine .env
app.outbound-queue.stuck-timeout-minutes=10     # voicemail/crash recovery window (minutes)
app.outbound-queue.max-retries=3
```

> **Dev:** Leave `outbound-trigger-url` blank. The scheduler will find due rows but skip the HTTP call — follow-ups are marked `SENT` immediately so the queue advances without calling anyone.

---

## 10. Status Lifecycles

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

---

## 11. Edge Cases & Recovery

| Scenario | Handling |
|---|---|
| Engine down when scheduler fires | `isEngineBusy()` catches the error and returns `false` (assumes free) — call is triggered. If trigger also fails, queue item marked `FAILED`. |
| Engine busy when scheduler fires | `processQueue` returns early — item stays `PENDING`. Webhook from the current call advances the queue. |
| Voicemail / patient doesn't answer | AMD ends the call, no webhook fires. Recovery cron (every 5 min) marks stuck TRIGGERED items as `DONE (no_answer)` and calls `processQueue`. |
| Engine restarts mid-call | Call ends eventually → webhook fires → queue advances normally. |
| Two HOS instances running | `SELECT FOR UPDATE SKIP LOCKED` in `pickAndMarkTriggered` prevents double-trigger. |
| Lead-based row has no patient/appointment | Scheduler query uses LEFT JOINs; phone + name come from `leads` table. |
| Staff reschedules a lead follow-up | `saveLeadFollowUp` finds existing `(leadId, CALL)` row, updates `scheduledAt`, resets status to `PENDING`. |
| Follow-up already exists for appointment | `saveFollowUp` returns the existing record (idempotent — safe for AI to retry). |

---

## Backend Module Map

| Module | Responsibility |
|---|---|
| `hos-appointment` | `FollowUpRequest` entity, `FollowUpService`, `FollowUpRequestRepository`, `SaveFollowUpRequest` DTO |
| `hos-notification` | `FollowUpScheduler`, `OutboundQueueService`, `OutboundQueuePersistence`, `OutboundCallQueue` entity, `OutboundQueueController` |
| `hos-tools` | `ToolController` endpoints: `POST /tools/follow-ups`, `POST /tools/call-result`, `POST /tools/call-logs` |
| `hos-app` | Flyway migrations V17–V25, `application.properties` config keys |
