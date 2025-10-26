# agent troubleshoot - AI-Powered Post-Call Analysis

**Date**: October 26, 2025  
**Type**: P2 CLI Tool (4th tool)  
**Status**: 📋 **DESIGN PHASE**

---

## Executive Summary

### Purpose

**Automated post-call RCA with AI-powered analysis and actionable recommendations.**

`agent troubleshoot` combines:
1. Data collection (like `rca_collect.sh`)
2. Automated analysis (parsing logs, metrics, audio)
3. **LLM-powered insights** (GPT-4/Claude to analyze patterns)
4. Actionable recommendations (step-by-step fixes)

### Key Difference from `agent doctor`

| Feature | `agent doctor` | `agent troubleshoot` |
|---------|----------------|----------------------|
| **When** | Pre-call / anytime | Post-call (after issue) |
| **Focus** | System health | Call-specific RCA |
| **Data** | Live system state | Historical call data |
| **Analysis** | Rule-based checks | LLM-powered insights |
| **Output** | Health status | Root cause + fix steps |

### User Value

**Before** (manual RCA):
```bash
$ make rca-collect              # 2 min to collect
$ grep "ERROR" logs/*.log       # 10 min analyzing
$ compare metrics manually      # 15 min
$ read documentation           # 20 min
$ try random fixes             # 30+ min
Total: ~77 minutes
```

**After** (agent troubleshoot):
```bash
$ agent troubleshoot 1761505357.2187
# Collects, analyzes, diagnoses in ~3 minutes
# Provides: Root cause + fix steps + confidence score
Total: ~3 minutes to diagnosis
```

---

## Core Features

### 1. Smart Data Collection

**What to collect**:
- ✅ Container logs (ai_engine, local-ai-server)
- ✅ Audio taps (if enabled)
- ✅ Call recordings (if available)
- ✅ Metrics snapshots
- ✅ Configuration files
- ✅ Provider API logs (Deepgram/OpenAI)
- ✅ Timeline events

**Smart detection**:
```bash
# If taps not enabled:
$ agent troubleshoot --call-id 123

⚠️  Audio taps not enabled. Enable for better analysis?
  [Y/n]: Y
  
✅ Updated config/ai-agent.yaml (diagnostics.audio_taps: true)
ℹ️  Restart ai-engine for changes: docker-compose restart ai-engine
ℹ️  Next call will have taps. For this call, analyzing without taps.
```

### 2. Automated Analysis

**Analysis pipeline**:
1. **Parse logs** → Extract events, errors, warnings
2. **Audio quality** → SNR, clipping, drift, underflows
3. **Timeline reconstruction** → Event sequence
4. **Pattern detection** → Known issues (wrong profile, gating, etc.)
5. **Metrics correlation** → Find anomalies
6. **Provider logs** → API errors, latency spikes

### 3. LLM-Powered Insights

**How it works**:
```
┌─────────────────────────────────────┐
│  agent troubleshoot                 │
└───────────┬─────────────────────────┘
            │
            v
┌─────────────────────────────────────┐
│  1. Collect RCA data                │
│     - Logs, taps, metrics           │
└───────────┬─────────────────────────┘
            │
            v
┌─────────────────────────────────────┐
│  2. Extract key indicators          │
│     - Errors, warnings, metrics     │
│     - Audio quality stats           │
│     - Timeline events               │
└───────────┬─────────────────────────┘
            │
            v
┌─────────────────────────────────────┐
│  3. Build LLM prompt                │
│     - Structured context            │
│     - Known issue patterns          │
│     - System configuration          │
└───────────┬─────────────────────────┘
            │
            v
┌─────────────────────────────────────┐
│  4. LLM Analysis (GPT-4/Claude)     │
│     - Root cause identification     │
│     - Similar case matching         │
│     - Fix recommendations           │
└───────────┬─────────────────────────┘
            │
            v
┌─────────────────────────────────────┐
│  5. Generate Report                 │
│     - Root cause (confidence %)     │
│     - Step-by-step fixes            │
│     - Prevention tips               │
└─────────────────────────────────────┘
```

