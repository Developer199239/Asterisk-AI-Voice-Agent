# FUTURE: Unify Outbound Dialplan Context

**Status:** Deferred — do not implement until both outbound flows are stable in production  
**Raised:** 2026-07-12  
**Author:** Jalilur Rahman Murtuza  

---

## The Issue

There are currently two separate Asterisk dialplan contexts and two different extension
formats for outbound calls. They do the same job (dial → AMD → no-answer curl) but with
different payloads, which means duplicate maintenance:

| Call type | Extension format | Dialplan context | Env var |
|---|---|---|---|
| outbound_reminder | `{phone}_{appt_id}_{patient_id}` | `[from-ai-outbound]` | `AAVA_OUTBOUND_DIAL_CONTEXT` |
| outbound_lead | `{phone}_{lead_id}` | `[from-ai-outbound-lead]` | `AAVA_OUTBOUND_LEAD_DIAL_CONTEXT` |

**Concrete problems:**

1. Any change to the AMD parameters or curl headers must be made in two places.
2. Two env vars (`AAVA_OUTBOUND_DIAL_CONTEXT` and `AAVA_OUTBOUND_LEAD_DIAL_CONTEXT`) must
   both be kept in sync in `.env` and in every deployment doc.
3. Adding a third outbound type in the future (e.g. `outbound_survey`) requires a third
   context, a third env var, and another copy of the same dial + AMD + curl logic.

---

## Proposed Solution

### 1. New unified extension format

Prefix the extension with a short type token:

```
{type}_{phone}_{id1}[_{id2}]
```

Examples:
```
reminder_6002_29_3    → type=reminder, phone=6002, appointment_id=29, patient_id=3
lead_6001_9           → type=lead,     phone=6001, lead_id=9
```

The Asterisk `CUT()` function reads each segment by position:
- `CUT(EXTEN,_,1)` → type
- `CUT(EXTEN,_,2)` → phone
- `CUT(EXTEN,_,3)` → id1 (appointment_id or lead_id)
- `CUT(EXTEN,_,4)` → id2 (patient_id — empty for lead)

### 2. Single dialplan context `[from-ai-outbound]`

Replace both contexts with one. Use `_.` pattern (matches any string).
After AMD, on no-answer, branch on `CALL_TYPE` to send the correct HOS payload:

```asterisk
[from-ai-outbound]
exten => _.,1,NoOp(Unified outbound - exten=${EXTEN})
 same => n,Set(CALL_TYPE=${CUT(EXTEN,_,1)})
 same => n,Set(DIAL_NUMBER=${CUT(EXTEN,_,2)})
 same => n,Set(ID1=${CUT(EXTEN,_,3)})
 same => n,Set(ID2=${CUT(EXTEN,_,4)})
 same => n,NoOp(type=${CALL_TYPE} phone=${DIAL_NUMBER} id1=${ID1} id2=${ID2})
 same => n,Dial(PJSIP/${DIAL_NUMBER},20,U(sub-amd-check,s,1))
 same => n,NoOp(DIALSTATUS=${DIALSTATUS})
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,Set(CALL_RESULT=${IF($["${DIALSTATUS}"="BUSY"]?busy:no_answer)})
 same => n,GotoIf($["${CALL_TYPE}" = "lead"]?curl_lead:curl_reminder)
 same => n(curl_reminder),Set(IGNORED=${SHELL(curl -s -X POST http://168.144.27.225/api/v1/tools/call-result -H 'Content-Type: application/json' -H 'X-Tenant-ID: 1' -H 'X-API-Key: dev-api-key-replace-in-production' --data '{"appointmentId":"${ID1}","result":"${CALL_RESULT}","patientId":"${ID2}"}' --max-time 5)})
 same => n,Goto(done)
 same => n(curl_lead),Set(IGNORED=${SHELL(curl -s -X POST http://168.144.27.225/api/v1/tools/call-result -H 'Content-Type: application/json' -H 'X-Tenant-ID: 1' -H 'X-API-Key: dev-api-key-replace-in-production' --data '{"leadId":"${ID1}","result":"${CALL_RESULT}"}' --max-time 5)})
 same => n(done),Hangup()

exten => h,1,NoOp(Hangup handler: DIALSTATUS=${DIALSTATUS} CALL_TYPE=${CALL_TYPE})
 same => n,GotoIf($["${CALL_RESULT}" != ""]?done)
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done)
 same => n,GotoIf($["${ID1}" = ""]?done)
 same => n,Set(CALL_RESULT=no_answer)
 same => n,GotoIf($["${CALL_TYPE}" = "lead"]?curl_lead:curl_reminder)
 same => n(curl_reminder),Set(IGNORED=${SHELL(curl -s -X POST http://168.144.27.225/api/v1/tools/call-result -H 'Content-Type: application/json' -H 'X-Tenant-ID: 1' -H 'X-API-Key: dev-api-key-replace-in-production' --data '{"appointmentId":"${ID1}","result":"${CALL_RESULT}","patientId":"${ID2}"}' --max-time 5)})
 same => n,Goto(done)
 same => n(curl_lead),Set(IGNORED=${SHELL(curl -s -X POST http://168.144.27.225/api/v1/tools/call-result -H 'Content-Type: application/json' -H 'X-Tenant-ID: 1' -H 'X-API-Key: dev-api-key-replace-in-production' --data '{"leadId":"${ID1}","result":"${CALL_RESULT}"}' --max-time 5)})
 same => n(done),NoOp(Hangup handler done)
```

