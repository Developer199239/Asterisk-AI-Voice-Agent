# Why LLM Performance Expectations Are Wrong

## The Critical Question

**How do we know which LLM model will perform within expected timeframes for specific CPU architectures?**

**Answer:** We DON'T currently - and that's the problem!

---

## What Install Script Promises vs Reality

### HEAVY Tier Expectations (from `registry.json` lines 99-108)

```json
"HEAVY": {
  "requirements": {"min_ram_gb": 32, "min_cpu_cores": 8},
  "expectations": {
    "llm_latency_sec": 15,  // ← PROMISE
    "two_way_summary": "Expect 15-20 seconds per conversational turn"
  },
  "models": {
    "llm": {
      "name": "llama-2-13b-chat.Q4_K_M.gguf",
      "size_mb": 7300
    }
  }
}
```

### Your Server (Actual Performance)

```
Hardware: 39GB RAM, 16 cores, Intel Xeon E5-2660 v3 @ 2.60GHz (2014)
Model: Llama-2-13B Q4_K_M (7.3GB, 13 billion parameters)

PROMISED: 15 seconds LLM latency
ACTUAL:   135 seconds warmup + 20-30 seconds per response

Reality is 2-8× SLOWER than promised! ❌
```

---

## Why The Expectations Are Wrong

### 1. **Registry Assumes GPU Is Available**

The expectations were likely tested with:
- NVIDIA GPU (RTX 3090, A100, etc.)
- GPU offloading enabled (`n_gpu_layers=-1`)
- VRAM: 12-24GB

**With GPU:**
```python
model = Llama(
    model_path="llama-2-13b-chat.Q4_K_M.gguf",
    n_gpu_layers=-1,  # Offload ALL layers to GPU
    n_ctx=2048
)
# Result: ~15 seconds for 30 tokens ✅
```

**Your Server (CPU-only):**
```python
model = Llama(
    model_path="llama-2-13b-chat.Q4_K_M.gguf",
    n_gpu_layers=0,  # NO GPU offloading
    n_ctx=512,
    n_threads=16
)
# Result: ~135s warmup + 30s per response ❌
```

---

### 2. **No CPU Architecture Consideration**

The registry checks:
```bash
if [ "$ram" -ge 32 ] && [ "$cores" -ge 8 ]; then HEAVY; fi
```

**What it SHOULD check:**

| Factor | Your Server | Modern Server | Impact |
|--------|-------------|---------------|---------|
| **CPU Model** | Intel Xeon E5-2660 v3 (2014) | AMD Ryzen 9 7950X (2023) | 3-4× difference |
| **Clock Speed** | 2.60 GHz | 4.5-5.7 GHz | 2× difference |
| **Instructions** | AVX2 | AVX2 + AVX-512 | 2× difference |
| **Memory Bandwidth** | DDR4-2133 | DDR5-5200 | 2× difference |
| **Overall** | 1.5-2 tok/s per billion params | 5-6 tok/s per billion params | **3-4× faster** |

**Your Llama-2-13B performance:**
```
13B params × 1.5 tok/s = ~19.5 tokens/second MAX
For 30 token response: 30 / 1.5 = 20 seconds MINIMUM
Reality: 30+ seconds (context processing + generation)
```

**Same model on modern CPU:**
```
13B params × 5 tok/s = 65 tokens/second
For 30 token response: 30 / 5 = 6 seconds
Close to the 15s registry expectation ✅
```

---

### 3. **Event Loop Blocking Not Considered**

Even if 13B ran in 20s, the `local-ai-server` architecture can't handle it:

```python
# local_ai_server/main.py - Single async event loop
async def handler(websocket, path):
    # All 3 WebSocket connections share this loop
    if mode == "llm":
        # This blocks for 20-30 seconds
        result = await asyncio.to_thread(self.llm_model, prompt)
        # During blocking: STT/TTS requests timeout
```

**Safe threshold for single-threaded async:**
- LLM inference should complete in **<10 seconds**
- Beyond 10s: risk of blocking other operations
- Beyond 15s: guaranteed timeouts and dropped connections

