# GA v4.0 Code Cleanup Checklist

**Purpose**: Remove dead code and unused configuration before production release  
**Timeline**: 1-2 hours  
**Impact**: Code cleanliness, no functional changes

---

## 1. Remove Dead Classes (src/engine.py)

### AudioFrameProcessor (lines 128-167)

**Status**: Defined but never instantiated or used  
**Evidence**: Only referenced in dict initialization `self.frame_processors: Dict[str, AudioFrameProcessor] = {}` but never populated

**Action**: Delete entire class definition

```python
# DELETE LINES 128-167
class AudioFrameProcessor:
    """Processes audio in 40ms frames to prevent voice queue backlog."""
    # ... entire class ...
```

**Also remove**:
- Line 350: `self.frame_processors: Dict[str, AudioFrameProcessor] = {}`

---

### VoiceActivityDetector (lines 168-195)

**Status**: Defined but never instantiated or used  
**Evidence**: Only referenced in dict initialization `self.vad_detectors: Dict[str, VoiceActivityDetector] = {}` but never populated

**Action**: Delete entire class definition

```python
# DELETE LINES 168-195
class VoiceActivityDetector:
    """Simple VAD to reduce unnecessary audio processing."""
    # ... entire class ...
```

**Also remove**:
- Line 351: `self.vad_detectors: Dict[str, VoiceActivityDetector] = {}`

---

## 2. Clean LLM Configuration

### src/config.py - LocalProviderConfig

**Current** (lines 48-54):
```python
class LocalProviderConfig(BaseModel):
    # ... other fields ...
    llm_model: Optional[str] = None  # ← REMOVE
    temperature: float = Field(default=0.8)  # ← REMOVE
```

**Issue**: 
- `llm_model` is NOT used (providers use their own model fields)
- `temperature` is NOT used at top level (only in provider-specific configs)

**Action**: Remove both fields

**Updated**:
```python
class LocalProviderConfig(BaseModel):
    enabled: bool = Field(default=False)
    ws_url: str = Field(default="ws://127.0.0.1:8765")
    response_timeout_sec: float = Field(default=5.0)
    chunk_ms: int = Field(default=200)
    stt_model: Optional[str] = None
    tts_voice: Optional[str] = None
    max_tokens: int = Field(default=150)
```

---

### config/ai-agent.yaml - Top-level llm section

**Current**:
```yaml
llm:
  model: gpt-4o-mini  # ← REMOVE
  temperature: 0.7     # ← REMOVE
  initial_greeting: "Hello! How can I assist you today?"
  prompt: |
    You are a helpful AI assistant...
```

**Issue**: 
- `model` is NOT referenced anywhere (providers have own model fields)
- `temperature` is NOT used at top level (only in provider-specific configs)

**Action**: Remove `model` and `temperature` keys

**Updated**:
```yaml
llm:
  initial_greeting: "Hello! How can I assist you today?"
  prompt: |
    You are a helpful AI assistant...
```

---

## 3. Remove Unused Config Field

### config/ai-agent.yaml - external_media.jitter_buffer_ms

**Current**:
```yaml
external_media:
  host: 0.0.0.0
  rtp_start_port: 10000
  rtp_end_port: 10100
  jitter_buffer_ms: 20  # ← REMOVE
```

**Issue**: 
- `jitter_buffer_ms` is defined in `ExternalMediaConfig` (src/config.py:178)
- BUT: Never consumed by RTP server (src/rtp_server.py)
- NOTE: `streaming.jitter_buffer_ms` IS used by StreamingPlaybackManager

**Action**: Delete the line

**Updated**:
```yaml
external_media:
  host: 0.0.0.0
  rtp_start_port: 10000
  rtp_end_port: 10100
```

**Also remove from src/config.py**:
```python
class ExternalMediaConfig(BaseModel):
    host: str = "0.0.0.0"
    rtp_start_port: int = 10000
    rtp_end_port: int = 10100
    # DELETE: jitter_buffer_ms: int = Field(default=20)
```

---

## 4. Convert Python Scripts to Shell

### Reason
Python version differences across systems cause compatibility issues. Shell scripts are universal.

### scripts/analyze_logs.py → scripts/analyze_logs.sh