**LLM Prompt Structure**:
```markdown
# Call Analysis Request

## System Context
- Provider: OpenAI Realtime
- Profile: openai_realtime_24k
- Duration: 124.8s
- Outcome: Completed

## Issue Description
User reported: "Audio was clipping"

## Key Indicators
- Drift: -52% (CRITICAL - expected < 30%)
- Gate closures: 94 (HIGH - expected < 5)
- Buffering events: 94 (HIGH - expected 0)
- SNR: 64.2 dB (GOOD)

## Errors (5 critical, 12 warnings)
[ERROR] Late provider ACK (1200ms delay)
[ERROR] Jitter buffer underflow (264 events)
[WARN] Audio gate fluttering (50+ toggles)

## Timeline
18:46:00 - Call start
18:46:05 - First audio chunk
18:46:47 - Playback interrupted (gate closed)
... (truncated)

## Configuration
idle_cutoff_ms: 800 (telephony_ulaw_8k profile)
webrtc_aggressiveness: 1
audio_gating: enabled

## Similar Cases
- P1_POST_FIX_RCA.md: Wrong profile used (telephony vs openai_realtime)
- OPENAI_GOLDEN_BASELINE.md: webrtc_aggressiveness=0 caused gate fluttering

Based on this data, identify:
1. Root cause (with confidence %)
2. Contributing factors
3. Step-by-step fix
4. Prevention strategy
```

### 4. Structured Output

**Report format**:
```bash
$ agent troubleshoot 1761505357.2187

🔍 AI-Powered Call Analysis
═══════════════════════════════════════

Call ID: 1761505357.2187
Duration: 124.8s
Provider: OpenAI Realtime
Status: Completed with issues

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 ROOT CAUSE (95% confidence)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Wrong audio profile used for OpenAI Realtime

Analysis:
  • Profile: telephony_ulaw_8k (idle_cutoff_ms: 800)
  • Should be: openai_realtime_24k (idle_cutoff_ms: 0)
  
Evidence:
  ✓ Drift -52% indicates streaming starvation
  ✓ 94 gate closures suggests idle timeout conflicts
  ✓ 94 buffering events matches gate closure count
  ✓ Similar to P1_POST_FIX_RCA.md case

Impact:
  • Audio accumulated during idle_cutoff wait
  • Playback bursts at end causing clipping
  • User experience: choppy, incomplete responses

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 FIX STEPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1: Update Dialplan
  Location: /etc/asterisk/extensions_custom.conf
  
  Change:
    - Set(AI_AUDIO_PROFILE=telephony_ulaw_8k)
    + Set(AI_AUDIO_PROFILE=openai_realtime_24k)
  
  Or run: agent init --provider openai_realtime

Step 2: Restart AI Engine
  $ docker-compose restart ai-engine

Step 3: Validate Configuration
  $ agent doctor
  # Should show: Profile 'openai_realtime_24k' active

Step 4: Test Audio Pipeline
  $ agent demo --profile openai_realtime_24k
  # Should show: Drift < 20%, no underflows

Step 5: Make Test Call
  # Monitor with: agent troubleshoot --watch

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🛡️  PREVENTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Always set AI_AUDIO_PROFILE explicitly in dialplan
2. Use 'agent doctor' before first call
3. Enable audio taps for better diagnostics:
   diagnostics.audio_taps: true
4. Review golden baselines:
   - OPENAI_REALTIME_P1_FINAL_RCA.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 ANALYSIS DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Contributing Factors:
  • Dialplan used default profile (telephony_responsive)
  • Context mapping not configured
  • No validation before call

What Went Right:
  ✓ Audio gating working correctly
  ✓ VAD configured properly
  ✓ Provider connection stable
  ✓ SNR quality excellent (64.2 dB)

Metrics Summary:
  Audio Quality:   [████████░░] 8/10 (SNR good, but drift high)
  Config Correct:  [███░░░░░░░] 3/10 (wrong profile)
  System Health:   [█████████░] 9/10 (no infrastructure issues)
  
Overall Score: 67/100 (Needs configuration fix)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💾 RCA ARTIFACTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Saved to: logs/remote/rca-20251026-190606/

Files:
  • ai-engine.log (2.4 MB)
  • analysis-report.md
  • llm-analysis.json
  • metrics-summary.json
  • timeline.json
  • audio-quality.json

Commands:
  View full logs:    less logs/remote/rca-*/ai-engine.log
  Replay timeline:   cat logs/remote/rca-*/timeline.json | jq
  Check audio:       cat logs/remote/rca-*/audio-quality.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Need help? Run: agent doctor --fix
Next: Apply fix and test with: agent demo
```

---

## Implementation Strategy

### Option 1: Go + LLM API (Recommended)

