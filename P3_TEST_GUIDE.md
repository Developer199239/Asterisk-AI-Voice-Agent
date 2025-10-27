# P3 Phase 2 - Dashboard Testing Guide

## ✅ Status: Dashboard Deployed & Ready

**System Overview Dashboard** is now live and ready to collect metrics!

---

## Dashboard Access

**URL**: http://207.38.71.85:3000

**Login**: admin / admin2025

**Dashboard**: "AI Voice Agent - System Overview"
- Navigate to: Dashboards → AI Voice Agent folder → System Overview

---

## Dashboard Panels (6 total)

1. **Active Calls** - Current number of calls in progress
2. **System Health** - UP/DOWN status of ai_engine
3. **AudioSocket Connections** - Active TCP connections  
4. **Memory Usage** - Process memory over time
5. **Call Rate** - Calls per minute (5min rate)
6. **Provider Distribution** - Pie chart of Deepgram vs OpenAI (last hour)

---

## Test Call Instructions

### Option 1: Quick Test (Recommended)

Make 5-10 short test calls to generate initial metrics:

```bash
# From your phone or SIP client
# Dial your Asterisk server's AI extension

# Example scenarios:
1. "Hello, how are you?" - Simple greeting
2. "What's the weather like?" - Question
3. "Tell me a joke" - Request
4. Practice barge-in: interrupt the agent mid-response
5. Long conversation: ask follow-up questions
```

**Duration**: 20-60 seconds per call  
**Total time**: ~10 minutes for 10 calls

### Option 2: Systematic Testing

Test different providers and scenarios:

**Deepgram Calls** (5 calls):
- 2 short calls (20-30s)
- 2 medium calls (60-90s)
- 1 long call (2-3 min)

**OpenAI Realtime Calls** (5 calls):
- 2 short calls (20-30s)
- 2 medium calls (60-90s)
- 1 long call (2-3 min)

**Special Tests**:
- 1 call with frequent barge-ins
- 1 call with noisy background
- 1 call with silence/pauses

**Total**: 12 calls, ~30 minutes

---

## Real-Time Monitoring

### During Calls

1. **Open Dashboard**: http://207.38.71.85:3000/d/ai-voice-agent-system
2. **Set Time Range**: "Last 15 minutes"
3. **Auto-refresh**: Click refresh icon → Set to "5s" or "10s"
4. **Watch Metrics**:
   - Active Calls should increment to 1 during call
   - System Health should stay green (UP)
   - AudioSocket Connections should show 1+
   - Call Rate should increase
   - Provider Distribution should populate

### After Calls

1. **Check Historical Data**:
   - Set time range to "Last 1 hour"
   - Review call rate trends
   - Verify provider distribution pie chart

2. **Query Prometheus Directly**:
   ```bash
   # Check total calls started
   curl -s 'http://207.38.71.85:9090/api/v1/query?query=ai_agent_stream_started_total' | python3 -m json.tool
   
   # Check AudioSocket bytes
   curl -s 'http://207.38.71.85:9090/api/v1/query?query=ai_agent_audiosocket_rx_bytes_total' | python3 -m json.tool
   ```

---

## Expected Behavior

### Before Calls (No Activity)

- **Active Calls**: 0
- **System Health**: UP (green, value=1)
- **AudioSocket Connections**: 0
- **Memory Usage**: ~200-400 MB baseline
- **Call Rate**: 0 calls/min
- **Provider Distribution**: Empty or showing "No data"

### During First Call

- **Active Calls**: 1
- **AudioSocket Connections**: 1 (or 2 with full-duplex)
- **Memory Usage**: Slight increase (~50-100 MB)
- **System Health**: Stays green

### After 10 Calls

- **Call Rate**: Should show spikes when calls were placed
- **Provider Distribution**: Pie chart shows Deepgram and/or OpenAI percentages
- **Memory Usage**: Stable (no significant growth)
- **Total metrics collected**: 50+ different metrics per call

---

## Verification Checklist

After making test calls, verify:

