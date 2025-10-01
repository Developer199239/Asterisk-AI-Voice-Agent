# How Install Script Uses Model Setup

## Complete Flow

### 1. Install Script (`install.sh` lines 302-320)

```bash
# When you run ./install.sh and choose "local" or "hybrid" profile
if [ "$PROFILE" = "local" ] || [ "$PROFILE" = "hybrid" ]; then
    read -p "Run local model setup now? [Y/n]: " do_models
    if [[ "$do_models" =~ ^[Yy]$|^$ ]]; then
        # Try 3 methods in order:
        
        # Method 1: Use Makefile target (if make available)
        if command -v make >/dev/null 2>&1; then
            make model-setup
        else
            # Method 2: Use host python3 directly
            if command -v python3 >/dev/null 2>&1; then
                python3 scripts/model_setup.py --assume-yes
            else
                # Method 3: Use containerized python
                docker-compose run --rm ai-engine python /app/scripts/model_setup.py --assume-yes
            fi
        fi
    fi
    
    # After download, auto-detect what was downloaded and set .env paths
    autodetect_local_models  # Lines 150-218
fi
```

---

### 2. Makefile Target (`Makefile` lines 72-82)

```makefile
model-setup:
    # Prefers bash version (faster, no Python dependency)
    if [ -f scripts/model_setup.sh ]; then
        bash scripts/model_setup.sh --assume-yes
    
    # Falls back to Python version
    elif command -v python3 >/dev/null 2>&1; then
        python3 scripts/model_setup.py --assume-yes
    
    # Last resort: containerized
    else
        docker-compose run --rm ai-engine bash /app/scripts/model_setup.sh --assume-yes
        # OR
        docker-compose run --rm ai-engine python /app/scripts/model_setup.py --assume-yes
    fi
```

---

### 3. Model Setup Scripts (TWO Implementations)

#### Option A: Bash Version (`scripts/model_setup.sh`)

**Simpler, no dependencies, used by default:**

```bash
#!/usr/bin/env bash

# Detection (lines 50-72)
cpu_cores=$(nproc || getconf _NPROCESSORS_ONLN)
ram_gb=$(awk '/MemTotal:/ { print $2/1024/1024 }' /proc/meminfo)

# Tier selection (lines 64-72)
select_tier() {
    if [ "$ram_gb" -ge 32 ] && [ "$cores" -ge 8 ]; then 
        echo HEAVY      # ← YOUR SERVER MATCHED THIS
    elif [ "$ram_gb" -ge 16 ] && [ "$cores" -ge 4 ]; then 
        echo MEDIUM
    else
        echo LIGHT
    fi
}

# Download logic (lines 126-140)
setup_heavy() {
    # STT: vosk-model-en-us-0.22
    curl -L https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip
    
    # LLM: Llama-2-13B (7.3GB) ← DOWNLOADED THIS
    curl -L https://huggingface.co/.../llama-2-13b-chat.Q4_K_M.gguf
    
    # TTS: en_US-lessac-high.onnx
    curl -L https://huggingface.co/.../en_US-lessac-high.onnx
}
```

**Result:** Llama-2-13B downloaded for HEAVY tier

---

#### Option B: Python Version (`scripts/model_setup.py`)

**More sophisticated, uses `registry.json`:**

```python
# Detection (lines 59-94)
cpu_cores = os.cpu_count()
ram_gb = psutil.virtual_memory().total / (1024**3)

# Tier selection (lines 110-130)
def determine_tier(registry, cpu_cores, ram_gb):
    # Selects HIGHEST tier where requirements are met
    selected = None
    for name, info in tiers.items():
        min_ram = info['requirements']['min_ram_gb']
        min_cpu = info['requirements']['min_cpu_cores']
        
        if ram_gb >= min_ram and cpu_cores >= min_cpu:
            selected = name  # Keeps updating to higher tier
    
    return selected  # Returns HEAVY for 39GB + 16 cores

# Downloads from registry.json (lines 174-208)
def download_models_for_tier(tier_info, models_dir):
    llm = tier_info['models']['llm']
    url = llm['url']  # From registry.json
    dest = llm['dest_path']
    
    download_file(url, dest, llm['name'])
```

**Result:** Same as bash - Llama-2-13B for HEAVY tier

---

### 4. After Download: Auto-Detection (`install.sh` lines 150-218)

```bash
autodetect_local_models() {
    # Scans models/ directory for downloaded files
    # Preference order for LLM:
    
    if [ "$has_gpu" -eq 1 ]; then
        # GPU detected → prefer larger models
        if [ -f models/llm/llama-2-13b-chat.Q4_K_M.gguf ]; then
            llm="/app/models/llm/llama-2-13b-chat.Q4_K_M.gguf"  ← SET THIS
        elif [ -f models/llm/llama-2-7b-chat.Q4_K_M.gguf ]; then
            llm="/app/models/llm/llama-2-7b-chat.Q4_K_M.gguf"
        fi
    else
        # NO GPU → prefer smaller models
        if [ -f models/llm/phi-3-mini-4k-instruct.Q4_K_M.gguf ]; then
            llm="/app/models/llm/phi-3-mini-4k-instruct.Q4_K_M.gguf"
        elif [ -f models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf ]; then
            llm="/app/models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
        elif [ -f models/llm/llama-2-7b-chat.Q4_K_M.gguf ]; then
            llm="/app/models/llm/llama-2-7b-chat.Q4_K_M.gguf"
        elif [ -f models/llm/llama-2-13b-chat.Q4_K_M.gguf ]; then  ← FOUND THIS
            llm="/app/models/llm/llama-2-13b-chat.Q4_K_M.gguf"    ← USED AS LAST RESORT
        fi
    fi
    
    # Write to .env
    echo "LOCAL_LLM_MODEL_PATH=$llm" >> .env
}
```

