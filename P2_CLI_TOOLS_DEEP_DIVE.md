# P2 CLI Tools - Comprehensive Design & Implementation Plan

**Date**: October 26, 2025  
**Milestone**: P2 - Config Cleanup + CLI UX  
**Status**: 📋 **PLANNING** - Pre-implementation analysis

---

## Executive Summary

### Goal

Create three unified CLI tools to improve operator experience:
1. **`agent init`** - Interactive setup wizard (zero-to-call in 10min)
2. **`agent doctor`** - Health check & diagnostics (auto-detect issues)
3. **`agent demo`** - Audio pipeline validation (test without real call)

### Why These Tools?

**Current Pain Points**:
- First setup takes 30+ minutes (should be < 10min)
- Debugging requires deep Asterisk knowledge
- Tools scattered across Makefile + 20+ Python scripts
- No guided troubleshooting
- No cross-platform binary

**P2 Improvements**:
- ✅ Single binary (no "install dependencies")
- ✅ Interactive workflows
- ✅ Auto-detection and auto-fix
- ✅ Cross-platform (Linux, macOS, Windows WSL2)
- ✅ Backward compatible with existing Makefile

---

## Proposed CLI Tools

### 1. `agent init` - Interactive Setup Wizard

**Purpose**: Guide new users from zero to first call in <10 minutes

**What it does**:
```bash
$ agent init

🚀 Asterisk AI Voice Agent - Setup Wizard

Step 1/6: Environment Detection
  ✅ Docker detected
  ✅ Docker Compose detected
  
Step 2/6: Provider Selection
  Which AI provider?
  [1] Deepgram
  [2] OpenAI Realtime  ← Recommended
  [3] Local (TinyLlama)
  Choice: 2

Step 3/6: API Keys
  OpenAI API key: sk-proj-...
  ✅ Validated (tier-2)

Step 4/6: Audio Profile
  Profile: openai_realtime_24k (recommended)
  ✅ Configured

Step 5/6: Asterisk Dialplan
  Add this to extensions_custom.conf:
  
  [from-ai-agent-openai]
  exten => s,1,Set(AI_PROVIDER=openai_realtime)
   same => n,Set(AI_AUDIO_PROFILE=openai_realtime_24k)
   same => n,Stasis(asterisk-ai-voice-agent)

Step 6/6: Generating Config
  ✅ Created .env
  ✅ Created config/ai-agent.yaml (v4)
  
🎉 Setup complete! Next: docker-compose up -d
```

**Key Features**:
- Interactive prompts with smart defaults
- API key validation (test before saving)
- Profile recommendations based on provider
- Asterisk auto-detection
- Minimal config generation
- Validates at end

---

### 2. `agent doctor` - Health Check & Diagnostics

**Purpose**: Comprehensive system validation and troubleshooting

**What it does**:
```bash
$ agent doctor

🩺 Health Check

[1/12] Docker...                  ✅
[2/12] Containers...              ✅
[3/12] Asterisk ARI...            ✅
[4/12] AudioSocket...             ⚠️  Port 8090 not listening
[5/12] Dialplan...                ✅
[6/12] Configuration...           ✅
[7/12] Provider Keys...           ❌ OPENAI_API_KEY invalid
[8/12] Audio Pipeline...          ✅
[9/12] Network...                 ✅
[10/12] Media Directory...        ✅
[11/12] Logs...                   ⚠️  3 warnings
[12/12] Recent Calls...           ✅

📊 HEALTH: 38/40 checks passed, 2 warnings, 0 failures

Recommendations:
  1. Fix OPENAI_API_KEY: run 'agent init --reconfigure'
  2. Restart AudioSocket: docker-compose restart ai-engine

Run 'agent doctor --fix' to auto-fix issues
```

**Key Features**:
- 12 comprehensive check categories
- Color-coded output (✅ ⚠️ ❌)
- Actionable recommendations
- Auto-fix mode (`--fix`)
- JSON output for CI/CD
- Exit codes (0=healthy, 1=warnings, 2=errors)

---

### 3. `agent demo` - Audio Pipeline Validator

**Purpose**: Test audio end-to-end without making a real call

