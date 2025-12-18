# Milestone 21: Call History & Analytics Dashboard

**Status**: 🟡 Core Complete (Milestone Partially Complete)  
**Priority**: High  
**Estimated Effort**: 7 days  
**Branch**: `feature/call-history`

## Summary

Implement a comprehensive Call History feature in the Admin UI with debugging capabilities, analytics dashboard, and search/filter functionality. This enables operators to review past calls, debug issues, and analyze call patterns.

## Motivation

Currently, `CallSession` data is in-memory only and deleted when calls end (`session_store.remove_call()`). Operators have no way to:

- Review past call conversations
- Debug failed calls
- Analyze call patterns and performance
- Track tool execution success rates

## Data Model

### CallRecord

```python
@dataclass
class CallRecord:
    # Core
    id: str                          # UUID
    call_id: str                     # Asterisk channel ID
    caller_number: Optional[str]
    caller_name: Optional[str]
    
    # Timing
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    
    # Configuration
    provider_name: str
    pipeline_name: Optional[str]
    pipeline_components: Dict[str, str]  # {stt: "vosk", llm: "ollama", tts: "piper"}
    context_name: Optional[str]
    
    # Conversation
    conversation_history: List[Dict]  # [{role, content, timestamp}]
    
    # Outcome
    outcome: str                      # completed | transferred | error | abandoned
    transfer_destination: Optional[str]
    error_message: Optional[str]
    
    # Tool Executions (Debugging)
    tool_calls: List[Dict]            # [{name, params, result, timestamp, duration_ms}]
    
    # Latency Metrics (Debugging)
    avg_turn_latency_ms: float
    max_turn_latency_ms: float
    total_turns: int
    
    # Audio Stats (Debugging)
    caller_audio_format: str
    codec_alignment_ok: bool
    barge_in_count: int
```

### SQLite Schema

```sql
CREATE TABLE call_records (
    id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL,
    caller_number TEXT,
    caller_name TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_seconds REAL,
    provider_name TEXT,
    pipeline_name TEXT,
    pipeline_components TEXT,  -- JSON
    context_name TEXT,
    conversation_history TEXT,  -- JSON
    outcome TEXT,
    transfer_destination TEXT,
    error_message TEXT,
    tool_calls TEXT,           -- JSON
    avg_turn_latency_ms REAL,
    max_turn_latency_ms REAL,
    total_turns INTEGER,
    caller_audio_format TEXT,
    codec_alignment_ok INTEGER,
    barge_in_count INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_call_records_start_time ON call_records(start_time);
CREATE INDEX idx_call_records_caller_number ON call_records(caller_number);
CREATE INDEX idx_call_records_outcome ON call_records(outcome);
CREATE INDEX idx_call_records_provider ON call_records(provider_name);
CREATE INDEX idx_call_records_pipeline ON call_records(pipeline_name);
CREATE INDEX idx_call_records_context ON call_records(context_name);
```

**Storage Location**: `data/call_history.db` (gitignored)

## Implementation Phases

### Phase 1: Persistence Layer (2 days)

| Step | Files | Description |
|------|-------|-------------|
| 1.1 | `src/core/call_history.py` | `CallRecord` dataclass + SQLite storage class |
| 1.2 | `src/core/call_history.py` | CRUD: `save()`, `get()`, `list()`, `delete()`, `search()` |
| 1.3 | `src/engine.py` | Hook `_cleanup_call` to persist before `remove_call()` |
| 1.4 | `src/engine.py` | Add tool execution logging to session |
| 1.5 | `src/engine.py` | Add timestamps to conversation history entries |
| 1.6 | `.env.example` | `CALL_HISTORY_RETENTION_DAYS=0` (0 = unlimited) |
| 1.7 | `src/core/call_history.py` | Retention cleanup task (if configured) |

### Phase 2: Backend API (2 days)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/calls` | GET | List with pagination, filters |
| `/api/calls/{id}` | GET | Full call detail |
| `/api/calls/{id}/transcript` | GET | Just conversation history |
| `/api/calls/{id}` | DELETE | Delete single record |
| `/api/calls` | DELETE | Bulk delete (by date range) |
| `/api/calls/export` | GET | CSV/JSON export |
| `/api/calls/stats` | GET | Aggregate stats |

**New File**: `admin_ui/backend/api/calls.py`

### Phase 3: Frontend UI (3 days)

| Component | Description |
|-----------|-------------|
| `CallHistoryPage.tsx` | Table with sorting, pagination |
| `CallStatsWidget.tsx` | Stats dashboard with charts |
| `CallDetailModal.tsx` | Full call view with tabs |
| Tab: Overview | Duration, caller, provider, outcome |
| Tab: Transcript | Conversation with timestamps |
| Tab: Tools | Tool executions with params/results |
| Tab: Metrics | Latency chart, audio stats |

### Phase 4: Audio Recording Integration (Future - Deferred)

Asterisk already handles call recording. This phase would add UI to link/play recordings if needed.

## Search & Filter Capabilities

| Filter | Type | Description |
|--------|------|-------------|
| Date Range | date-picker | Start/end date |
| Caller Number | text | Partial match |
| Caller Name | text | Partial match |
| Provider | dropdown | deepgram, openai_realtime, elevenlabs, local, etc. |
| Pipeline | dropdown | local_hybrid, openai, etc. |
| Context | dropdown | AI_CONTEXT values from dialplan |
| Outcome | dropdown | completed, transferred, error, abandoned |
| Duration | range | Min/max seconds |
| Has Tool Calls | boolean | Filter calls with tool executions |

