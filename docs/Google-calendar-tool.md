# Google Calendar tool

The **google_calendar** tool lets the AI voice agent interact with Google Calendar: list events, get a single event, create events, delete events, and find free appointment slots (with duration and slot alignment).

## Prerequisites / Setup

### 1. Enable the Google Calendar API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or select an existing one).
3. Navigate to **APIs & Services > Library**.
4. Search for **Google Calendar API** and click **Enable**.

### 2. Create a Service Account

1. In the Cloud Console, go to **APIs & Services > Credentials**.
2. Click **Create Credentials > Service Account**.
3. Give it a name (e.g. `asterisk-calendar`) and click **Create**.
4. Skip the optional role/access steps and click **Done**.
5. Click on the newly created service account, go to the **Keys** tab.
6. Click **Add Key > Create new key > JSON** and download the key file.
7. Place the JSON key file somewhere accessible to the Asterisk AI Voice Agent (e.g. `credentials/google-calendar-sa.json`).

### 3. Share Your Calendar with the Service Account

1. Open [Google Calendar](https://calendar.google.com/) in a browser.
2. Find the calendar you want the agent to use in the left sidebar.
3. Click the three-dot menu next to the calendar name and select **Settings and sharing**.
4. Under **Share with specific people or groups**, click **Add people and groups**.
5. Enter the service account email (found in the JSON key file as `client_email`, looks like `name@project.iam.gserviceaccount.com`).
6. Set the permission to **Make changes to events** (so the agent can create bookings).
7. Click **Send**.
8. Copy the **Calendar ID** from the **Integrate calendar** section (looks like `abc123@group.calendar.google.com`, or use `primary` for the main calendar).

### 4. Set Environment Variables

Add these to your `.env` file:

```bash
GOOGLE_CALENDAR_CREDENTIALS=credentials/google-calendar-sa.json
GOOGLE_CALENDAR_ID=abc123@group.calendar.google.com
GOOGLE_CALENDAR_TZ=America/New_York  # Your calendar's timezone
```

### 5. Enable in the Admin UI

1. Open the Admin UI and go to the **Tools** section.
2. Toggle **Google Calendar** to enabled.

Or set it directly in `config/ai-agent.yaml`:

```yaml
tools:
  google_calendar:
    enabled: true
```

### 6. Add to Your Context

Make sure `google_calendar` is in the tools list for the context(s) that should have calendar access:

```yaml
contexts:
  my_context:
    tools:
      - google_calendar
      - hangup_call
      # ... other tools
```

## Implementation

- **`gcal_tool.py`** -- Tool definition and execution (actions, config, slot logic).
- **`gcalendar.py`** -- Low-level Google Calendar API client (`GCalendar`).

## Dependencies

The tool requires the `google-api-python-client` package. It is already listed in the project's `requirements.txt`, but if you are installing manually:

```bash
pip install google-api-python-client>=2.0.0
```

## Environment

| Variable | Description |
|----------|-------------|
| `GOOGLE_CALENDAR_CREDENTIALS` | Path to the service account JSON key file (required). |
| `GOOGLE_CALENDAR_ID` | Calendar ID (default: `primary`). |
| `GOOGLE_CALENDAR_TZ` | Timezone for operations (fallback: `TZ`, then system/UTC). |

## Why `get_free_slots` is in this tool

AI models are generally weak at handling large datasets and at carrying out precise logical operations on them (e.g. interval arithmetic, consistent time alignment). If we fed the model a long list of raw calendar events and asked it to compute "free slots," we'd risk mistakes, inconsistency, and heavy token use. So the tool does that work in code and returns a small, deterministic list of slot start times the model can simply read out and act on.

The Google Calendar API only returns a list of events. For appointment booking over the phone, the agent needs to answer "When are you free?" with concrete, bookable start times. **`get_free_slots`** does that by:

1. **Interpreting the calendar** -- Events whose titles start with `free_prefix` (e.g. "Open") are treated as available windows; events with `busy_prefix` (e.g. "Busy" for a booked slot) are treated as blocked. The tool subtracts busy blocks from free blocks to get truly available intervals.
2. **Duration and alignment** -- It returns only start times where a slot of the requested length (e.g. 30 minutes) fits, and aligns those starts to round times (e.g. :00 and :30 for 30-minute slots). That avoids half-off times and gives the AI a short list of times it can read out naturally (e.g. "I have 2pm, 2:30pm, and 3pm").

So instead of the LLM having to fetch raw events and infer availability and alignment, this tool provides ready-to-say slot starts and supports creating the booking with `create_event` in the same flow.

## Config (ai-agent.yaml / Admin UI)

Under `tools.google_calendar`:

| Key | Description | Default |
|-----|-------------|---------|
| `enabled` | Turn the tool on or off. | `false` |
| `free_prefix` | Default prefix for events that define available windows (e.g. `"Open"`). The LLM can override this per-call. | *(none -- must be provided by LLM or config)* |
| `busy_prefix` | Default prefix for events that define booked slots (e.g. `"Busy"`). The LLM can override this per-call. | *(none -- must be provided by LLM or config)* |
| `min_slot_duration_minutes` | Default appointment duration in minutes for `get_free_slots`. | `15` |
| `calendars` | Map of named calendars (multi-account support). Each entry can set `credentials_path`, `calendar_id`, `timezone`. | *(optional)* |

Example (single or multiple calendars):

```yaml
tools:
  google_calendar:
    enabled: true
    free_prefix: "Open"
    busy_prefix: "Busy"
    min_slot_duration_minutes: 30
    calendars:
      work:
        credentials_path: credentials/work-sa.json
        calendar_id: abc@group.calendar.google.com
        timezone: America/Denver
      personal:
        credentials_path: credentials/personal-sa.json
        calendar_id: primary
        timezone: America/Denver
```

### Per-context calendar selection

Each context binds to **exactly one calendar**. This keeps the routing
unambiguous: when the caller says "book me for 2pm," the agent always
knows which calendar the event belongs to.

In the Admin UI (Contexts → Edit Context → Google Calendar), pick one
calendar. The others become disabled until you clear the selection.

Equivalent YAML:

```yaml
contexts:
  sales:
    tools:
      - google_calendar
    tool_overrides:
      google_calendar:
        selected_calendars: [work]   # single entry — the UI enforces this
```

**Missing vs. empty `selected_calendars`:**

| `selected_calendars` value | Behavior |
|----------------------------|----------|
| Omitted (not present) | Context uses **all** configured calendars (legacy / single-calendar default). |
| `[calendar_key]` | Context uses that one calendar. **Recommended.** |
| `[]` (empty list) | No calendars available to this context — all calendar actions return an authorization error (fail-closed). |

- If `calendars` is omitted at the tool root but env vars are set, the tool will auto-materialize `calendars.default` from `GOOGLE_CALENDAR_*` and use it.

### Power-user: cross-calendar availability via YAML

The UI constrains each context to one calendar because that matches how
99% of deployments use the tool. However, the backend still supports
multiple `selected_calendars` entries for one specific use case:
**aggregating availability across multiple calendars in `get_free_slots`**
(e.g. "find a time when both my work and personal calendars are free").

This has to be set up in YAML — the UI will not produce a multi-calendar
selection, and editing a context in the UI after setting this will reset
it to single-select.

```yaml
contexts:
  unified_assistant:
    tools:
      - google_calendar
    tool_overrides:
      google_calendar:
        selected_calendars: [work, personal]   # YAML-only — not representable in UI
```

When multiple calendars are selected:

- `get_free_slots` aggregates across all of them. `aggregate_mode: all` (default) returns times free on every calendar; `aggregate_mode: any` returns times free on any calendar.
- `list_events` merges events from all selected calendars.
- `create_event`, `delete_event`, `get_event` fall back to the first calendar in the list when the LLM doesn't pass `calendar_key` — this is why the UI forces single-select, to avoid the LLM silently picking a default.

If you use multi-calendar YAML, the LLM needs `calendar_key` to be
explicit for create/delete actions, so you must prompt it with the
available calendar keys in your context instructions (e.g. "Available
calendars: `work`, `personal`. Use `calendar_key` to specify which one
for any booking.").

## Actions

In the normal (UI-configured) case, each context has exactly one
selected calendar, so the LLM does not need to pass `calendar_key` —
the tool uses the context's single calendar automatically. The
`calendar_key` and `aggregate_mode` parameters below only matter for
the multi-calendar YAML setup described above.

| Action | Purpose |
|--------|--------|
| `list_events` | List events in a time range (`time_min`, `time_max`). With one calendar selected, returns events from that calendar. With multiple (YAML only), aggregates across all selected calendars; pass `calendar_key` to target a specific one. |
| `get_event` | Get one event by `event_id`. Uses the context's single calendar, or pass `calendar_key` for multi-calendar YAML setups. |
| `create_event` | Create event with `summary`, `start_datetime`, `end_datetime` (optional `description`). Uses the context's single calendar; in multi-calendar YAML setups, pass `calendar_key` to target a specific one (otherwise falls back to the first selected calendar). |
| `delete_event` | Delete an event by `event_id`. Uses the context's single calendar, or pass `calendar_key` for multi-calendar YAML setups. |
| `get_free_slots` | Return start times where a slot of given `duration` (minutes) fits. Uses `free_prefix` / `busy_prefix` to compute available intervals. With multiple calendars selected (YAML only), aggregates via `aggregate_mode`: `all` (default) = intersection (time is free on every calendar), `any` = union. Pass `calendar_key` to constrain to one calendar. Slot starts are aligned to multiples of `duration`. |

All times use ISO 8601. The tool is registered as `google_calendar` and is in the **business** tool category.

## Prompt examples (how callers use the tool)

Example things a caller might say, and the kind of **google_calendar** call the agent should make in response.

- **"What do I have on my calendar tomorrow?"**
  -> `list_events` with `time_min` / `time_max` covering tomorrow in the calendar's timezone.

- **"When are you free for a 30-minute appointment next Tuesday?"**
  -> `get_free_slots` with `time_min` / `time_max` for that day, `duration: 30`, and (if not in config) `free_prefix` / `busy_prefix` as needed.

- **"Do you have 2pm available?"**
  -> Either `get_free_slots` for that day and check if 2pm is in the list, or `list_events` for a short window around 2pm and interpret.

- **"Book me for 2:30pm next Tuesday for 30 minutes."**
  -> `create_event` with `summary` (e.g. appointment title), `start_datetime` = 2:30pm that day, `end_datetime` = 3:00pm that day; optional `description`.

- **"What's the details of my appointment on Thursday at 10?"**
  -> `list_events` for that morning, find the matching event, then optionally `get_event` with that event's `event_id` for full details.

- **"Cancel my 3pm meeting."**
  -> `list_events` for that day to find the event, then `delete_event` with that event's `event_id` to cancel it.

## Sample context system prompts

The LLM only knows what your context's `instructions` (system prompt)
tells it. A good prompt turns the calendar tool from a generic API
into a specific, reliable agent. Two templates below — a standard
single-calendar agent (the common case), and the multi-calendar YAML
variant.

### Single-calendar appointment agent (recommended default)

Use this when the context is bound to one calendar via the Admin UI.
No `calendar_key` is needed because the backend already knows which
calendar to use.

```text
You are the scheduling assistant for Acme Dental. You book, reschedule,
and cancel appointments using the google_calendar tool.

Time & timezone rules:
- The calendar is configured for America/New_York. Always speak and
  reason in that timezone. If the caller says a bare time like "2pm",
  assume it's 2pm Eastern.
- Today's date is provided in the runtime context — never guess the date.
- All datetimes sent to google_calendar must be ISO 8601 (e.g.
  2026-04-23T14:00:00). Seconds may be :00.

Finding available times:
- When a caller asks for availability, use the action get_free_slots.
  - time_min / time_max: cover the day or range they asked about, in
    the calendar timezone.
  - duration: default 30 minutes unless the caller says otherwise.
  - free_prefix: "Open"
  - busy_prefix: "Busy"
- Read back at most 3 options at a time (e.g. "I have 9am, 10:30am, or
  2pm — which works?"). Don't recite the whole list.

Booking:
- Once the caller confirms a time, call create_event.
  - summary: "{caller_name} — {reason}" (e.g. "Jane Smith — Cleaning")
  - start_datetime / end_datetime: the agreed slot, aligned to the
    slot grid get_free_slots returned.
  - description: include the caller's phone number and any notes.
- After a successful booking, read back the confirmed date and time
  once, then move on. Do not re-book the same slot.

Looking up or canceling:
- For "what do I have on {day}?" use list_events for that day.
- For cancellations, use list_events first to get the event_id, confirm
  with the caller which appointment they mean, then call delete_event.

Never promise a time you haven't verified with get_free_slots first.
If the tool returns an error, apologize briefly and offer to take a
message or try a different day.
```

### Multi-calendar (YAML-only escape hatch)

If you've configured multiple calendars in `selected_calendars` via
YAML (see "Power-user: cross-calendar availability" above), the LLM
needs to know the calendar keys by name and which to pick. Add a
section like this to your system prompt:

```text
This context has access to two calendars:
- work — used for customer meetings, demos, and anything work-related.
- personal — used for personal appointments (dentist, gym, family).

When the caller asks to book or cancel something:
- If they say "at work", "team meeting", "customer call", or similar,
  pass calendar_key: "work".
- If they say "personal", "doctor", "family", etc., pass
  calendar_key: "personal".
- If it's ambiguous, ask: "Should I put that on your work or personal
  calendar?" — do not guess.

When the caller asks "when am I free", use get_free_slots WITHOUT a
calendar_key. The tool will aggregate across both calendars and
return only times that are free on both (aggregate_mode: all), which
is the right behavior for finding a time that works for everything.

When the caller asks "what do I have on {day}", use list_events
without calendar_key to see everything across both calendars.
```

> **Tip:** pair the multi-calendar prompt with a clearly-named context
> (e.g. `unified_assistant`) so it's obvious the LLM is meant to pick
> between calendars. Don't mix this prompt into a context that's also
> bound to a single-calendar UI selection — you'll get contradictory
> signals.
