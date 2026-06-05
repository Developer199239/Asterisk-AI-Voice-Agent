Good progress. Yes, next step is `fetch_doctor_list`. Here are all the details:

---

## Tool Configuration

### Admin UI Settings

| Field | Value |
|---|---|
| **Tool Name** | `fetch_doctor_list` |
| **Enabled** | ON |
| **Global** | OFF |
| **URL** | `http://192.168.0.170:8080/api/v1/tools/doctors` |
| **Method** | GET |
| **Timeout** | 5000 |

### Headers
```
Content-Type: application/json
X-Tenant-ID: 1
X-API-Key: dev-api-key-replace-in-production
```

### Tool Description
```
Fetches the list of available doctors in the system. Called when the patient 
wants to book an appointment or asks which doctors are available. Returns 
doctor names, IDs, specialties, and consultation durations.
```

### AI Parameters
None — no parameters needed (GET request, no body)

### Body Template
*(leave empty)*

### Return Raw JSON to AI
**ON** — the AI needs the full doctor list to present names and store IDs

### Output Variables
*(leave empty — Raw JSON handles everything)*

### Error Message
```
I'm sorry, I wasn't able to fetch the doctor list right now. Please try again.
```

---

## YAML (`config/ai-agent.local.yaml`)

```yaml
in_call_tools:
  fetch_doctor_list:
    kind: in_call_http_lookup
    phase: in_call
    enabled: true
    is_global: false
    timeout_ms: 5000
    url: http://192.168.0.170:8080/api/v1/tools/doctors
    method: GET
    headers:
      Content-Type: application/json
      X-Tenant-ID: '1'
      X-API-Key: dev-api-key-replace-in-production
    return_raw_json: true
    error_message: I'm sorry, I wasn't able to fetch the doctor list right now. Please try again.
    description: >-
      Fetches the list of available doctors. Called when patient wants to book
      an appointment. Returns doctor names, IDs, specialties and durations.
```

Add to context tools list:
```yaml
contexts:
  default:
    tools:
      - fetch_doctor_list
      - register_patient
      - hangup_call
```

---

## Updated Full Prompt

```
You are Ava, a voice assistant for the Smart Doctor Appointment System.

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
When the patient wants to book an appointment or asks about available doctors:

1. Immediately call fetch_doctor_list — do NOT say anything before calling it

2. From the response data.content array, read the doctor list.
   Present based on count:
   - 1 doctor:  "The available doctor is Dr. [fullName]. Would you like to book?"
   - 2 doctors: "The available doctors are Dr. [fullName1] and Dr. [fullName2].
                 Which would you prefer?"
   - 3+ doctors: "The available doctors are Dr. [fullName1], Dr. [fullName2],
                  and Dr. [fullName3]. Which doctor would you like to see?"

3. Remember the full doctor list (id, fullName, specialty) for the next step.

4. When patient selects a doctor:
   - Match their spoken name to the list → get the doctor's id
   - Say: "Let me check Dr. [fullName]'s availability."
   - Call check_doctor_slots (next tool)

## DOCTOR FLOW RULES
- Always call fetch_doctor_list before mentioning any doctor names
- Never make up doctor names — only use names from the API response
- Always store the selected doctor id for the booking step
- If fetch_doctor_list returns empty list:
  Say: "I'm sorry, there are no doctors available right now.
  Please call back later or visit us in person."

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

## Flow So Far

```
Call → name_look_up (pre-call)
           │
    ┌──────┴──────┐
  Found         Not Found
    │               │
"Welcome        "Are you a
 {name}!"       new patient?"
    │               │
    │           register_patient
    │               │
    └──────┬────────┘
           │
   "I need a doctor"
           │
   fetch_doctor_list ← next tool ✅
           │
   "Dr. Hina or Dr. Zaid?"
           │
   check_doctor_slots ← after this
```

Once this is working, next is `check_doctor_slots`. Tell me when ready.