**Current**: Python script with dependencies  
**Action**: Rewrite as shell script using standard tools (grep, awk, sed)

**Benefits**:
- No Python version dependency
- Works everywhere
- Faster startup

---

### scripts/model_setup.py → scripts/model_setup.sh

**Current**: Python script  
**Action**: Rewrite as shell script

**Note**: Keep Python version as `scripts/model_setup_legacy.py` for reference

---

## 5. Document CLI Tools

### README.md

**Add section**:
```markdown
## CLI Tools

Build the unified `agent` command:

```bash
cd cli/cmd/agent
go build -o agent
sudo mv agent /usr/local/bin/
```

**Available commands**:
- `agent doctor` - System health check
- `agent demo` - Demo functionality
- `agent init` - Initialize configuration
- `agent troubleshoot <call_id>` - Post-call analysis
- `agent version` - Show version

See `cli/` directory for details.
```

---

## Execution Plan

### Step 1: Remove Dead Code (15 min)
```bash
# Edit src/engine.py
# - Delete lines 128-167 (AudioFrameProcessor)
# - Delete lines 168-195 (VoiceActivityDetector)  
# - Delete line 350 (frame_processors dict)
# - Delete line 351 (vad_detectors dict)
```

### Step 2: Clean Config (15 min)
```bash
# Edit src/config.py
# - Remove llm_model from LocalProviderConfig
# - Remove temperature from LocalProviderConfig
# - Remove jitter_buffer_ms from ExternalMediaConfig

# Edit config/ai-agent.yaml
# - Remove llm.model
# - Remove llm.temperature
# - Remove external_media.jitter_buffer_ms
```

### Step 3: Convert Scripts (30-45 min)
```bash
# Create scripts/analyze_logs.sh (new shell version)
# Create scripts/model_setup.sh (new shell version)
# Rename originals to _legacy.py
```

### Step 4: Document CLI (15 min)
```bash
# Edit README.md - add CLI tools section
# Test build: cd cli/cmd/agent && go build
```

### Step 5: Test (15 min)
```bash
# Build containers
docker compose build

# Start engine
docker compose up -d ai-engine

# Check logs (no errors)
docker logs ai_engine | tail -50

# Make test call
# Verify functionality unchanged
```

### Step 6: Commit
```bash
git add .
git commit -m "chore: Production code cleanup for GA v4.0

Remove dead code:
- AudioFrameProcessor class (unused)
- VoiceActivityDetector class (unused)

Clean configuration:
- Remove unused llm.model and llm.temperature
- Remove unused external_media.jitter_buffer_ms

Convert scripts to shell:
- analyze_logs.py → analyze_logs.sh
- model_setup.py → model_setup.sh

Document CLI tools in README.md

No functional changes - cleanup only"

git push origin develop
```

---

## Validation Checklist

After cleanup:

- [ ] Engine starts without errors
- [ ] Pipelines initialize correctly
- [ ] Test call completes successfully
- [ ] No references to removed code
- [ ] Config loads without errors
- [ ] Shell scripts executable (`chmod +x`)
- [ ] CLI tools build successfully
- [ ] Documentation updated

---

## Safety Notes

**Safe to Remove**:
- ✅ AudioFrameProcessor - Never instantiated
- ✅ VoiceActivityDetector - Never used
- ✅ llm.model/temperature - Not referenced
- ✅ external_media.jitter_buffer_ms - Not consumed

**Do NOT Remove**:
- ❌ streaming.jitter_buffer_ms - USED by StreamingPlaybackManager
- ❌ provider-specific model/temperature - USED by providers

---

## Timeline

**Total**: 1.5-2 hours

- Remove dead code: 15 min
- Clean config: 15 min  
- Convert scripts: 45 min
- Document CLI: 15 min
- Test & commit: 15 min

---

## Post-Cleanup Benefits

1. **Cleaner codebase**: No dead code
2. **Clearer configuration**: Only used settings
3. **Better compatibility**: Shell scripts work everywhere
4. **Production ready**: Clean, professional release
5. **Maintainability**: Less confusion for future developers

---

**Status**: Ready to execute  
**Risk**: Low (no functional changes)  
**Impact**: Code quality improvement
