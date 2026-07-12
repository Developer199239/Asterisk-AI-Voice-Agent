# Appointment Booking & Reminder Flow

> Complete end-to-end flow for the AI Hospital Operating System —  
> inbound voice booking + outbound reminder call.

---

## 1. System Overview

```mermaid
flowchart LR
    subgraph Patient
        P["📞 Patient Phone"]
    end

    subgraph PBX["Asterisk PBX (ARI)"]
        A["ARI Channel"]
    end

    subgraph AI["AI Engine (Node.js :3003)"]
        IB["Inbound Handler"]
        OB["Outbound Handler"]
    end

    subgraph HOS["HOS Backend (Spring Boot :8080)"]
        TOOLS["Tool Endpoints\n/api/v1/tools/*\n(API Key auth)"]
        SCHED["FollowUpScheduler\n(every 60 sec)"]
        DB[("PostgreSQL")]
    end

    P -- "Calls in" --> A
    A -- "Inbound call event" --> IB
    IB -- "Tool calls (X-Api-Key)" --> TOOLS
    TOOLS --> DB

    SCHED -- "Reads PENDING follow-ups" --> DB
    SCHED -- "POST /api/outbound/trigger" --> OB
    OB -- "Dials patient" --> A
    A -- "Outbound call" --> P
    OB -- "Tool calls (X-Api-Key)" --> TOOLS
```

---

## 2. Inbound Booking Flow

```mermaid
flowchart TD
    START([📞 Patient calls in]) --> ARI[Asterisk ARI receives call]
    ARI --> AI_GREET[AI Engine answers\nplays greeting]

    AI_GREET --> LOOKUP["Tool 1 — Patient Lookup\nPOST /tools/patients/lookup\nbody: phone number"]

    LOOKUP --> FOUND{Patient\nfound?}

    FOUND -- Yes --> INTENT
    FOUND -- No --> REGISTER["Tool 2 — Register Patient\nPOST /tools/patients/register\nname · phone · DOB · gender"]
    REGISTER --> INTENT

    INTENT{What does\npatient want?}

    %% ── BOOK PATH ──────────────────────────────────────
    INTENT -- "Book appointment" --> LIST_DOC["Tool 11 — List Doctors\nGET /tools/doctors"]
    LIST_DOC --> PICK_DOC[AI reads doctor names\nPatient picks doctor]

    PICK_DOC --> PICK_DATE[AI asks preferred date]
    PICK_DATE --> SLOTS["Tool 3 — Available Slots\nGET /tools/doctors/{id}/slots?date="]
    SLOTS --> SLOT_AVAIL{Slots\navailable?}

    SLOT_AVAIL -- No --> ALT_DATE[AI suggests alternate date] --> PICK_DATE
    SLOT_AVAIL -- Yes --> SERIAL["Tool 14 — Next Serial\nGET /tools/appointments/next-serial\n?doctorId=&date="]

    SERIAL --> BOOK["Tool 4 — Book Appointment\nPOST /tools/appointments\nsource: AI_VOICE"]
    BOOK --> CONFIRM_MSG[AI reads back:\nserial · date · time · doctor]

    CONFIRM_MSG --> CONSENT["Tool 9 — Update Consent\nPOST /tools/consent/update\nAI · data-processing · communication"]

    CONSENT --> ASK_REMINDER{Patient wants\nreminder call?}
    ASK_REMINDER -- Yes --> SAVE_FU["Tool 15 — Save Follow-up\nPOST /tools/follow-ups\nminutesBefore: 60 · type: CALL"]
    ASK_REMINDER -- No --> CALLLOG
    SAVE_FU --> CALLLOG

    %% ── CANCEL PATH ─────────────────────────────────────
    INTENT -- "Cancel appointment" --> ASK_CODE[AI asks confirmation code]
    ASK_CODE --> LOOKUP_APT["Tool 6 — Lookup Appointment\nGET /tools/appointments/lookup\n?confirmationCode=A-XXXXXX"]
    LOOKUP_APT --> CANCEL["Tool 5 — Cancel Appointment\nPOST /tools/appointments/cancel\nreason from patient"]
    CANCEL --> CANCEL_MSG[AI confirms cancellation] --> CALLLOG

    %% ── RESCHEDULE PATH ──────────────────────────────────
    INTENT -- "Reschedule" --> ASK_CODE2[AI asks confirmation code]
    ASK_CODE2 --> LOOKUP_APT2["Tool 6 — Lookup Appointment\nGET /tools/appointments/lookup"]
    LOOKUP_APT2 --> NEW_DATE[AI asks new preferred date]
    NEW_DATE --> SLOTS2["Tool 3 — Available Slots\nGET /tools/doctors/{id}/slots?date="]
    SLOTS2 --> RESCHEDULE["Tool 7 — Reschedule\nPOST /tools/appointments/reschedule"]
    RESCHEDULE --> RESCHED_MSG[AI confirms new time] --> CALLLOG

    %% ── QUEUE PATH ───────────────────────────────────────
    INTENT -- "Queue status" --> QUEUE["Tool 8 — Queue Status\nGET /tools/queue/status?patientId="]
    QUEUE --> QUEUE_MSG[AI reads position\nand estimated wait] --> CALLLOG

    %% ── END ──────────────────────────────────────────────
    CALLLOG["Tool 13 — Save Call Log\nPOST /tools/call-logs\nsessionId · transcript · duration"]
    CALLLOG --> END_CALL([Call ends])

    %% Styles
    style START fill:#4CAF50,color:#fff
    style END_CALL fill:#9E9E9E,color:#fff
    style BOOK fill:#2196F3,color:#fff
    style SAVE_FU fill:#FF9800,color:#fff
    style CANCEL fill:#F44336,color:#fff
    style RESCHEDULE fill:#9C27B0,color:#fff
```

