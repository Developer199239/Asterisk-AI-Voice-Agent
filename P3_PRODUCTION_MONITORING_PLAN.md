# P3 - Production Monitoring & Observability Plan

## Executive Summary

**Goal**: Deploy production-grade monitoring infrastructure to observe, measure, and optimize the AI voice agent at scale.

**Status**: 🔨 **PLANNING**  
**Duration**: 1 week  
**Priority**: HIGH (recommended next milestone)

**Current State**:
- ✅ Extensive Prometheus metrics already instrumented (~50+ metrics)
- ✅ Health endpoints exposed on port 15000 (/health, /metrics, /ready, /live)
- ✅ Basic prometheus.yml config exists
- ⏳ No Grafana dashboards
- ⏳ No alerting rules
- ⏳ No persistent metrics storage
- ⏳ No call quality scoring

---

## 1. Current Instrumentation Audit

### Existing Prometheus Metrics (50+ metrics)

**Streaming**: 16 metrics (active, bytes, underflows, latency, jitter buffer)  
**VAD**: 3 metrics (frames, confidence, threshold)  
**Providers**: 8 metrics (sample rates, alignment, ACK latency)  
**AudioSocket**: 3 metrics (connections, rx/tx bytes)  
**Conversation**: 4 metrics (gating, capture, state, barge-in)  
**Latency**: 3 histograms (STT→TTS, turn response, barge-in)  
**Config**: 5 metrics (exposure of runtime config)  
**Audio Quality**: 4 metrics (RMS, DC offset, codec alignment)

**Key Metrics Examples**:
```
ai_agent_turn_response_seconds{pipeline,provider}     # Histogram
ai_agent_stream_underflow_events_total{call_id}       # Counter
ai_agent_streaming_jitter_buffer_depth{call_id}       # Gauge
ai_agent_codec_alignment{call_id,provider}            # Gauge
ai_agent_barge_in_events_total{call_id}               # Counter
```

---

## 2. Architecture

```
Production Server (voiprnd.nemtclouddispatch.com)
┌─────────────────────────────────────────┐
│  ai_engine :15000/metrics               │
│  ↓ scrape every 1s                      │
│  Prometheus :9090 (30d retention)       │
│  ↓ PromQL                                │
│  Grafana :3000 (dashboards + alerts)    │
└─────────────────────────────────────────┘
```

---

## 3. Implementation Plan

### **Phase 1: Prometheus Setup (Day 1)**

#### Tasks:
1. Create `monitoring/alerts/ai-engine.yml` with alert rules
2. Update `monitoring/prometheus.yml` with scrape config
3. Create `docker-compose.monitoring.yml`
4. Deploy Prometheus container
5. Validate scraping from ai_engine:15000

#### Alert Rules (10 critical alerts):
- HighTurnResponseLatency (p95 > 2s)
- CriticalTurnResponseLatency (p95 > 5s)
- HighUnderflowRate (> 5/sec)
- StreamingFallbacksFrequent
- AudioSocketConnectionLoss
- ProviderCodecMismatch
- SlowBargeInReaction
- VADConfidenceLow
- JitterBufferUnderrun
- HealthEndpointDown

**Deliverable**: Prometheus running, scraping metrics, alerts configured

---

### **Phase 2: Grafana Dashboards (Day 2-3)**

#### Dashboard 1: System Overview
- Active calls (gauge)
- Call rate (calls/min)
- Provider distribution (pie)
- Health status (stat)
- Audio transport mode

#### Dashboard 2: Call Quality
- Turn response latency (p50/p95/p99)
- STT→TTS latency (p50/p95/p99)
- Barge-in reaction time
- Audio underflows (rate)
- Streaming fallbacks (count)
- Jitter buffer depth (heatmap)

#### Dashboard 3: Provider Performance
- Deepgram: sample rates, ACK latency, codec alignment
- OpenAI Realtime: rate alignment, measured vs expected
- Provider comparison (side-by-side)
- Cost per call (manual tracking)

#### Dashboard 4: Audio Quality
- RMS levels (by stage)
- DC offset
- Bytes tx/rx (rate)
- Codec alignment status
- VAD confidence distribution