**Architecture**:
```
agent troubleshoot (Go)
    │
    ├─> Data Collection (Go)
    │   └─> Calls rca_collect.sh
    │
    ├─> Analysis Pipeline (Go)
    │   ├─> Log parser
    │   ├─> Metrics extractor
    │   ├─> Audio analyzer
    │   └─> Timeline builder
    │
    ├─> LLM Integration (Go)
    │   ├─> Prompt builder
    │   ├─> API client (OpenAI/Claude/Local)
    │   └─> Response parser
    │
    └─> Report Generator (Go)
        ├─> Markdown output
        ├─> JSON output
        └─> Interactive TUI
```

**Pros**:
- ✅ Consistent with other CLI tools
- ✅ Single binary distribution
- ✅ Fast execution
- ✅ Easy API integration

**Cons**:
- ⚠️ Need to rewrite some Python analysis logic

### Option 2: Python Script + LLM API

**Architecture**:
```
agent troubleshoot (Go wrapper)
    │
    └─> scripts/agent_troubleshoot.py (Python)
        ├─> Uses existing rca_collect.sh
        ├─> Uses existing analysis scripts
        └─> LLM API integration (simple)
```

**Pros**:
- ✅ Leverage existing Python scripts
- ✅ Faster initial development
- ✅ Rich Python ecosystem

**Cons**:
- ❌ Requires Python runtime
- ❌ Slower execution
- ❌ Dependency management

### Option 3: Hybrid (Recommended for P2)

**Best of both worlds**:
```
agent troubleshoot (Go CLI)
    │
    ├─> Data Collection
    │   └─> Shell exec: bash scripts/rca_collect.sh
    │
    ├─> Basic Analysis (Go)
    │   ├─> Parse logs (grep, regex)
    │   ├─> Extract metrics (JSON parsing)
    │   └─> Audio stats (from wav_quality_analyzer.py)
    │
    ├─> LLM Analysis (Go)
    │   ├─> Build structured prompt
    │   ├─> Call OpenAI/Claude/Local API
    │   └─> Parse response
    │
    └─> Report Generation (Go)
```