---

## 3. Outbound Reminder Flow

```mermaid
flowchart TD
    TICK([⏱ Scheduler tick\nevery 60 seconds]) --> QUERY

    QUERY["FollowUpService.findPendingDueForTrigger()\nSELECT fur.* · p.phone · p.full_name\n       d.full_name · a.appointment_date · a.start_time\nFROM follow_up_requests fur\nJOIN appointments · patients · doctors\nWHERE status='PENDING' AND scheduled_at ≤ NOW()"]

    QUERY --> EMPTY{Any rows\ndue?}
    EMPTY -- No --> SLEEP([Wait for next tick])
    EMPTY -- Yes --> LOOP

    LOOP["For each due follow-up"] --> URL_CHECK{outbound-trigger-url\nconfigured?}

    URL_CHECK -- No --> DEV_WARN["WARN: not configured\n(dev mode — skip call)"]
    DEV_WARN --> MARK_SENT_DEV[markSent — status = SENT]
    MARK_SENT_DEV --> NEXT

    URL_CHECK -- Yes --> BUILD_BODY["Build trigger payload:\n{\n  phone_number,  patient_id,\n  patient_name,  appointment_id,\n  doctor_name,   appointment_date,\n  start_time,    context\n}"]

    BUILD_BODY --> LOG_REQ["INFO: Follow-up #X → POST url\nINFO: Headers + masked API key\nINFO: Body (full JSON)"]

    LOG_REQ --> HTTP["POST /api/outbound/trigger\nX-Api-Key: ****\nContent-Type: application/json"]

    HTTP --> HTTP_RESP{HTTP\nresponse?}

    HTTP_RESP -- "200 / 201" --> LOG_OK["INFO: HTTP 200 | Body: {ok:true}"]
    LOG_OK --> MARK_SENT[markSent\nstatus = SENT\ntriggeredAt = NOW Dhaka]
    MARK_SENT --> NEXT

    HTTP_RESP -- "401" --> FAIL_KEY["ERROR: API key wrong (401)"]
    HTTP_RESP -- "503" --> FAIL_OFF["ERROR: AI engine disabled (503)"]
    HTTP_RESP -- "422 / other" --> FAIL_OTHER["ERROR: HTTP 4xx/5xx + body"]

    FAIL_KEY --> MARK_FAILED
    FAIL_OFF --> MARK_FAILED
    FAIL_OTHER --> MARK_FAILED

    MARK_FAILED["markFailed\nretry_count++\nlast_error = message"]
    MARK_FAILED --> RETRY_CHECK{retry_count\n≥ 3?}
    RETRY_CHECK -- Yes --> PERMANENT["status = FAILED\n(permanent — no more retries)"]
    RETRY_CHECK -- No --> PENDING_AGAIN["status stays PENDING\n(retried next tick)"]

    PERMANENT --> NEXT
    PENDING_AGAIN --> NEXT

    NEXT{More rows?}
    NEXT -- Yes --> LOOP
    NEXT -- No --> SLEEP

    %% ── Outbound call side ───────────────────────────────
    subgraph AI_OUTBOUND["AI Engine — Outbound Call (parallel)"]
        direction TD
        DIAL[AI Engine dials phone_number\nvia Asterisk ARI]
        DIAL --> ANSWER{Patient\nanswers?}
        ANSWER -- No / Voicemail --> NO_ANS[Hang up\n→ Backend marks FAILED\non next tick if no 200]
        ANSWER -- Yes --> REMIND[AI plays reminder:\nappointment_date · start_time · doctor_name]
        REMIND --> PATIENT_RESP{Patient\nresponse?}
        PATIENT_RESP -- "Confirm" --> CONFIRM_TOOL["Tool 16 — Confirm Appointment\nPUT /tools/appointments/{id}/confirm\nSCHEDULED → CONFIRMED"]
        PATIENT_RESP -- "Cancel" --> CANCEL_TOOL["Tool 5 — Cancel Appointment\nPOST /tools/appointments/cancel"]
        PATIENT_RESP -- "Reschedule" --> RESCHEDULE_TOOL["Tool 7 — Reschedule\nPOST /tools/appointments/reschedule"]
        CONFIRM_TOOL --> END_OB([Call ends])
        CANCEL_TOOL --> END_OB
        RESCHEDULE_TOOL --> END_OB
    end

    HTTP --> DIAL

    %% Styles
    style TICK fill:#4CAF50,color:#fff
    style SLEEP fill:#9E9E9E,color:#fff
    style MARK_SENT fill:#4CAF50,color:#fff
    style MARK_SENT_DEV fill:#FF9800,color:#fff
    style PERMANENT fill:#F44336,color:#fff
    style CONFIRM_TOOL fill:#2196F3,color:#fff
    style CANCEL_TOOL fill:#F44336,color:#fff
```