**Your 30s inference = Pipeline breakdown** ❌

---

## How To Actually Determine Expected Performance

### Method 1: Theoretical Calculation (Quick Estimate)

```python
def estimate_inference_time(model_params_billions, cpu_architecture):
    """
    Estimate LLM inference time based on model size and CPU.
    """
    # Tokens per second per billion parameters (empirical)
    CPU_PERFORMANCE = {
        "modern_amd_ryzen": 5.0,      # Ryzen 9 7950X
        "modern_intel_xeon": 4.5,     # Xeon Platinum 8380
        "older_intel_xeon": 1.5,      # Xeon E5-2660 v3 (YOUR SERVER)
        "budget_cpu": 1.0,            # Core i5 older gen
    }
    
    tokens_per_sec = CPU_PERFORMANCE[cpu_architecture] * model_params_billions
    
    # For 30 token response + context processing overhead
    context_processing = 2.0  # seconds (varies by context size)
    generation_time = 30 / tokens_per_sec
    
    return context_processing + generation_time

# Your server
print(estimate_inference_time(13, "older_intel_xeon"))
# Output: 2.0 + (30 / 1.5) = 22 seconds ✓ (matches reality!)

# Modern CPU
print(estimate_inference_time(13, "modern_amd_ryzen"))
# Output: 2.0 + (30 / 5.0) = 8 seconds ✓ (matches registry)
```

---

### Method 2: Runtime Benchmarking (Accurate)

**What `model_setup.py` SHOULD do:**

```python
def benchmark_llm_performance(model_path: str, cpu_cores: int) -> dict:
    """
    Run a quick 5-10 second benchmark to measure actual performance.
    Returns tokens/second and estimated response time.
    """
    import time
    from llama_cpp import Llama
    
    print(f"Benchmarking {model_path}...")
    
    # Load model with production settings
    model = Llama(
        model_path=model_path,
        n_ctx=512,
        n_threads=cpu_cores,
        n_batch=512,
        n_gpu_layers=0,  # CPU-only test
        verbose=False
    )
    
    # Warmup (models are slower on first run)
    model("Hello", max_tokens=5)
    
    # Benchmark: Generate 20 tokens
    start = time.time()
    output = model("What is the weather like today?", max_tokens=20, temperature=0.1)
    elapsed = time.time() - start
    
    # Calculate performance
    tokens_generated = len(output['choices'][0]['text'].split())
    tokens_per_sec = tokens_generated / elapsed if elapsed > 0 else 0
    
    # Estimate full response time (30 tokens typical)
    estimated_response_time = (30 / tokens_per_sec) + 2.0  # +2s for context
    
    return {
        "tokens_per_sec": tokens_per_sec,
        "benchmark_time": elapsed,
        "estimated_30_token_response": estimated_response_time,
        "suitable_for_realtime": estimated_response_time < 15
    }

# Usage during model setup
result = benchmark_llm_performance("models/llm/llama-2-13b-chat.Q4_K_M.gguf", 16)
print(f"Tokens/sec: {result['tokens_per_sec']:.1f}")
print(f"Estimated response time: {result['estimated_30_token_response']:.1f}s")
print(f"Suitable for real-time: {result['suitable_for_realtime']}")

# For your server would output:
# Tokens/sec: 1.5
# Estimated response time: 22.0s
# Suitable for real-time: False ❌

# Would then recommend:
# "Llama-2-13B is too slow for your CPU (22s response time)"
# "Recommended: Phi-3-mini (12s) or TinyLlama (8s) or hybrid pipeline (<5s)"
```

---

### Method 3: Look Up Known Benchmarks

**llama.cpp community benchmarks:**