#### Dashboard 5: Conversation Flow
- Conversation state timeline
- TTS gating active
- Audio capture enabled
- Barge-in events (rate)
- Config values (thresholds, timeouts)

**Deliverable**: 5 Grafana dashboards, auto-provisioned

---

### **Phase 3: Call Quality Scoring (Day 4)**

#### Quality Score Algorithm

**Score**: 0-100 per call

**Factors**:
- Turn response latency (30 points max penalty)
- Underflow count (20 points max penalty)
- Fallback count (15 points max penalty)
- Barge-in reaction (15 points max penalty)
- Codec alignment (10 points max penalty)
- RMS consistency (10 points max penalty)

**Thresholds**:
- **Excellent** (90-100): p95 latency < 1s, no underflows
- **Good** (75-89): p95 latency < 2s, few underflows
- **Fair** (60-74): p95 latency < 3s, some underflows
- **Poor** (< 60): p95 latency > 3s, frequent issues

**Implementation**:
- Python script: `scripts/calculate_quality_score.py`
- Reads Prometheus metrics via API
- Exports scores as new metric: `ai_agent_call_quality_score{call_id}`
- Runs every 30 seconds

**Deliverable**: Quality scores available in Grafana

---

### **Phase 4: Real Call Validation (Day 5-6)**

#### Test Matrix

| Provider | Duration | Scenario | Expected Quality |
|----------|----------|----------|------------------|
| Deepgram | 30s | Simple Q&A | > 90 |
| Deepgram | 60s | Complex conversation | > 85 |
| OpenAI Realtime | 30s | Simple Q&A | > 90 |
| OpenAI Realtime | 60s | Complex conversation | > 85 |
| Deepgram | 30s | Noisy background | > 75 |
| OpenAI Realtime | 30s | Barge-in test | > 80 |

#### Validation Steps:
1. Place 10-20 test calls (mix of providers)
2. Monitor dashboards in real-time
3. Collect quality scores
4. Run `agent troubleshoot` on each call
5. Compare metrics to golden baseline
6. Document any regressions
7. Tune alert thresholds based on real data

**Deliverable**: Test report with quality scores and recommendations

---

### **Phase 5: Documentation & Handoff (Day 7)**

#### Documentation Updates:

1. **Monitoring Guide** (`docs/Monitoring-Guide.md`)
   - Dashboard overview
   - Alert descriptions
   - Troubleshooting workflows
   - Quality score interpretation

2. **Operator's Manual** (`docs/Operators-Manual.md`)
   - Daily health checks
   - Alert response procedures
   - Escalation paths
   - Common issues and fixes

3. **Runbook** (`docs/Runbook.md`)
   - Alert → Diagnosis → Fix workflows
   - Example: "HighTurnResponseLatency" → check provider status → restart if needed

4. **ROADMAPv4 Update**
   - Mark P3 complete
   - Add metrics baseline
   - Document quality thresholds

**Deliverable**: Complete documentation suite

---

## 4. Deliverables Checklist

### Phase 1: Prometheus
- [ ] `monitoring/alerts/ai-engine.yml` (10 alert rules)
- [ ] `monitoring/prometheus.yml` (updated config)
- [ ] `docker-compose.monitoring.yml`
- [ ] Prometheus container running
- [ ] Metrics scraped successfully

### Phase 2: Grafana
- [ ] Dashboard 1: System Overview
- [ ] Dashboard 2: Call Quality
- [ ] Dashboard 3: Provider Performance
- [ ] Dashboard 4: Audio Quality
- [ ] Dashboard 5: Conversation Flow
- [ ] Auto-provisioning configured

### Phase 3: Quality Scoring
- [ ] `scripts/calculate_quality_score.py`
- [ ] Quality scores exposed as Prometheus metric
- [ ] Quality panel in dashboards

### Phase 4: Validation
- [ ] 20 test calls completed
- [ ] Quality scores collected
- [ ] Test report written
- [ ] Alert thresholds tuned

### Phase 5: Documentation
- [ ] Monitoring Guide
- [ ] Operator's Manual
- [ ] Runbook
- [ ] ROADMAPv4 updated

---