---

## 4. Appointment Status State Machine

```mermaid
stateDiagram-v2
    [*] --> SCHEDULED : Tool 4 — Book\n(AI_VOICE / MANUAL)

    SCHEDULED --> CONFIRMED : Tool 16 — Confirm\n(AI outbound call)
    SCHEDULED --> CANCELLED : Tool 5 — Cancel
    SCHEDULED --> SCHEDULED : Tool 7 — Reschedule\n(new date/time, stays SCHEDULED)

    CONFIRMED --> CHECKED_IN : PUT /appointments/{id}/check-in\n(reception desk)
    CONFIRMED --> CANCELLED : Tool 5 — Cancel

    CHECKED_IN --> COMPLETED : PUT /appointments/{id}/complete\n(doctor marks done)
    CHECKED_IN --> NO_SHOW : PUT /appointments/{id}/no-show\n(reception desk)

    CANCELLED --> [*]
    COMPLETED --> [*]
    NO_SHOW --> [*]
```

---

## 5. Follow-up Request Status

```mermaid
stateDiagram-v2
    [*] --> PENDING : Tool 15 — Save Follow-up\n(patient opts in during booking)

    PENDING --> SENT : Scheduler fires successfully\nor URL not configured (dev)
    PENDING --> FAILED : Scheduler fails 3× retries
    PENDING --> CANCELLED : Appointment cancelled\n(cancelByAppointmentId)

    PENDING --> PENDING : Admin PATCH reset\n(retryCount=0, status=PENDING)
    FAILED --> PENDING : Admin PATCH reset\n(retryCount=0, status=PENDING)

    SENT --> [*]
    FAILED --> [*]
    CANCELLED --> [*]
```

---

## 6. Tool Reference