- [ ] Dashboard loads without errors
- [ ] All 6 panels display data (not "No data")
- [ ] Active Calls returns to 0 after call ends
- [ ] System Health stays green throughout
- [ ] Call Rate graph shows activity spikes
- [ ] Provider Distribution pie chart populates
- [ ] Memory usage is stable (no leaks)
- [ ] Time range selector works
- [ ] Auto-refresh updates metrics

---

## Troubleshooting

### Dashboard Shows "No data"

**Check metrics are being collected**:
```bash
ssh root@voiprnd.nemtclouddispatch.com
curl http://localhost:15000/metrics | grep ai_agent | head -20
```

**Check Prometheus is scraping**:
- Open http://207.38.71.85:9090/targets
- Verify ai-engine target is UP
- Check "Last Scrape" is recent (<5s)

### Panels Show Errors

**Check Prometheus queries**:
- Open panel edit mode (click panel title → Edit)
- Click "Query inspector"
- Review query and error message
- Verify metric names match instrumentation

### Call Metrics Not Appearing

**Verify call completed successfully**:
```bash
# Check ai_engine logs for the call
ssh root@voiprnd.nemtclouddispatch.com
docker logs ai_engine --since 5m | grep -i "stream\|call\|audio"
```

**Check if metrics are per-call**:
- Some metrics use `call_id` label
- These will only appear DURING active calls
- After call ends, they're removed from metrics endpoint
- Use rate() or increase() to see historical data

---

## Next Steps After Testing

### 1. Validate Metrics (5 min)

Review Prometheus queries in dashboard work correctly:
- [ ] Queries return data
- [ ] Visualizations make sense
- [ ] No errors in panel inspector
- [ ] Time series data aligns with call timing

### 2. Create Remaining Dashboards (2-3 hours)

Use System Overview as template:

**Priority Order**:
1. **Call Quality** (most important - latency, underflows)
2. **Provider Performance** (compare Deepgram vs OpenAI)
3. **Audio Quality** (RMS, codec alignment)
4. **Conversation Flow** (state, gating, barge-in)

**Process**:
- Copy System Overview dashboard JSON
- Replace panel queries with specs from P3_DASHBOARDS_SUMMARY.md
- Adjust panel titles, types, and layout
- Test each panel with real data
- Save and export JSON for version control

### 3. Tune Alert Thresholds (30 min)

Based on observed metrics from test calls:
- Update alert rules in `monitoring/alerts/ai-engine.yml`
- Adjust thresholds to match actual performance
- Test alerts by simulating failures
- Verify alert annotations appear in Grafana

### 4. Document Findings

Create a test report:
- Observed latency ranges (p50/p95/p99)
- Provider comparison results
- Any issues or anomalies
- Recommended optimizations

---

## Quick Prometheus Queries

Test these in Prometheus UI (http://207.38.71.85:9090):

```promql
# Total calls started (all time)
sum(ai_agent_stream_started_total)

# Current active calls
count(ai_agent_streaming_active == 1)

# Call rate (last 5 min)
rate(ai_agent_stream_started_total[5m])

# Provider breakdown
sum by (provider) (ai_agent_stream_started_total)

# AudioSocket bytes received
rate(ai_agent_audiosocket_rx_bytes_total[1m])

# Memory usage
process_resident_memory_bytes{job="ai-engine"}
```

---

## Success Criteria

✅ **Dashboard working** if:
- All 6 panels render
- Metrics populate during/after calls
- No errors in browser console
- Time range and auto-refresh work
- Queries return expected data

✅ **System healthy** if:
- System Health stays green
- Memory usage is stable
- Call rate matches actual call volume
- Provider distribution is accurate
- No Prometheus target failures

---

## Ready to Test!

1. **Open dashboard**: http://207.38.71.85:3000
2. **Enable auto-refresh**: 10 seconds
3. **Make first call**: Dial your AI extension
4. **Watch metrics populate** in real-time
5. **Make 9 more calls**: Mix short and long
6. **Review results**: Check all panels have data

**Estimated time**: 15-30 minutes for complete test cycle

Good luck! 🎉