## 5. Success Criteria

**Technical**:
- ✅ Prometheus scraping all 50+ metrics
- ✅ 5 Grafana dashboards deployed
- ✅ 10 alert rules configured
- ✅ Quality scoring operational
- ✅ 30 days metric retention

**Operational**:
- ✅ Operator can diagnose call issues in < 2 minutes using dashboards
- ✅ Alerts fire correctly for degraded performance
- ✅ Quality scores correlate with user experience
- ✅ Documentation enables self-service troubleshooting

**Performance Baselines** (from 20 test calls):
- Turn response p95 < 1.5s (target)
- Underflow rate < 2/call (target)
- Barge-in reaction p95 < 0.5s (target)
- Quality score > 85 average (target)

---

## 6. Files to Create

```
monitoring/
├── alerts/
│   └── ai-engine.yml           # NEW: Alert rules
├── grafana/
│   ├── provisioning/
│   │   ├── dashboards/
│   │   │   └── dashboard.yml   # NEW: Auto-provisioning
│   │   └── datasources/
│   │       └── prometheus.yml  # NEW: Datasource config
│   └── dashboards/
│       ├── system-overview.json      # NEW
│       ├── call-quality.json         # NEW
│       ├── provider-performance.json # NEW
│       ├── audio-quality.json        # NEW
│       └── conversation-flow.json    # NEW
└── prometheus.yml              # UPDATE: Add alert_rules

docker-compose.monitoring.yml   # NEW: Monitoring stack

scripts/
└── calculate_quality_score.py # NEW: Quality scoring

docs/
├── Monitoring-Guide.md         # NEW
├── Operators-Manual.md         # NEW
└── Runbook.md                  # NEW
```

---

## 7. Timeline & Milestones

**Day 1**: Prometheus + Alerts ✅  
**Day 2-3**: Grafana Dashboards ✅  
**Day 4**: Quality Scoring ✅  
**Day 5-6**: Real Call Validation ✅  
**Day 7**: Documentation ✅  

**Total: 7 days (1 week)**

---

## 8. Post-P3 Benefits

**For Operators**:
- Real-time visibility into system health
- Proactive alerting before users complain
- Self-service troubleshooting
- Quality trends over time

**For Development**:
- Data-driven optimization decisions
- Regression detection
- Provider comparison metrics
- A/B testing capability

**For Business**:
- Quality metrics for SLAs
- Cost per call tracking
- Capacity planning data
- Customer satisfaction correlation

---

## 9. Next Steps After P3

**Option A: Optimization Sprint**
- Use monitoring data to identify bottlenecks
- Tune parameters based on real metrics
- Reduce p95 latency by 20%

**Option B: Advanced Features**
- Multi-language support
- Function calling
- Load testing at scale

**Option C: Production Scale-Out**
- Deploy to multiple regions
- Load balancing
- Auto-scaling

---

## 10. Questions for Discussion

1. **Prometheus retention**: 30 days local or remote write to long-term storage?
2. **Alert channels**: Email, Slack, PagerDuty, or webhook?
3. **Dashboard access**: Public dashboards or auth-protected?
4. **Quality thresholds**: Adjust targets based on business requirements?
5. **Cost tracking**: Manual or integrate with billing APIs?

---

## Appendix: Sample Queries

### Call Quality Report (Last 24h)
```promql
# Average turn response latency
avg(rate(ai_agent_turn_response_seconds_sum[24h])) / avg(rate(ai_agent_turn_response_seconds_count[24h]))

# Total underflows
sum(increase(ai_agent_stream_underflow_events_total[24h]))

# Provider distribution
sum by (provider) (increase(ai_agent_stream_started_total[24h]))
```

### Real-Time Call Monitoring
```promql
# Active calls
count(ai_agent_streaming_active == 1)

# Current jitter buffer depth
ai_agent_streaming_jitter_buffer_depth

# Recent barge-in events
sum(increase(ai_agent_barge_in_events_total[1m]))
```

### Provider Performance Comparison
```promql
# Turn response latency by provider
histogram_quantile(0.95, sum by (provider, le) (rate(ai_agent_turn_response_seconds_bucket[5m])))
```