**What it does**:
```bash
$ agent demo

🎵 Audio Demo

Step 1/5: Preparing...
  ✅ Test audio loaded (1kHz tone, 2s)
  
Step 2/5: Creating Loopback...
  ✅ AudioSocket channel originated
  
Step 3/5: Playback...
  [====================>] 100%
  ✅ 100/100 frames sent
  
Step 4/5: Quality Analysis...
  ✅ RMS: 8124 (expected: 8000, 1.5% diff)
  ✅ SNR: 68.2 dB (excellent)
  ✅ Frequency: 1001 Hz (0.1% diff)
  ✅ No clipping
  
Step 5/5: Cleanup...
  ✅ Channel hungup

🎉 AUDIO DEMO PASSED
  Format: PCM16 @ 8kHz
  Latency: 23ms
  Quality: 68.2 dB SNR
```

**Key Features**:
- Reference audio (1kHz sine, 8kHz PCM16)
- AudioSocket loopback (no AI provider needed)
- Real-time progress visualization
- Quality metrics (RMS, SNR, frequency, clipping)
- Latency measurement
- Options: `--profile`, `--duration`, `--audio custom.wav`

---

## Cross-Platform Architecture

### Why Go + Python Bridge?

**Go Binary**:
- ✅ Single binary (no runtime deps)
- ✅ Cross-compilation (Linux/macOS/Windows)
- ✅ Fast startup (<100ms vs Python ~500ms)
- ✅ Easy distribution (curl | bash)
- ✅ Rich CLI libs (cobra, viper, bubbletea)

**Python Bridge**:
- ✅ Leverage existing 20+ scripts
- ✅ Python ecosystem (PyYAML, requests)
- ✅ Gradual migration
- ✅ Operator familiarity

### Installation

**Recommended**:
```bash
curl -fsSL https://get.asterisk-ai-agent.dev/install.sh | bash
```

**Package Managers**:
```bash
# Homebrew (macOS/Linux)
brew install asterisk-ai-voice-agent/tap/agent

# apt (Ubuntu/Debian)
sudo apt install agent

# Manual
curl -LO https://.../agent-linux-amd64
chmod +x agent-linux-amd64
sudo mv agent-linux-amd64 /usr/local/bin/agent
```

### Platform Support

| Feature | Linux | macOS | Windows (WSL2) |
|---------|-------|-------|----------------|
| **Binary format** | ELF | Mach-O | ELF (WSL) |
| **Asterisk** | Native + Docker | Docker only | Docker only |
| **Docker socket** | `/var/run/docker.sock` | `~/.docker/run/` | `/var/run/` |
| **Audio devices** | ALSA/Pulse | CoreAudio | Limited |
| **Dialplan edit** | Auto | Manual | Manual |

---

## Implementation Plan

### Phase 1: Core Framework (Week 1)

**Goals**:
- Go CLI skeleton with Cobra
- Cross-compilation working
- Basic subcommands (init/doctor/demo)
- Config loading (Viper)

**Deliverables**:
```
cli/
├── cmd/agent/
│   ├── main.go
│   ├── init.go
│   ├── doctor.go
│   └── demo.go
├── internal/
│   ├── config/
│   ├── docker/
│   ├── asterisk/
│   └── ui/
└── go.mod
```

**Acceptance**: `agent --help` works on all platforms

### Phase 2: `agent init` (Week 1-2)

**Priority**:
1. Environment detection
2. Provider selection
3. API key validation
4. Config generation
5. Dialplan snippets
6. Final validation

### Phase 3: `agent doctor` (Week 2)

**Priority**:
1. Docker checks
2. Asterisk checks
3. Config validation
4. Provider checks
5. Audio pipeline checks
6. Auto-fix mode

### Phase 4: `agent demo` (Week 3)

**Priority**:
1. Reference audio
2. AudioSocket loopback
3. Playback/recording
4. Quality analysis
5. Progress UI

### Phase 5: Integration (Week 4)

**Tasks**:
- Update Makefile
- Write docs
- Create install scripts
- CI/CD for releases
- Migration guide

---

## User Workflows

### Workflow 1: New User Setup

```bash
$ curl -fsSL https://get.../install.sh | bash
$ agent init          # 5 minutes
$ docker-compose up -d
$ agent doctor        # ✅ All pass
$ agent demo          # ✅ Audio works
$ # Make first call   # 🎉 Success!

# Total: ~10 minutes (vs 30+ min currently)
```

### Workflow 2: Troubleshooting

```bash
$ agent doctor
#   ❌ OpenAI API key invalid
#   ❌ AudioSocket not listening

$ agent init --reconfigure
$ docker-compose restart ai-engine
$ agent doctor        # ✅ Fixed
$ agent demo          # ✅ Works
```

### Workflow 3: Provider Switch

