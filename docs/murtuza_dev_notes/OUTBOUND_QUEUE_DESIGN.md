# Outbound Call Queue — Serial Execution Design

**Date:** 2026-06-14  
**Author:** Murtuza Rahman  
**Version:** 1.0  
**Status:** Engine endpoint implemented ✅ | HOS backend: pending implementation

---

## Overview

By default the engine runs all outbound calls in parallel. For `outbound_reminder`
we need **serial execution** — only one reminder call at a time.

The queue logic lives entirely in the **HOS backend**. The engine exposes one new
read-only status endpoint. This keeps the engine simple and the queue safe in the
HOS database even if the engine restarts.

---

## Flow Diagram

```
HOS Backend: schedule reminders for Patient A, B, C
                        │
                        ▼
           ┌────────────────────────┐
           │ GET /outbound/context- │
           │ status?context=        │
           │ outbound_reminder      │
           └────────────────────────┘
                        │
              ┌─────────┴──────────┐
           FREE (busy=false)    BUSY (busy=true)
              │                    │
              ▼                    ▼
       POST /api/outbound/    Add to HOS queue
       trigger (Patient A)    (status = PENDING)
              │
              │  Call A runs...
              │
              ▼ (call ends)
       POST smart_doctor_call_log
       webhook → HOS backend
              │
              ▼
       Mark A as DONE
       Pick next from queue (Patient B)
              │
              ▼
       POST /api/outbound/trigger (Patient B)
              │  ... same cycle ...
```

---

## Part 1 — Engine (AI Voice Agent)

### New Endpoint

```
GET http://<engine-host>:15000/outbound/context-status?context=outbound_reminder
```