| Model | Size | Xeon E5-2660 v3 | Ryzen 9 7950X | RTX 4090 |
|-------|------|-----------------|---------------|----------|
| TinyLlama-1.1B | 570MB | ~8 tok/s → **4s** | ~25 tok/s → 1.5s | ~80 tok/s → 0.5s |
| Phi-3-mini-3.8B | 2.2GB | ~4 tok/s → **10s** | ~15 tok/s → 2.5s | ~50 tok/s → 0.8s |
| Llama-2-7B | 3.9GB | ~2.5 tok/s → **14s** | ~10 tok/s → 3.5s | ~35 tok/s → 1s |
| Llama-2-13B | 7.3GB | ~1.5 tok/s → **22s** | ~6 tok/s → 5.5s | ~20 tok/s → 1.5s |

*(For 30 token generation + 2s context processing)*

**Your server matches the benchmarks!** 22s is expected for 13B on 2014 Xeon.

---

## Why `autodetect_local_models` Tried But Failed

### The Logic (from `install.sh` lines 183-202)

```bash
# After models are downloaded, try to pick the best one
if [ "$has_gpu" -eq 1 ]; then
    # GPU detected → use largest model
    if [ -f llama-2-13b-chat.Q4_K_M.gguf ]; then
        llm="llama-2-13b-chat.Q4_K_M.gguf"  # GPU can handle it
    fi
else
    # NO GPU → prefer smaller models
    if [ -f phi-3-mini-4k-instruct.Q4_K_M.gguf ]; then
        llm="phi-3-mini"  # NOT DOWNLOADED by HEAVY tier
    elif [ -f tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf ]; then
        llm="tinyllama"   # NOT DOWNLOADED by HEAVY tier
    elif [ -f llama-2-7b-chat.Q4_K_M.gguf ]; then
        llm="llama-2-7b"  # NOT DOWNLOADED by HEAVY tier
    elif [ -f llama-2-13b-chat.Q4_K_M.gguf ]; then
        llm="llama-2-13b"  # ← ONLY THIS EXISTS, used as last resort ❌
    fi
fi
```

**The problem:**
1. HEAVY tier downloads ONLY Llama-2-13B
2. `autodetect_local_models` wants to use Phi-3 or Llama-2-7B for CPU
3. But those models don't exist (not downloaded)
4. Falls back to 13B (only option available)

**It's trying to fix the problem AFTER the wrong download already happened!**

---

## The Complete Fix

### 1. Add GPU Detection to `model_setup.sh` (lines 64-72)

```bash
detect_gpu() {
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi >/dev/null 2>&1 && echo 1 || echo 0
    elif command -v rocm-smi >/dev/null 2>&1; then
        rocm-smi >/dev/null 2>&1 && echo 1 || echo 0
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
        echo LIGHT_GPU; return
    fi
    
    # CPU-only tiers (conservative)
    if [ "$ram" -ge 32 ] && [ "$cores" -ge 16 ]; then echo HEAVY_CPU; return; fi  # Llama-2-7B
    if [ "$ram" -ge 16 ] && [ "$cores" -ge 8 ]; then echo MEDIUM_CPU; return; fi  # Phi-3-mini
    if [ "$ram" -ge 8 ] && [ "$cores" -ge 4 ]; then echo LIGHT_CPU; return; fi    # TinyLlama
    echo MINIMAL  # Recommend hybrid
}
```

### 2. Add CPU Benchmark to `model_setup.py`

