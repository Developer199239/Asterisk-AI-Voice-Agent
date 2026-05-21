Good progress. Now working directly in the root directory. Here are all the details for the `register_patient` tool.

---

## Tool Configuration

### Admin UI Settings

| Field | Value |
|---|---|
| **Tool Name** | `register_patient` |
| **Enabled** | ON |
| **Global** | OFF |
| **URL** | `http://192.168.0.170:8080/api/v1/tools/patients/register` |
| **Method** | POST |
| **Timeout** | 5000 |

### Headers
```
Content-Type: application/json
X-Tenant-ID: 1
X-API-Key: dev-api-key-replace-in-production
```

### Tool Description
```
Registers a new patient in the system. Called after collecting the patient's 
full name when name_look_up returns not found. Uses caller phone number 
automatically. All consent fields are set to true by default.
```

### AI Parameters
Add **one** parameter:

| Parameter Name | Type | Required | Description |
|---|---|---|---|
| `fullName` | string | yes | Full name of the patient as spoken by the caller |

### Body Template
```json
{
    "fullName": "{fullName}",
    "phone": "{caller_number}",
    "consentDataProcessing": true,
    "consentAiInteraction": true,
    "consentCommunication": true
}
```

### Output Variables

| Variable Name | JSON Path |
|---|---|
| `reg_success` | `success` |
| `reg_patient_id` | `data.id` |
| `reg_patient_name` | `data.fullName` |
| `reg_patient_code` | `data.patientCode` |

### Error Message
```
I'm sorry, I wasn't able to register you at this time. Please try again.
```

---

## YAML (ai-agent.local.yaml)

```yaml
tools:
  register_patient:
    kind: in_call_http
    enabled: true
    is_global: false
    timeout_ms: 5000
    url: "http://192.168.0.170:8080/api/v1/tools/patients/register"
    method: POST
    headers:
      Content-Type: "application/json"
      X-Tenant-ID: "1"
      X-API-Key: "dev-api-key-replace-in-production"
    body_template: |
      {
        "fullName": "{fullName}",
        "phone": "{caller_number}",
        "consentDataProcessing": true,
        "consentAiInteraction": true,
        "consentCommunication": true
      }
    output_variables:
      reg_success: "success"
      reg_patient_id: "data.id"
      reg_patient_name: "data.fullName"
      reg_patient_code: "data.patientCode"
```

Add `register_patient` to your context tools list:
```yaml
contexts:
  default:
    pre_call_tools:
      - name_look_up
    tools:
      - register_patient
      - hangup_call
```

---

## Updated Prompt Section

Add this block to your existing prompt:

```
## NEW PATIENT REGISTRATION FLOW

If lookup_success is "False" or patient_name is empty:
1. Greet: "Welcome to the Smart Doctor Appointment System! This is Ava. 
   I don't see your information in our system. Are you a new patient?"

2. If user says YES:
   - Ask: "What is your full name?"
   - Wait for the name
   - Call register_patient immediately with the name they provided
   - Do NOT say anything before calling the tool

3. After register_patient response:
   - If reg_success is "True":
     Say: "Thank you {reg_patient_name}! You are now registered. 
     Your patient code is {reg_patient_code}. How can I help you today?"
   - If reg_success is "False":
     Say: "I'm sorry, I wasn't able to register you right now. 
     Please call back or visit us in person."

4. If user says NO (not a new patient):
   - Ask: "Let me look you up by name. What is your full name?"
   - Wait — manual lookup flow (next tool)

## RULES FOR REGISTRATION
- Never register without collecting the full name first
- Never ask for consent — it is given automatically
- Never ask for phone number — it is captured from the call automatically
- Never mention tool names to the caller
```

---

## Complete Flow

```
Call starts → name_look_up (pre-call)
                    │
         ┌──────────┴──────────┐
     Found ✅               Not Found ❌
         │                      │
  "Welcome John!"         "Are you a new patient?"
                                │
                         User: "Yes"
                                │
                    "What is your full name?"
                                │
                         User: "Rahim"
                                │
                    register_patient called
                    {fullName: "Rahim", phone: "6001", ...}
                                │
                    "Thank you Rahim! Your patient 
                     code is P-000008. How can I help?"
```

Once this is working, tell me and we move to the next tool (`fetch_doctor_list`).