---

## What Actually Happened on Your Server

### Timeline:

```
1. You ran: ./install.sh
2. Selected: "local" or "hybrid" profile
3. Confirmed: "Run local model setup? Y"

4. Script detected:
   - CPU cores: 16
   - RAM: 39GB
   - GPU: Not detected (has_gpu=0)

5. Tier selected: HEAVY
   - Meets: 32GB+ RAM ✅
   - Meets: 8+ cores ✅
   - Assumption: GPU available (WRONG ❌)

6. Downloaded:
   - STT: vosk-model-en-us-0.22 (1.8GB)
   - LLM: llama-2-13b-chat.Q4_K_M.gguf (7.3GB)
   - TTS: en_US-lessac-high.onnx (120MB)

7. autodetect_local_models ran:
   - No GPU detected (has_gpu=0)
   - Checked for phi-3-mini: NOT FOUND
   - Checked for tinyllama: NOT FOUND  
   - Checked for llama-2-7b: NOT FOUND
   - Found: llama-2-13b-chat ✓ (last resort)
   - Set: LOCAL_LLM_MODEL_PATH=/app/models/llm/llama-2-13b-chat.Q4_K_M.gguf

8. Result:
   - HEAVY tier model on MEDIUM tier hardware
   - 135s warmup, 30s+ inference
   - Event loop blocked ❌
```

---

## The Logic Gap

### What's Missing:

1. **Bash version has NO GPU detection:**
   ```bash
   # Lines 64-72 in model_setup.sh
   if [ "$ram" -ge 32 ] && [ "$cores" -ge 8 ]; then 
       echo HEAVY  # Assumes GPU available!
   fi
   ```

2. **Python version has NO GPU detection:**
   ```python
   # Lines 110-130 in model_setup.py
   if ram_gb >= 32 and cpu_cores >= 8:
       return "HEAVY"  # Assumes GPU available!
   ```

3. **autodetect_local_models tries to compensate:**
   ```bash
   # Line 173: has_gpu check
   if nvidia-smi >/dev/null 2>&1; then has_gpu=1; fi
   
   # Lines 183-202: Prefer smaller models if NO GPU
   # BUT Llama-2-13B was already downloaded!
   ```

---

## The Fix Needed

### Short-term (Your Server):
```bash
# Switch to appropriate model
./fix-local-pipeline-mvp.sh  # TinyLlama for MVP
# OR
# Use what MEDIUM tier would have downloaded
LOCAL_LLM_MODEL_PATH=/app/models/llm/llama-2-7b-chat.Q4_K_M.gguf
```

### Long-term (Codebase):

**1. Update both model setup scripts to detect GPU:**

```bash
# scripts/model_setup.sh - Add GPU detection
detect_gpu() {
    if nvidia-smi >/dev/null 2>&1 || rocm-smi >/dev/null 2>&1; then
        echo 1
    else
        echo 0
    fi
}

select_tier() {
    local cores ram gpu
    cores=$(cpu_cores)
    ram=$(ram_gb)
    gpu=$(detect_gpu)
    
    if [ -n "$TIER_OVERRIDE" ]; then echo "$TIER_OVERRIDE"; return; fi
    
    # GPU-accelerated tiers
    if [ "$gpu" -eq 1 ]; then
        if [ "$ram" -ge 32 ] && [ "$cores" -ge 8 ]; then echo HEAVY_GPU; return; fi
        if [ "$ram" -ge 16 ] && [ "$cores" -ge 4 ]; then echo MEDIUM_GPU; return; fi
    fi
    
    # CPU-only tiers (conservative)
    if [ "$ram" -ge 32 ] && [ "$cores" -ge 16 ]; then echo HEAVY_CPU; return; fi
    if [ "$ram" -ge 16 ] && [ "$cores" -ge 8 ]; then echo MEDIUM_CPU; return; fi
    echo LIGHT_CPU
}

setup_medium_cpu() {
    # LLM: Phi-3-mini (3.8B) - better than Llama-2-7B for CPU
    download "..." "$MODELS_DIR/llm/phi-3-mini-4k-instruct.Q4_K_M.gguf" "..."
}

setup_heavy_cpu() {
    # LLM: Llama-2-7B (NOT 13B!) for CPU-only
    download "..." "$MODELS_DIR/llm/llama-2-7b-chat.Q4_K_M.gguf" "..."
}
```

**2. Update registry.json with CPU vs GPU tiers** (see MODEL-SELECTION-ANALYSIS.md)

**3. Add warnings during install:**
```bash
echo "⚠️  WARNING: HEAVY tier detected but NO GPU found"
echo "   Llama-2-13B requires GPU for 15s inference"
echo "   On CPU-only, expect 30-40s per turn (may block pipeline)"
echo "   Recommendation: Use MEDIUM tier (Phi-3-mini) or hybrid pipeline"
```

---

## Summary

**Yes, install.sh IS using model_setup:**
- ✅ It calls `make model-setup` OR `python3 scripts/model_setup.py`
- ✅ Model setup correctly detected your 39GB RAM + 16 cores
- ✅ Downloaded models successfully

**But the logic is flawed:**
- ❌ HEAVY tier assumes GPU available (doesn't check)
- ❌ Llama-2-13B downloaded for CPU-only hardware
- ❌ autodetect_local_models tries to compensate but too late
- ❌ Result: Wrong model for your hardware

**Solution:** Implement GPU detection and split tiers into CPU/GPU variants as detailed in `MODEL-SELECTION-ANALYSIS.md`.