```bash
$ agent init --provider openai_realtime
$ docker-compose restart ai-engine
$ agent doctor        # ✅ Configured
$ agent demo --profile openai_realtime_24k  # ✅ Works
```

### Workflow 4: CI/CD

```bash
# In GitHub Actions
agent doctor --json > health.json
[ $? -eq 0 ] || exit 1

agent demo --profile telephony_responsive
[ $? -eq 0 ] || exit 1
```

---

## Technical Stack

### Go Dependencies

```go
github.com/spf13/cobra v1.8.0           // CLI framework
github.com/spf13/viper v1.18.0          // Config
github.com/docker/docker v24.0.7        // Docker API
github.com/charmbracelet/bubbletea      // TUI
gopkg.in/yaml.v3 v3.0.1                 // YAML
github.com/fatih/color v1.16.0          // Colors
```

### Build System

```makefile
# Makefile targets
cli-build:          # Build for current OS
cli-build-all:      # Cross-compile all platforms
cli-test:           # Run Go tests
cli-install:        # Install to /usr/local/bin
```

---

## Integration with Existing Tools

### Makefile Integration

```makefile
# New targets
agent-init:
	agent init

agent-check:
	agent doctor

agent-test:
	agent demo

# Wrapper for backward compatibility
doctor: agent-check
demo: agent-test
```

### Python Script Bridge

**CLI calls Python when needed**:
```go
// internal/python/bridge.go
func AnalyzeLogs(logPath string) error {
    cmd := exec.Command("python3", 
        "scripts/analyze_logs.py", logPath)
    return cmd.Run()
}
```

**Gradual migration**:
- Phase 1: Go CLI calls Python scripts
- Phase 2: Rewrite critical scripts in Go
- Phase 3: Python optional (pure Go fallback)

---

## Risk Analysis

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Cross-platform bugs | Medium | High | Extensive testing on all OS |
| Docker API changes | Low | Medium | Version pinning, tests |
| Python bridge issues | Medium | Low | Fallback to direct script calls |
| Performance issues | Low | Medium | Benchmark, optimize hot paths |

### User Adoption Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Learning curve | Medium | Medium | Excellent docs, videos |
| Existing workflow disruption | High | Low | Backward compatible |
| Installation friction | Low | High | Multiple install methods |

---

## Success Metrics

| Metric | Current | P2 Target | How to Measure |
|--------|---------|-----------|----------------|
| **Setup time** | 30+ min | < 10 min | User testing |
| **Debug time** | 15+ min | < 5 min | Scenario testing |
| **Platform support** | Linux only | Linux/macOS/WSL2 | Test matrix |
| **Tool discovery** | Low | High | User feedback |
| **Error resolution** | Manual | Auto | agent doctor --fix |

---

## Open Questions

### 1. Binary Distribution Strategy

**Options**:
- A) GitHub Releases only
- B) Package managers (brew, apt, yum)
- C) Custom repo + install script
- **Recommended**: C (most flexible)

### 2. Python Bridge Scope

**What to rewrite in Go?**
- Critical path: Config validation, health checks → Go
- Analysis tools: Log analysis, audio quality → Keep Python
- **Recommended**: Hybrid approach

### 3. Backward Compatibility

**How long to support old Makefile targets?**
- A) Forever (wrappers)
- B) 1 major version
- C) Immediate deprecation
- **Recommended**: A (no breaking changes)

### 4. TUI vs CLI

**Should agent demo be interactive TUI?**
- Pros: Beautiful, real-time updates
- Cons: SSH sessions, scripting issues
- **Recommended**: CLI with optional TUI mode (`--tui`)

### 5. Config Migration

**Auto-migrate old configs?**
- agent init detects old config
- Offers to migrate
- Backs up original
- **Recommended**: Yes, with explicit consent

---

## Next Steps

### Decision Points

1. **Approve approach**: Go binary + Python bridge?
2. **Prioritize tools**: Start with agent doctor or agent init?
3. **Distribution**: GitHub Releases or package managers?
4. **Timeline**: 4-week sprint realistic?

### Before Implementation

1. Review this deep-dive document
2. Test Go toolchain setup
3. Prototype one command (agent doctor) for validation
4. Get user feedback on mockups

### After Approval

1. Week 1: Core framework + agent doctor prototype
2. Week 2: Complete agent doctor + start agent init
3. Week 3: Complete agent init + start agent demo
4. Week 4: Complete agent demo + integration + docs

---

**Status**: ⏸️ **AWAITING APPROVAL**  
**Next**: Review & decide on implementation approach