| # | Method | Path | Purpose |
|---|--------|------|---------|
| 1 | POST | `/tools/patients/lookup` | Find patient by phone or patient code |
| 2 | POST | `/tools/patients/register` | Register new patient |
| 3 | GET | `/tools/doctors/{id}/slots` | Available time slots for a doctor on a date |
| 4 | POST | `/tools/appointments` | Book an appointment (source forced to `AI_VOICE`) |
| 5 | POST | `/tools/appointments/cancel` | Cancel an appointment |
| 6 | GET | `/tools/appointments/lookup` | Find appointment by confirmation code |
| 7 | POST | `/tools/appointments/reschedule` | Move appointment to new date/time |
| 8 | GET | `/tools/queue/status` | Patient queue position today |
| 9 | POST | `/tools/consent/update` | Record patient consent flags |
| 10 | PATCH | `/tools/patients/{id}` | Update patient profile |
| 11 | GET | `/tools/doctors` | List active doctors |
| 12 | GET | `/tools/appointments` | List appointments by doctor + date |
| 13 | POST | `/tools/call-logs` | Save completed call session + transcript |
| 14 | GET | `/tools/appointments/next-serial` | Next serial number for doctor on date |
| 15 | POST | `/tools/follow-ups` | Save patient's reminder call preference |
| 16 | PUT | `/tools/appointments/{id}/confirm` | Confirm appointment (SCHEDULED → CONFIRMED) |

> **Auth:** All tool endpoints require `X-Api-Key` header + `X-Tenant-ID` header.  
> **JWT endpoints** (`/api/v1/appointments`, `/api/v1/follow-ups`, etc.) require `Authorization: Bearer <token>`.

---

## 7. Configuration Quick Reference

```properties
# ── Follow-up Scheduler ──────────────────────────────────────────────────
app.followup.outbound-trigger-url=http://192.168.0.170:3003/api/outbound/trigger
app.followup.outbound-trigger-api-key=your-strong-random-key-here
app.followup.scheduler-fixed-delay-ms=60000   # poll every 60 s
app.followup.timezone=Asia/Dhaka              # all LocalDateTime comparisons
app.followup.enabled=true                     # set false to disable scheduler bean

# ── Notification Scheduler (SMS reminders) ──────────────────────────────
app.notification.retry-delay-ms=86400000      # 24 h between retries (prod)
app.notification.reminder-cron=-              # disable cron scheduler (prod workaround)

# ── Frontend polling ─────────────────────────────────────────────────────
VITE_NOTIFICATION_POLL_MS=60000               # 0 = disable notification bell polling
```

---

## 8. Data Flow Diagram

```mermaid
erDiagram
    PATIENTS ||--o{ APPOINTMENTS : "has"
    DOCTORS  ||--o{ APPOINTMENTS : "assigned to"
    APPOINTMENTS ||--o{ FOLLOW_UP_REQUESTS : "triggers"
    APPOINTMENTS ||--o{ APPOINTMENT_HISTORY : "tracks"
    APPOINTMENTS ||--o{ CALL_LOGS : "recorded in"

    PATIENTS {
        bigint id PK
        string patient_code
        string full_name
        string phone
        string email
        bool consent_ai_interaction
        bool consent_communication
    }

    APPOINTMENTS {
        bigint id PK
        bigint patient_id FK
        bigint doctor_id FK
        date appointment_date
        time start_time
        string status "SCHEDULED|CONFIRMED|CHECKED_IN|COMPLETED|CANCELLED|NO_SHOW"
        string source "MANUAL|AI_VOICE|ONLINE"
        string confirmation_code
        int serial_number
    }

    FOLLOW_UP_REQUESTS {
        bigint id PK
        bigint appointment_id FK
        bigint patient_id FK
        string reminder_type "CALL|SMS"
        int minutes_before
        string status "PENDING|SENT|FAILED|CANCELLED"
        timestamp scheduled_at
        timestamp triggered_at
        int retry_count
        string last_error
    }

    DOCTORS {
        bigint id PK
        string full_name
        string specialty
        string phone
        int consultation_duration
        int max_patients_per_day
    }
```
