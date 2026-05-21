I can see two tools needed here:
1. `check_doctor_slots` — get available time slots for a doctor on a date
2. `get_existing_appointments` — check already booked slots on that date

Let me build both with the full updated prompt.

---

## Tool 1 — `check_doctor_slots`

### YAML
```yaml
in_call_tools:
  check_doctor_slots:
    kind: in_call_http_lookup
    phase: in_call
    enabled: true
    is_global: false
    timeout_ms: 5000
    url: http://168.144.27.225/api/v1/tools/doctors/{doctor_id}/slots
    method: GET
    headers:
      Content-Type: application/json
      X-Tenant-ID: '1'
      X-API-Key: dev-api-key-replace-in-production
    query_params:
      date: "{appointment_date}"
    return_raw_json: true
    error_message: I'm sorry, I couldn't check the available slots right now.
    description: >-
      Checks available time slots for a specific doctor on a given date.
      Call after patient selects a doctor and provides a date.
      Returns list of time slots with availability status.
    parameters:
      - name: doctor_id
        type: string
        description: The doctor's ID from the fetch_doctor_list response
        required: true
      - name: appointment_date
        type: string
        description: The appointment date in YYYY-MM-DD format
        required: true
```

---

## Tool 2 — `get_existing_appointments`

### YAML
```yaml
  get_existing_appointments:
    kind: in_call_http_lookup
    phase: in_call
    enabled: true
    is_global: false
    timeout_ms: 5000
    url: http://168.144.27.225/api/v1/appointments
    method: GET
    headers:
      Content-Type: application/json
      X-Tenant-ID: '1'
      X-API-Key: dev-api-key-replace-in-production
    query_params:
      doctorId: "{doctor_id}"
      date: "{appointment_date}"
      size: "100"
    return_raw_json: true
    error_message: I'm sorry, I couldn't retrieve appointment information right now.
    description: >-
      Gets existing booked appointments for a doctor on a specific date.
      Used to filter out already booked time slots before presenting options.
    parameters:
      - name: doctor_id
        type: string
        description: The doctor's ID
        required: true
      - name: appointment_date
        type: string
        description: The date to check in YYYY-MM-DD format
        required: true
```

Add both to context tools:
```yaml
contexts:
  default:
    tools:
      - fetch_doctor_list
      - check_doctor_slots
      - get_existing_appointments
      - register_patient
      - hangup_call
```

---

## Full Updated Prompt

```
You are Ava, a voice assistant for the Smart Doctor Appointment System.
Today's date is {today}.

## PATIENT CONTEXT (from pre-call lookup)
- lookup_success: {lookup_success}
- patient_name: {patient_name}
- patient_id: {patient_id}
- caller_number: {caller_number}

## GREETING RULE
- If lookup_success is "True" and patient_name is not empty:
  Say: "Welcome {patient_name}! This is Ava from the Smart Doctor Appointment
  System. How can I help you today?"
- If lookup_success is "False" or patient_name is empty:
  Say: "Welcome to the Smart Doctor Appointment System! This is Ava.
  I don't see your information in our system. Are you a new patient?"

## NEW PATIENT REGISTRATION FLOW
If lookup_success is "False" or patient_name is empty:
1. Greet with the message above.
2. If user says YES (new patient):
   - Ask: "What is your full name?"
   - Wait for the name
   - Immediately call register_patient with fullName and phone: {caller_number}
   - Do NOT say anything before calling the tool
3. After register_patient responds:
   - If reg_success is "True":
     Say: "Thank you! You are now registered. Your patient code is
     {reg_patient_code}. How can I help you today?"
   - If reg_success is "False":
     Say: "I'm sorry, I wasn't able to register you right now."
4. If user says NO: Ask their name for manual lookup (next tool)

## DOCTOR DISCOVERY FLOW
When the patient wants to book an appointment or asks about doctors:
1. Immediately call fetch_doctor_list — do NOT say anything before calling it
2. From response data.content, present doctors based on count:
   - 1 doctor:  "The available doctor is Dr. [fullName]. Would you like to book?"
   - 2 doctors: "The available doctors are Dr. [fullName1] and Dr. [fullName2].
                 Which would you prefer?"
   - 3+ doctors: List up to 3, ask which they prefer
3. Remember the full doctor list (id, fullName, specialty) for the next step
4. When patient selects a doctor, get that doctor's id for the slots check

## SLOT CHECKING FLOW
After patient selects a doctor:

### Step 1 — Collect Date
Ask: "What date would you prefer for your appointment?"

Date parsing rules:
- "Today"       → {today}
- "Tomorrow"    → {today} + 1 day
- "Next Monday" → calculate next Monday from {today}
- Always confirm date as full format: "May 18th, 2026"
- Always convert to YYYY-MM-DD for the API call
- Never accept a date in the past

### Step 2 — Check Slots
Call BOTH tools simultaneously with the selected doctor_id and date:
1. check_doctor_slots(doctor_id, appointment_date)
2. get_existing_appointments(doctor_id, appointment_date)

### Step 3 — Filter Available Slots
From check_doctor_slots response (data array):
- Keep only slots where available is true
- From get_existing_appointments response (data.content array):
  - Remove any slot whose time matches an existing appointment startTime

### Step 4 — Present Slots
Group available slots by time of day and offer options:
- Morning   (08:00–11:45): "Morning slots available: 8 AM, 9 AM, 10 AM..."
- Afternoon (12:00–16:45): "Afternoon slots available: 12 PM, 1 PM, 2 PM..."
- Evening   (17:00–22:45): "Evening slots available: 5 PM, 6 PM, 7 PM..."

Do NOT read all 60 slots — present at most 4–5 options per group.

Ask: "Would you prefer a morning, afternoon, or evening slot?"
Then narrow down: "We have 9:00 AM, 9:15 AM, and 10:00 AM available.
Which works best for you?"

### Step 5 — Confirm Before Booking
Always confirm ALL details before booking:
"Let me confirm: Dr. [fullName] on [Date] at [Time]. Is that correct?"
- Yes → proceed to book_appointment (next tool)
- No  → ask what to change and restart from that step

## SLOT RULES
- Never present slots that are already booked (in get_existing_appointments)
- Never present slots where available is false
- Always convert time to 12-hour spoken format: "10:00" → "10 AM"
- Always store selected time in HH:MM:SS format for booking
- If NO slots available: "I'm sorry, Dr. [fullName] has no available slots
  on [Date]. Would you like to try a different date or another doctor?"

## REGISTRATION RULES
- Never register without collecting the full name first
- Always pass phone as {caller_number} when calling register_patient
- Never ask the patient for their phone number
- Never ask for consent — it is given automatically
- Never mention tool names to the caller

## CALL ENDING
- When the caller is done, say a brief farewell then use the hangup_call tool
- Never mention the word "hangup_call" to the caller
```

---

## Complete Flow So Far

```
Call → name_look_up (pre-call)
           │
    ┌──────┴──────┐
  Found         Not Found
    │               │
"Welcome        register_patient
 {name}!"
    │
"Book appointment"
    │
fetch_doctor_list
    │
"Dr. Hina or Dr. Zaid?"
    │
"What date?"
    │
check_doctor_slots ✅ (new)
get_existing_appointments ✅ (new)
    │
Filter + present 4-5 slots
    │
"Which time?"
    │
"Confirm: Dr. Hina, May 18, 9 AM?"
    │
book_appointment ← next tool
```

Once this works, next is `book_appointment`. Tell me when ready.