**Why Hybrid?**:
- ✅ Reuse battle-tested rca_collect.sh
- ✅ Go for LLM integration and reporting
- ✅ Single binary distribution
- ✅ Fast development (don't rewrite everything)
- ✅ Gradual migration path

---

## Detailed Workflows

### Workflow 1: Basic Usage (Most Common)

```bash
# User reports: "Call had bad audio quality"

$ agent troubleshoot

🔍 Recent calls:
  [1] 1761505357.2187 - 2 min ago - OpenAI - 124.8s - Completed ⚠️
  [2] 1761504353.2179 - 10 min ago - Deepgram - 43s - Completed ✅
  [3] 1761503254.2175 - 20 min ago - OpenAI - 95s - Completed ✅

Select call to analyze [1-3]: 1

📦 Collecting RCA data...
  ✅ Container logs (2.4 MB)
  ⚠️  Audio taps not enabled
  ✅ Call recordings found
  ✅ Metrics snapshot
  ✅ Config files

⚠️  Audio taps disabled. Enable for better analysis?
  [Y/n]: Y
  
✅ Updated config (taps enabled for next call)

📊 Analyzing call 1761505357.2187...
  ✅ Parsed 12,450 log events
  ✅ Extracted 234 metrics
  ✅ Analyzed audio quality
  ✅ Built timeline (45 events)

🤖 AI Analysis (GPT-4)...
  ✅ Analyzed patterns
  ✅ Matched similar cases
  ✅ Generated recommendations

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 ROOT CAUSE (95% confidence)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Wrong audio profile used for OpenAI Realtime
[... detailed report ...]

💾 Saved to: logs/remote/rca-20251026-190606/
```

### Workflow 2: Specific Call ID

```bash
$ agent troubleshoot --call-id 1761505357.2187

# Or shorthand
$ agent troubleshoot 1761505357.2187

# Skips selection, goes directly to analysis
```

### Workflow 3: Watch Mode (Real-Time)

```bash
$ agent troubleshoot --watch

🔍 Watching for new calls...
  Press Ctrl+C to stop

[19:06:45] New call detected: 1761505555.2190
           Provider: OpenAI Realtime
           Status: In progress...
           
[19:07:12] Call ended (27s)
           Analyzing...
           
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Call 1761505555.2190 Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ No issues detected
   - SNR: 68.2 dB (excellent)
   - Drift: -8.4% (good)
   - No errors or warnings

[19:08:20] New call detected: 1761505600.2195
           ...
```

### Workflow 4: Batch Analysis (Multiple Calls)

```bash
$ agent troubleshoot --last 5

🔍 Analyzing last 5 calls...

Call 1: 1761505357.2187 - ❌ Issues found
Call 2: 1761504353.2179 - ✅ Healthy
Call 3: 1761503254.2175 - ✅ Healthy
Call 4: 1761502156.2170 - ⚠️  Minor warnings
Call 5: 1761501034.2165 - ✅ Healthy

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Aggregate Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Success Rate: 80% (4/5 calls healthy)
Common Issues:
  1. Wrong profile (1 call)
  2. Low audio energy (1 call)

Recommendations:
  • Set AI_AUDIO_PROFILE explicitly in dialplan
  • Check microphone gain settings
```

### Workflow 5: Export for Sharing

```bash
$ agent troubleshoot 1761505357.2187 --export report.zip

✅ Exported analysis to: report.zip

Contents:
  • analysis-report.md (human-readable)
  • llm-analysis.json (machine-readable)
  • logs/ (sanitized, no sensitive data)
  • metrics/
  • timeline.json

Share with: support, team, GitHub issues
```

---

## LLM Integration Details

### Supported LLM Providers

**1. OpenAI (GPT-4)**
```yaml
llm:
  provider: openai
  model: gpt-4-turbo-preview
  api_key: ${OPENAI_API_KEY}
  max_tokens: 4000
  temperature: 0.2  # Lower = more deterministic
```

**2. Anthropic (Claude)**
```yaml
llm:
  provider: anthropic
  model: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}
  max_tokens: 4000
```

**3. Local (Ollama)**
```yaml
llm:
  provider: ollama
  model: mistral:7b-instruct
  endpoint: http://localhost:11434
  # No API key needed
```

**4. Disabled (Rule-Based Only)**
```yaml
llm:
  enabled: false
  # Falls back to pattern matching only
```

### Prompt Engineering

**Structured prompt with examples**:
```python
SYSTEM_PROMPT = """
You are an expert Asterisk/VoIP engineer specializing in AI voice agents.

Your task: Analyze call data and identify root causes.

Output format (JSON):
{
  "root_cause": "Brief description",
  "confidence": 95,
  "evidence": ["point 1", "point 2"],
  "contributing_factors": ["factor 1"],
  "fix_steps": [
    {"step": 1, "action": "...", "command": "..."},
    ...
  ],
  "prevention": ["tip 1", "tip 2"]
}

Known issue patterns:
- Wrong profile: idle_cutoff_ms mismatch → drift > 40%
- Gate fluttering: webrtc_aggressiveness too low → gate closures > 20
- Provider latency: STT finalization > 2s → Deepgram Voice Agent
- Audio accumulation: buffering events = gate closures

Be specific. Reference documentation when possible.
"""

USER_PROMPT = """
Call Analysis Request:

SYSTEM CONTEXT:
{system_config}

ISSUE:
{user_description}

KEY INDICATORS:
{metrics_summary}

ERRORS:
{error_log}

TIMELINE:
{event_timeline}

SIMILAR CASES:
{similar_cases}

Analyze and provide root cause with fix steps.
"""
```

### Context Window Management

**Challenge**: Call logs can be 100K+ lines

**Solution**: Intelligent sampling
1. Extract critical errors/warnings (top 50)
2. Key metrics snapshots (every 10s)
3. Timeline milestones (10-20 events)
4. First/last 100 lines of logs
5. Similar case summaries (max 3)

**Total context**: ~8K tokens (fits in GPT-4 context window)

### Cost Management

**Estimated costs**:
- GPT-4 Turbo: ~$0.02 per analysis
- Claude 3.5 Sonnet: ~$0.015 per analysis
- Local (Ollama): $0 (but slower, less accurate)

**Budget controls**:
```yaml
llm:
  daily_limit: 100  # Max 100 analyses/day
  cost_cap: 5.00    # Max $5/day
  fallback_to_rules: true  # If limit hit, use rules
```

**Cache similar analyses**:
- Hash: call_metrics + error_pattern
- TTL: 24 hours
- Saves ~70% of API calls

---

## Technical Implementation

### Data Collection Phase

**Reuse rca_collect.sh**:
```go
// internal/troubleshoot/collector.go
func CollectRCA(callID string) (*RCAData, error) {
    // Call existing bash script
    cmd := exec.Command("bash", "scripts/rca_collect.sh")
    cmd.Env = append(os.Environ(),
        fmt.Sprintf("CALL_ID=%s", callID),
        "SINCE_MIN=60",
    )
    
    output, err := cmd.CombinedOutput()
    if err != nil {
        return nil, fmt.Errorf("rca_collect failed: %w", err)
    }
    
    // Parse RCA_BASE from output
    base := extractRCABase(string(output))
    
    // Load collected data
    return loadRCAData(base)
}
```

### Analysis Phase

**Extract key indicators**:
```go
// internal/troubleshoot/analyzer.go
type CallAnalysis struct {
    CallID       string
    Duration     float64
    Provider     string
    Profile      string
    
    // Metrics
    SNR          float64
    Drift        float64
    Underflows   int
    GateClosures int
    BufferEvents int
    
    // Errors
    CriticalErrors []LogEvent
    Warnings       []LogEvent
    
    // Timeline
    Events []TimelineEvent
}

func AnalyzeCall(data *RCAData) (*CallAnalysis, error) {
    analysis := &CallAnalysis{}
    
    // Parse logs
    analysis.CriticalErrors = parseErrors(data.Logs)
    analysis.Warnings = parseWarnings(data.Logs)
    
    // Extract metrics
    analysis.SNR = extractMetric(data, "snr_db")
    analysis.Drift = extractMetric(data, "drift_pct")
    
    // Build timeline
    analysis.Events = buildTimeline(data.Logs)
    
    return analysis, nil
}
```

### LLM Integration

**API client**:
```go
// internal/troubleshoot/llm.go
type LLMClient interface {
    Analyze(ctx context.Context, prompt string) (*LLMResponse, error)
}

type OpenAIClient struct {
    APIKey string
    Model  string
}

func (c *OpenAIClient) Analyze(ctx context.Context, prompt string) (*LLMResponse, error) {
    req := openai.ChatCompletionRequest{
        Model: c.Model,
        Messages: []openai.Message{
            {Role: "system", Content: SYSTEM_PROMPT},
            {Role: "user", Content: prompt},
        },
        Temperature: 0.2,
        MaxTokens:   4000,
    }
    
    resp, err := c.client.CreateChatCompletion(ctx, req)
    if err != nil {
        return nil, err
    }
    
    // Parse JSON response
    return parseResponse(resp.Choices[0].Message.Content)
}
```

### Report Generation

**Markdown + JSON output**:
```go
// internal/troubleshoot/reporter.go
func GenerateReport(analysis *CallAnalysis, llm *LLMResponse) error {
    // Markdown for humans
    md := formatMarkdown(analysis, llm)
    ioutil.WriteFile("analysis-report.md", []byte(md), 0644)
    
    // JSON for machines
    json := formatJSON(analysis, llm)
    ioutil.WriteFile("llm-analysis.json", []byte(json), 0644)
    
    // Interactive TUI
    if tui.Enabled() {
        renderTUI(analysis, llm)
    }
    
    return nil
}
```

---

## Configuration

### Config Schema

```yaml
# config/ai-agent.yaml

troubleshooting:
  enabled: true
  
  # LLM configuration
  llm:
    provider: openai  # openai | anthropic | ollama | disabled
    model: gpt-4-turbo-preview
    api_key_env: OPENAI_API_KEY  # Read from env var
    temperature: 0.2
    max_tokens: 4000
    
    # Cost controls
    daily_limit: 100
    cost_cap: 5.00
    fallback_to_rules: true
    
    # Caching
    cache_enabled: true
    cache_ttl_hours: 24
  
  # Data collection
  collection:
    auto_enable_taps: prompt  # always | prompt | never
    include_recordings: true
    include_provider_logs: true
    retention_days: 30
  
  # Analysis
  analysis:
    similarity_threshold: 0.85  # For matching similar cases
    confidence_threshold: 70    # Min confidence to show recommendations
    
  # Known issue patterns (fallback when LLM disabled)
  patterns:
    - name: wrong_profile
      condition: "drift > 40 && buffering > 50"
      cause: "Wrong audio profile for provider"
      fix: "Update dialplan: Set(AI_AUDIO_PROFILE=...)"
      
    - name: gate_fluttering
      condition: "gate_closures > 20"
      cause: "webrtc_aggressiveness too sensitive"
      fix: "Set webrtc_aggressiveness: 1 in config"
```

### CLI Flags

```bash
agent troubleshoot [flags] [call-id]

Flags:
  -c, --call-id string       Call ID to analyze
  -l, --last int            Analyze last N calls (default: 1)
  -w, --watch               Watch for new calls and auto-analyze
  -v, --verbose             Verbose output
      --no-llm              Disable LLM analysis (rules only)
      --llm-provider string Provider: openai|anthropic|ollama
      --export string       Export analysis to file/zip
      --format string       Output format: text|json|markdown
      --enable-taps         Enable audio taps before analysis
  -h, --help                Help for troubleshoot
```

---

## Integration Points

### 1. With `agent doctor`

```bash
# doctor finds live issues
$ agent doctor
  ❌ Last call failed

# troubleshoot analyzes why
$ agent troubleshoot --last 1
  🎯 ROOT CAUSE: Wrong profile
```

### 2. With `agent demo`

```bash
# demo tests audio pipeline
$ agent demo
  ⚠️  Drift 45% (high)

# troubleshoot explains why
$ agent troubleshoot --call-id demo-12345
  🎯 ROOT CAUSE: Profile mismatch
```

### 3. With Makefile

```makefile
## troubleshoot: Analyze most recent call
troubleshoot:
	agent troubleshoot --last 1

## troubleshoot-watch: Monitor calls in real-time
troubleshoot-watch:
	agent troubleshoot --watch
```

---

## Implementation Phases

### Phase 1: Core (Week 1-2)
- ✅ Data collection (reuse rca_collect.sh)
- ✅ Basic analysis (parse logs, metrics)
- ✅ Rule-based diagnosis (no LLM)
- ✅ CLI interface

### Phase 2: LLM Integration (Week 2-3)
- ✅ OpenAI integration
- ✅ Prompt engineering
- ✅ Response parsing
- ✅ Cost controls

### Phase 3: Polish (Week 3-4)
- ✅ Report generation (MD, JSON, TUI)
- ✅ Cache similar analyses
- ✅ Watch mode
- ✅ Batch analysis

### Phase 4: Advanced (Post-P2)
- ⏳ Anthropic/Ollama support
- ⏳ Historical trend analysis
- ⏳ Automated fix application
- ⏳ Integration with monitoring (Prometheus)

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Time to diagnosis** | < 5 min | User feedback |
| **Accuracy** | > 85% | Root cause correct |
| **LLM cost** | < $0.05/call | API billing |
| **User adoption** | 60% of issues | Usage logs |
| **Fix success rate** | > 90% | Follow-up calls healthy |

---

## Open Questions

### 1. LLM Provider Selection

**Which should be default?**
- A) OpenAI GPT-4 (best quality, $$$)
- B) Claude 3.5 Sonnet (good quality, $$)
- C) Ollama Local (free, slower/less accurate)
- **Recommendation**: A (OpenAI), with config option