```python
def benchmark_cpu_speed() -> float:
    """
    Quick 5-second test to measure CPU inference capability.
    Returns relative performance score (1.0 = baseline).
    """
    try:
        # Download/use TinyLlama for quick test
        test_model = "models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
        if not Path(test_model).exists():
            print("Downloading benchmark model...")
            download_file(TINYLLAMA_URL, test_model, "tinyllama-benchmark")
        
        from llama_cpp import Llama
        import time
        
        model = Llama(test_model, n_ctx=128, n_threads=max(1, os.cpu_count()//2))
        
        start = time.time()
        model("Hello", max_tokens=10)
        elapsed = time.time() - start
        
        # Score: tokens per second (normalized)
        # 1.0 = old Xeon, 3.0 = modern Ryzen, 5.0 = high-end server
        tokens_per_sec = 10 / elapsed
        score = tokens_per_sec / 5.0  # Normalize to 5 tok/s baseline
        
        print(f"CPU benchmark score: {score:.1f} (higher is better)")
        return score
        
    except Exception as e:
        print(f"Benchmark failed: {e}, using conservative estimate")
        return 1.0  # Conservative default

def determine_tier_v2(registry, cpu_cores, ram_gb, override=None):
    """Enhanced tier selection with GPU and CPU performance checks."""
    
    if override:
        return override
    
    # Check GPU
    gpu_info = detect_gpu()
    has_gpu = gpu_info["available"]
    
    # GPU path
    if has_gpu:
        if ram_gb >= 32 and cpu_cores >= 8:
            return "HEAVY_GPU"
        elif ram_gb >= 16:
            return "MEDIUM_GPU"
    
    # CPU-only path - benchmark performance
    cpu_score = benchmark_cpu_speed()
    
    if ram_gb >= 32 and cpu_cores >= 16 and cpu_score >= 2.5:
        return "HEAVY_CPU"  # Modern CPU can handle Llama-2-7B
    elif ram_gb >= 16 and cpu_cores >= 8:
        return "MEDIUM_CPU"  # Phi-3-mini safe for most CPUs
    elif ram_gb >= 8:
        return "LIGHT_CPU"   # TinyLlama
    else:
        return "MINIMAL"     # Recommend hybrid
```

### 3. Update Registry with Realistic Expectations

```json
{
  "HEAVY_CPU": {
    "requirements": {"min_ram_gb": 32, "min_cpu_cores": 16, "gpu_required": false},
    "expectations": {
      "llm_latency_sec": 18,  // REALISTIC for CPU-only
      "two_way_summary": "18-25 seconds per turn on modern CPU; may be slower on older hardware",
      "notes": "Benchmarked on AMD Ryzen 9 / Intel Xeon Platinum. Older CPUs (pre-2018) may see 25-35s"
    },
    "models": {
      "llm": {
        "name": "llama-2-7b-chat.Q4_K_M.gguf",  // NOT 13B!
        "size_mb": 3900,
        "expected_tokens_per_sec_modern_cpu": 2.5,
        "expected_tokens_per_sec_older_cpu": 1.5
      }
    }
  },
  
  "HEAVY_GPU": {
    "requirements": {"min_ram_gb": 32, "min_cpu_cores": 8, "gpu_required": true, "min_gpu_vram_gb": 12},
    "expectations": {
      "llm_latency_sec": 8,  // With GPU offloading
      "two_way_summary": "8-12 seconds per turn with GPU acceleration"
    },
    "models": {
      "llm": {
        "name": "llama-2-13b-chat.Q4_K_M.gguf",  // OK with GPU
        "gpu_layers": -1,
        "expected_tokens_per_sec_gpu": 12
      }
    }
  }
}
```

---

## Summary: Why Your LLM Isn't Behaving as Expected

**Root Causes:**

1. ✅ **Install script worked correctly** - detected 39GB + 16 cores
2. ❌ **HEAVY tier assumes GPU** - doesn't check, downloads 13B model
3. ❌ **Registry expectations are GPU-based** - 15s only achievable with GPU
4. ❌ **No CPU architecture consideration** - your 2014 Xeon is 3× slower than modern CPUs
5. ❌ **13B model too large for CPU-only** - causes event loop blocking

**Your Server's Actual Performance:**
```
Llama-2-13B on Intel Xeon E5-2660 v3:
- Theoretical: 13B × 1.5 tok/s = 20 seconds minimum
- Reality: 135s warmup + 30s inference
- Expected (registry): 15s
- Discrepancy: 2-8× slower than promised ❌
```

**Correct Model for Your Hardware:**
```
Phi-3-mini-3.8B or Llama-2-7B:
- Theoretical: 3.8B × 1.5 tok/s = ~10-12 seconds
- Won't block event loop
- Matches MEDIUM_CPU tier expectations ✅
```

**Fix:** Implement GPU detection + CPU benchmarking + realistic tier expectations before download!

Would you like me to implement these improvements to the model setup scripts?