### 3. Single env var

Remove `AAVA_OUTBOUND_LEAD_DIAL_CONTEXT` from `.env`. Both call types share:

```env
AAVA_OUTBOUND_DIAL_CONTEXT=from-ai-outbound
```

### 4. `outbound_trigger.py` changes

Both branches build the extension with the type prefix and use the same dial context helper:

```python
# outbound_reminder branch:
_dial_ext = f"reminder_{req.phone_number}_{req.appointment_id}_{req.patient_id}"
dial_context = _outbound_dial_context()   # same helper for both

# outbound_lead branch:
_dial_ext = f"lead_{req.phone_number}_{req.lead_id}"
dial_context = _outbound_dial_context()   # same helper
```

---

## Files That Would Change

| File | What changes |
|---|---|
| `admin_ui/backend/api/outbound_trigger.py` | Extension format for both branches; both use `_outbound_dial_context()`; remove `_outbound_lead_dial_context()` |
| `docs/murtuza_dev_notes/3_extension_custom.conf` | Merge `[from-ai-outbound]` and `[from-ai-outbound-lead]` into one unified context; remove `[from-ai-outbound-lead]` |
| `.env` / `.env.example` | Remove `AAVA_OUTBOUND_LEAD_DIAL_CONTEXT` |
| HOS backend Java | `OutboundQueuePersistence` builds the trigger payload — must also produce the new `reminder_` / `lead_` prefixed extension format |

**No changes needed to:**
- `src/engine.py` — appArgs[0] is still `outbound_reminder` / `outbound_lead`
- `config/ai-agent.local.yaml` — context names unchanged
- `[sub-amd-check]` — already shared, no changes

---

## Why We Deferred

- Both flows just became stable after several bug fixes. Changing the extension format
  now risks regressions in working production code.
- The HOS Java backend also needs to change, which is a cross-team coordination cost.
- The benefit (one context, one env var) is organizational — it fixes no bugs and adds
  no features.
- Risk of the `_.` pattern: it is more permissive than `_X.`. Any extension that
  accidentally enters the context will be dialed. Mitigate by ensuring the context is
  only reachable from ARI originate, not from trunks or internal routing.

---

## When to Do This

Revisit when:
1. A third outbound call type is needed (the duplication cost becomes real).
2. A planned HOS backend release is already requiring changes to `OutboundQueuePersistence`.
3. Both outbound flows have been stable in production for at least 2 weeks with no curl
   or AMD bugs.