**Authentication:** Bearer token via `Authorization: Bearer <HEALTH_API_TOKEN>`  
(Set `HEALTH_API_TOKEN` in the engine's `.env` file)

**Response — context is free:**
```json
{
  "context": "outbound_reminder",
  "busy": false,
  "active_calls": 0,
  "calls": []
}
```

**Response — context is busy:**
```json
{
  "context": "outbound_reminder",
  "busy": true,
  "active_calls": 1,
  "calls": [
    {
      "call_id": "1781197314.6",
      "status": "active",
      "context": "outbound_reminder"
    }
  ]
}
```

**Error — missing context param:**
```json
{
  "error": "missing_context",
  "message": "Provide ?context=<context_name>"
}
```
HTTP 400

**Error — unauthorized:**
```json
{
  "error": "Forbidden"
}
```
HTTP 403

### Existing Endpoints Used

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/outbound/trigger` | POST | Trigger an outbound call |
| `/outbound/context-status` | GET | **New** — check if context is busy |

### Authentication Setup

Add to engine `.env`:
```env
HEALTH_API_TOKEN=your-secret-token-here
HEALTH_BIND_HOST=0.0.0.0
```

HOS backend sends:
```
Authorization: Bearer your-secret-token-here
```

---

## Part 2 — HOS Backend

### Database Table

```sql
CREATE TABLE outbound_call_queue (
    id              SERIAL PRIMARY KEY,
    phone_number    VARCHAR(20)  NOT NULL,
    patient_id      VARCHAR(50)  NOT NULL,
    patient_name    VARCHAR(100) NOT NULL,
    appointment_id  VARCHAR(50)  NOT NULL,
    doctor_name     VARCHAR(100) NOT NULL,
    appointment_date DATE        NOT NULL,
    start_time      TIME        NOT NULL,
    context         VARCHAR(50)  NOT NULL DEFAULT 'outbound_reminder',
    status          VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    -- PENDING | TRIGGERED | DONE | FAILED
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    triggered_at    TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    retry_count     INT          NOT NULL DEFAULT 0
);

CREATE INDEX idx_queue_status_context ON outbound_call_queue(status, context);
```

### API Contracts HOS Must Implement

#### 1. Add to Queue

```
POST /internal/outbound-queue
Body:
{
  "phone_number": "6000",
  "patient_id": "42",
  "patient_name": "Ahmed Khan",
  "appointment_id": "101",
  "doctor_name": "Dr. Hina Farooqi",
  "appointment_date": "2026-05-20",
  "start_time": "09:00",
  "context": "outbound_reminder"
}
Response: { "queued": true, "queue_id": 7 }
```

#### 2. Trigger Next (internal — called by queue worker)

This is internal HOS logic. Not an external API.

### Queue Worker Logic

```python
async def process_outbound_queue(context: str = "outbound_reminder"):
    """
    Called:
    - When a new item is added to queue (if engine might be free)
    - When post-call webhook fires indicating a call ended
    """

    # Step 1: Check if engine context is free
    status = await check_engine_context_status(context)
    if status["busy"]:
        return  # Engine busy — webhook will trigger us again when call ends

    # Step 2: Pick next PENDING item from queue
    next_item = await db.fetch_one(
        "SELECT * FROM outbound_call_queue "
        "WHERE status = 'PENDING' AND context = :context "
        "ORDER BY created_at ASC LIMIT 1",
        {"context": context}
    )
    if not next_item:
        return  # Queue empty

    # Step 3: Mark as TRIGGERED (prevent double-trigger)
    await db.execute(
        "UPDATE outbound_call_queue SET status = 'TRIGGERED', triggered_at = NOW() "
        "WHERE id = :id AND status = 'PENDING'",
        {"id": next_item["id"]}
    )

    # Step 4: Trigger the call
    try:
        await trigger_outbound_call(next_item)
    except Exception as e:
        await db.execute(
            "UPDATE outbound_call_queue SET status = 'FAILED', error_message = :err "
            "WHERE id = :id",
            {"id": next_item["id"], "err": str(e)}
        )
```

### Engine Status Check (HOS helper)

```python
async def check_engine_context_status(context: str) -> dict:
    """Check if the given engine context has an active call."""
    response = await http_client.get(
        f"http://<engine-host>:15000/outbound/context-status",
        params={"context": context},
        headers={"Authorization": f"Bearer {ENGINE_API_TOKEN}"},
        timeout=5.0
    )
    return response.json()
    # Returns: { "busy": bool, "active_calls": int }
```

### Post-Call Webhook Handler

The engine fires `smart_doctor_call_log` when a call ends. Add queue processing there:

```python
@router.post("/api/tools/call-logs")
async def receive_call_log(payload: CallLogPayload):
    # ... existing call log saving logic ...

    # If this was an outbound_reminder call, mark it done and process queue
    if payload.context_name == "outbound_reminder":
        call_id = payload.session_id

        # Mark the triggered item as DONE
        await db.execute(
            "UPDATE outbound_call_queue "
            "SET status = 'DONE', completed_at = NOW() "
            "WHERE status = 'TRIGGERED'",  # only one TRIGGERED at a time
        )

        # Trigger next in queue
        await process_outbound_queue("outbound_reminder")

    return {"status": "ok"}
```

### How to Add a Reminder (entry point)

```python
async def schedule_outbound_reminder(appointment: Appointment):
    """
    Called by HOS when an appointment reminder needs to be sent.
    """
    # Always add to queue first
    queue_id = await db.execute(
        "INSERT INTO outbound_call_queue "
        "(phone_number, patient_id, patient_name, appointment_id, "
        " doctor_name, appointment_date, start_time, context) "
        "VALUES (:phone, :pid, :name, :appt_id, :doc, :date, :time, 'outbound_reminder') "
        "RETURNING id",
        {...}
    )

    # Then try to process immediately (in case engine is free)
    await process_outbound_queue("outbound_reminder")
```

---

## Part 3 — Sequence: Happy Path (3 reminders)

```
Time │ HOS Backend                    │ Engine
─────┼────────────────────────────────┼──────────────────────────────
T+0  │ Add A, B, C to queue           │
T+1  │ Check context status           │
T+1  │ ← busy=false                   │
T+2  │ Trigger call A (mark TRIGGERED)│
T+2  │                                │ Dials 6000 (Ahmed)
T+2  │                                │ Call A running...
T+3  │ (B, C sit PENDING in queue)    │
...  │                                │
T+60 │                                │ Call A ends
T+60 │                                │ POST /api/tools/call-logs
T+60 │ Mark A → DONE                  │
T+60 │ Check context status           │
T+60 │ ← busy=false                   │
T+61 │ Trigger call B (mark TRIGGERED)│
T+61 │                                │ Dials 6001 (Fatima)
...  │                                │
T+90 │                                │ Call B ends → webhook
T+90 │ Mark B → DONE → trigger C      │
T+91 │                                │ Dials 6002 (Jalil)
```

---

## Part 4 — Edge Cases

| Scenario | Handling |
|---|---|
| Engine is down when webhook fires | Queue stays TRIGGERED. Add a periodic HOS cron job that re-checks TRIGGERED items older than 10 min and resets to PENDING |
| Patient doesn't answer | Call ends normally → webhook fires → mark DONE → process next |
| Engine returns 5xx on trigger | Mark queue item as FAILED, log error, process next after delay |
| Two HOS instances run simultaneously | `AND status = 'PENDING'` with atomic UPDATE prevents double-trigger (use `SELECT FOR UPDATE SKIP LOCKED` in Postgres) |
| Engine restarts mid-call | Call ends → webhook fires eventually → queue advances normally |

### Stuck TRIGGERED Recovery (HOS cron — run every 10 min)

```sql
UPDATE outbound_call_queue
SET status = 'PENDING', retry_count = retry_count + 1
WHERE status = 'TRIGGERED'
  AND triggered_at < NOW() - INTERVAL '10 minutes'
  AND retry_count < 3;

UPDATE outbound_call_queue
SET status = 'FAILED', error_message = 'max retries exceeded'
WHERE status = 'TRIGGERED'
  AND triggered_at < NOW() - INTERVAL '10 minutes'
  AND retry_count >= 3;
```

---

## Part 5 — Configuration

### Engine `.env`

```env
HEALTH_BIND_HOST=0.0.0.0        # allow HOS backend to reach :15000
HEALTH_API_TOKEN=<strong-secret> # HOS backend uses this as Bearer token
```

### HOS Backend env

```env
ENGINE_BASE_URL=http://192.168.0.108:15000
ENGINE_API_TOKEN=<same-secret>
ENGINE_OUTBOUND_URL=http://192.168.0.108:<outbound-port>/api/outbound/trigger
```

---

## Summary

| Component | Work Required | Status |
|---|---|---|
| Engine — `/outbound/context-status` endpoint | Add 1 handler + 1 route | ✅ Implemented |
| Engine — `HEALTH_API_TOKEN` auth | Already exists | ✅ Already done |
| HOS — `outbound_call_queue` table | Create migration | ⬜ Pending |
| HOS — `process_outbound_queue` worker | ~50 lines | ⬜ Pending |
| HOS — `schedule_outbound_reminder` entry point | ~20 lines | ⬜ Pending |
| HOS — post-call webhook handler update | Add 5 lines to existing handler | ⬜ Pending |
| HOS — stuck TRIGGERED recovery cron | 1 SQL query on cron | ⬜ Pending |