### 2. Auto-Enable Taps

**When taps disabled, should we?**
- A) Always prompt to enable
- B) Auto-enable without asking
- C) Analyze without taps (degraded mode)
- **Recommendation**: A (prompt), with `--auto-enable-taps` flag

### 3. Privacy & Data Sharing

**What data goes to LLM?**
- ✅ Include: Metrics, errors, timeline
- ⚠️ Sanitize: Call IDs, phone numbers
- ❌ Exclude: API keys, passwords, PII
- **Recommendation**: Explicit sanitization function

### 4. Offline Mode

**Should it work without LLM?**
- Yes - fallback to rule-based patterns
- Store 10-20 common patterns
- Lower confidence scores (50-70%)
- **Recommendation**: Yes, with clear indication

---

## Next Steps

### Decision Points

1. **Approve approach**: Hybrid Go + rca_collect.sh?
2. **LLM provider**: OpenAI GPT-4 as default?
3. **Timeline**: 3-4 weeks realistic?
4. **Priority**: Build after or parallel with init/doctor/demo?

### Before Implementation

1. Review this design document
2. Test LLM prompt with sample data
3. Estimate API costs for your usage
4. Get user feedback on report format

### After Approval

1. Week 1-2: Core data collection + analysis
2. Week 2-3: LLM integration
3. Week 3-4: Polish + documentation
4. Week 4: User testing + iteration

---

**Status**: ⏸️ **AWAITING APPROVAL**  
**Recommendation**: **Implement after `agent doctor`** (Week 2-3 of P2)  
**Effort**: 2-3 weeks  
**Value**: 🔥 **HIGH** - Automates most painful debugging task