## Stats Dashboard

| Metric | Visualization |
|--------|---------------|
| Calls per day/hour | Line chart |
| Avg call duration | Stat card |
| Outcome breakdown | Pie chart |
| Provider usage | Bar chart |
| Pipeline usage | Bar chart |
| Context usage | Bar chart |
| Tool execution success rate | Stat card |
| Avg turn latency | Stat card + trend |
| Top callers | Table |

## Configuration

Add to `.env`:

```bash
# Call History Settings
CALL_HISTORY_ENABLED=true
CALL_HISTORY_RETENTION_DAYS=0      # 0 = unlimited
CALL_HISTORY_DB_PATH=data/call_history.db
```

## Files to Create

| File | Description |
|------|-------------|
| `src/core/call_history.py` | CallRecord model + SQLite storage |
| `admin_ui/backend/api/calls.py` | REST API endpoints |
| `admin_ui/frontend/src/pages/CallHistoryPage.tsx` | Main page |
| `admin_ui/frontend/src/components/CallDetailModal.tsx` | Detail view |
| `admin_ui/frontend/src/components/CallStatsWidget.tsx` | Stats dashboard |

## Files to Modify

| File | Changes |
|------|---------|
| `src/engine.py` | Hook cleanup, add tool logging, add timestamps |
| `src/core/models.py` | Add `tool_calls` list to CallSession |
| `admin_ui/backend/main.py` | Register calls router |
| `admin_ui/frontend/src/App.tsx` | Add route |
| `.env.example` | Add config vars |
| `.gitignore` | Add `data/call_history.db` |

## Acceptance Criteria

- [x] Call records persist to SQLite after call ends
- [x] Admin UI shows paginated call history list
- [x] Filters work for all search dimensions
- [x] Call detail view shows full transcript with timestamps
- [x] Tool executions visible in call detail
- [ ] Stats dashboard shows aggregate metrics with charts *(stat cards implemented, charts deferred)*
- [x] Export works (CSV/JSON)
- [ ] Retention cleanup works when configured *(method exists, scheduler not implemented)*
- [x] No performance impact on active calls

## Technical Notes

### Outcome Determination Logic

```python
def determine_outcome(session: CallSession) -> str:
    if session.error_message:
        return "error"
    if session.transfer_destination:
        return "transferred"
    if not session.conversation_history:
        return "abandoned"
    return "completed"
```

### Tool Call Logging

Add to `_execute_provider_tool`:

```python
tool_record = {
    "name": function_name,
    "params": parameters,
    "result": result.get("status"),
    "timestamp": datetime.now().isoformat(),
    "duration_ms": (end_time - start_time) * 1000
}
session.tool_calls.append(tool_record)
```

### Conversation History Timestamps

Modify history append to include timestamp:

```python
session.conversation_history.append({
    "role": "user",
    "content": text,
    "timestamp": datetime.now().isoformat()
})
```

## Deferred Items (v4.5.4+)

The following items were identified during implementation but deferred for future releases:

### ~~Date Filtering Timezone Handling~~ ✅ FIXED

- **Issue**: UI sends `YYYY-MM-DD`, backend parses to naive datetime, DB stores UTC offset strings and compares lexicographically - end_date may exclude the entire day
- **Status**: ✅ Fixed - Date-only inputs now parsed to start/end-of-day in server TZ, converted to UTC

### ~~List API Returns Full Conversation History~~ ✅ FIXED

- **Issue**: `/api/calls` returns full `conversation_history` + `tool_calls` for every row
- **Status**: ✅ Fixed - Summary model for list, detail fetch on row click with lazy loading

### Transcript Timestamps Missing

- **Issue**: Some conversation history appends don't include `timestamp` field
- **Impact**: Data quality - UI expects timestamps for display
- **Fix**: Audit all `conversation_history.append()` calls in `engine.py` and add timestamps
- **Files**: `src/engine.py` lines ~4984, ~4995, ~5529
- **Effort**: Low

### Retention Scheduler Not Implemented

- **Issue**: `cleanup_old_records()` exists but nothing schedules it
- **Impact**: Database grows unbounded even with `CALL_HISTORY_RETENTION_DAYS` set
- **Fix**: Add background task to periodically run cleanup (daily)
- **Effort**: Low

### Tool Duration Always 0ms

- **Issue**: Tool call records have `duration_ms: 0` - actual execution time not tracked
- **Impact**: Nice-to-have debugging info
- **Fix**: Wrap tool execution with timing in each provider's `_handle_function_call`
- **Effort**: Medium

### ~~Tool Params May Be String vs Object~~ ✅ FIXED

- **Issue**: Some providers store `params` as JSON string, UI assumes object for pretty printing
- **Status**: ✅ Fixed - API normalizes params strings to objects before returning

## References

- Current session model: `src/core/models.py` (CallSession)
- Session cleanup: `src/engine.py` (_cleanup_call)
- Admin UI backend: `admin_ui/backend/api/`
- Admin UI frontend: `admin_ui/frontend/src/`
- Milestone 19: Admin UI Implementation

---

**Linear Issue**: AAVA-138 (to be created manually)  
**Created**: December 17, 2025  
**Last Updated**: December 18, 2025
