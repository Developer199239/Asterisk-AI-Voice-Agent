# Model Selection Logic Analysis & Improvements

## Current Installation Logic

### How Model Selection Works Today

#### Step 1: Tier Detection (`model_setup.py` lines 110-130)

```python
def determine_tier(registry, cpu_cores, ram_gb, override=None):
    # Selects HIGHEST tier whose requirements are met
    selected = None
    for name, info in tiers.items():
        min_ram = requirements.get("min_ram_gb", 0)
        min_cpu = requirements.get("min_cpu_cores", 0)
        if ram_gb >= min_ram and cpu_cores >= min_cpu:
            selected = name  # Keeps updating to higher tiers
    return selected
```

**Your Server (39GB RAM, 16 cores):**
```
LIGHT:  4GB+ RAM,  2+ cores → ✅ Qualified
MEDIUM: 16GB+ RAM, 4+ cores → ✅ Qualified  
HEAVY:  32GB+ RAM, 8+ cores → ✅ Qualified → SELECTED (highest)
```

#### Step 2: Model Assignment (from `registry.json`)

```json
"HEAVY": {
  "llm": {
    "name": "llama-2-13b-chat.Q4_K_M.gguf",
    "size_mb": 7300
  },
  "expectations": {
    "llm_latency_sec": 15,  ← WRONG for CPU-only
    "two_way_summary": "15-20 seconds per turn"
  }
}
```

---

## The Problem

### Issue 1: No GPU Detection in Tier Selection

**Current:** Tiers based ONLY on RAM + CPU cores  
**Reality:** Llama-2-13B needs GPU for 15s inference

**Your Server:**
- ✅ 39GB RAM (meets HEAVY)
- ✅ 16 cores (meets HEAVY)
- ❌ **NO GPU** (doesn't meet HEAVY performance expectations)

**Result:** HEAVY tier chosen → Llama-2-13B downloaded → 135s warmup + 30s inference ❌

---

### Issue 2: CPU Architecture Not Considered

**Intel Xeon E5-2660 v3 @ 2.60GHz** (your server):
- Released: 2014
- AVX2: Yes (basic)
- AVX-512: No
- Performance: ~1.5-2 tokens/sec per billion parameters

**Modern CPUs (e.g., AMD Ryzen 9 7950X):**
- AVX2: Enhanced
- AVX-512: Yes  
- Performance: ~4-6 tokens/sec per billion parameters

**Impact:**
```
Llama-2-13B on your server:  13B × 1.5 tok/s = ~20s for 30 tokens
Llama-2-13B on modern CPU:   13B × 5 tok/s   = ~6s for 30 tokens
```

---

### Issue 3: Single-Threaded Async Blocking

**The `local-ai-server` architecture:**
```python
# One async event loop handles ALL WebSocket connections
async def handler(websocket):
    if mode == "llm":
        result = await asyncio.to_thread(llm_model, prompt)  # Blocks for 20-30s
        # During this time: STT/TTS requests pile up, timeouts occur
```

**Problem:** Long-running LLM inference blocks the event loop, causing:
- STT empty transcripts
- TTS requests dropped
- WebSocket timeouts

**Safe threshold:** LLM inference should complete in <10s to avoid blocking

---

## Improved Model Selection Strategy

### Proposal: Multi-Factor Tier System

```python
# New detection logic
def determine_tier_v2(cpu_cores, ram_gb, gpu_available, cpu_benchmark_score):
    """
    Determine appropriate tier based on:
    1. GPU availability (most important for LLM)
    2. CPU performance (not just core count)
    3. RAM capacity
    4. Architecture considerations (event loop blocking)
    """
    
    # GPU-accelerated path
    if gpu_available and gpu_memory_gb >= 8:
        if ram_gb >= 32 and cpu_cores >= 8:
            return "HEAVY_GPU"      # Llama-2-13B + GPU → 5-10s inference
        elif ram_gb >= 16:
            return "MEDIUM_GPU"     # Llama-2-7B + GPU → 3-6s inference
    
    # CPU-only path (your server)
    else:
        # Check if CPU is modern enough for larger models
        cpu_score = benchmark_cpu_inference()  # Quick 1s test
        
        if ram_gb >= 32 and cpu_cores >= 16 and cpu_score > 5.0:
            return "HEAVY_CPU"      # Llama-2-7B (NOT 13B!)
        elif ram_gb >= 16 and cpu_cores >= 8 and cpu_score > 3.0:
            return "MEDIUM_CPU"     # Phi-3-mini or Llama-2-7B
        elif ram_gb >= 8 and cpu_cores >= 4:
            return "LIGHT_CPU"      # TinyLlama
        else:
            return "MINIMAL"        # Cloud-only (hybrid)
    
    return "LIGHT_CPU"  # Conservative default
```

---

## Recommended Registry Update

### New Tier Definitions

```json
{
  "tiers": {
    "MINIMAL": {
      "description": "<8GB RAM or <4 cores; use hybrid pipeline",
      "requirements": {"min_ram_gb": 2, "min_cpu_cores": 1, "gpu_required": false},
      "expectations": {
        "recommendation": "Use hybrid_support pipeline (local STT + cloud LLM/TTS)",
        "two_way_summary": "Cloud LLM provides <5s responses"
      },
      "models": {
        "stt": {"name": "vosk-model-small-en-us-0.15"},
        "llm": null,
        "tts": null
      }
    },
    
    "LIGHT_CPU": {
      "description": "8-16GB RAM, 4+ cores, NO GPU; basic offline capability",
      "requirements": {"min_ram_gb": 8, "min_cpu_cores": 4, "gpu_required": false},
      "expectations": {
        "stt_latency_sec": 2,
        "llm_latency_sec": 8,
        "tts_latency_sec": 3,
        "two_way_summary": "10-15 seconds per turn; functional MVP",
        "recommended_concurrent_calls": 1
      },
      "models": {
        "stt": {"name": "vosk-model-small-en-us-0.15"},
        "llm": {
          "name": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
          "size_mb": 570,
          "params_billions": 1.1,
          "expected_tokens_per_sec": 8
        },
        "tts": {"name": "en_US-lessac-medium.onnx"}
      }
    },
    
    "MEDIUM_CPU": {
      "description": "16-32GB RAM, 8+ cores, NO GPU; balanced offline",
      "requirements": {"min_ram_gb": 16, "min_cpu_cores": 8, "gpu_required": false},
      "cpu_benchmark_threshold": 3.0,
      "expectations": {
        "stt_latency_sec": 2,
        "llm_latency_sec": 12,
        "tts_latency_sec": 3,
        "two_way_summary": "15-20 seconds per turn; production-viable",
        "recommended_concurrent_calls": 2
      },
      "models": {
        "stt": {"name": "vosk-model-en-us-0.22"},
        "llm": {
          "name": "phi-3-mini-4k-instruct.Q4_K_M.gguf",
          "size_mb": 2200,
          "params_billions": 3.8,
          "expected_tokens_per_sec": 4,
          "notes": "More efficient than Llama-2-7B for CPU-only"
        },
        "tts": {"name": "en_US-lessac-medium.onnx"}
      }
    },
    
    "HEAVY_CPU": {
      "description": "32GB+ RAM, 16+ cores, modern CPU (AVX2+), NO GPU",
      "requirements": {"min_ram_gb": 32, "min_cpu_cores": 16, "gpu_required": false},
      "cpu_benchmark_threshold": 5.0,
      "expectations": {
        "stt_latency_sec": 2,
        "llm_latency_sec": 18,
        "tts_latency_sec": 3,
        "two_way_summary": "20-25 seconds per turn; max CPU-only performance",
        "recommended_concurrent_calls": 2,
        "notes": "Still slower than MEDIUM_GPU; consider hybrid for production"
      },
      "models": {
        "stt": {"name": "vosk-model-en-us-0.22"},
        "llm": {
          "name": "llama-2-7b-chat.Q4_K_M.gguf",
          "size_mb": 3900,
          "params_billions": 7,
          "expected_tokens_per_sec": 2.5,
          "notes": "7B is sweet spot for CPU-only; 13B causes event loop blocking"
        },
        "tts": {"name": "en_US-lessac-high.onnx"}
      }
    },
    
    "MEDIUM_GPU": {
      "description": "16GB+ RAM, 4+ cores, GPU with 6GB+ VRAM",
      "requirements": {"min_ram_gb": 16, "min_cpu_cores": 4, "gpu_required": true, "min_gpu_vram_gb": 6},
      "expectations": {
        "stt_latency_sec": 2,
        "llm_latency_sec": 5,
        "tts_latency_sec": 2,
        "two_way_summary": "8-12 seconds per turn; production-ready",
        "recommended_concurrent_calls": 4
      },
      "models": {
        "stt": {"name": "vosk-model-en-us-0.22"},
        "llm": {
          "name": "llama-2-7b-chat.Q4_K_M.gguf",
          "size_mb": 3900,
          "params_billions": 7,
          "expected_tokens_per_sec": 15,
          "gpu_layers": -1
        },
        "tts": {"name": "en_US-lessac-high.onnx"}
      }
    },
    
    "HEAVY_GPU": {
      "description": "32GB+ RAM, 8+ cores, GPU with 12GB+ VRAM",
      "requirements": {"min_ram_gb": 32, "min_cpu_cores": 8, "gpu_required": true, "min_gpu_vram_gb": 12},
      "expectations": {
        "stt_latency_sec": 2,
        "llm_latency_sec": 8,
        "tts_latency_sec": 2,
        "two_way_summary": "10-15 seconds per turn; high-quality production",
        "recommended_concurrent_calls": 8
      },
      "models": {
        "stt": {"name": "vosk-model-en-us-0.22"},
        "llm": {
          "name": "llama-2-13b-chat.Q4_K_M.gguf",
          "size_mb": 7300,
          "params_billions": 13,
          "expected_tokens_per_sec": 12,
          "gpu_layers": -1,
          "notes": "Only use with GPU; CPU-only will block event loop"
        },
        "tts": {"name": "en_US-lessac-high.onnx"}
      }
    }
  }
}
```

---

## Implementation: CPU Benchmarking

### Quick Inference Test (added to `model_setup.py`)

```python
def benchmark_cpu_inference() -> float:
    """
    Run a quick 1-second inference test with TinyLlama to measure CPU performance.
    Returns tokens/second score.
    """
    try:
        import tempfile
        from llama_cpp import Llama
        
        # Download tiny test model if needed
        test_model_path = Path("models/llm/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf")
        if not test_model_path.exists():
            print("Downloading benchmark model (570MB)...")
            download_file(
                "https://huggingface.co/jartine/tinyllama-1.1b-chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
                test_model_path,
                "tinyllama-benchmark"
            )
        
        # Load model
        model = Llama(
            model_path=str(test_model_path),
            n_ctx=256,
            n_threads=max(1, os.cpu_count() // 2),
            n_batch=128,
            verbose=False
        )
        
        # Run quick inference
        import time
        start = time.time()
        output = model("Hello, how are you?", max_tokens=20, temperature=0.1)
        elapsed = time.time() - start
        
        # Calculate tokens/sec
        tokens_generated = len(output['choices'][0]['text'].split())
        tokens_per_sec = tokens_generated / elapsed if elapsed > 0 else 0
        
        print(f"CPU benchmark: {tokens_per_sec:.1f} tokens/sec")
        return tokens_per_sec
        
    except Exception as e:
        print(f"Benchmark failed: {e}")
        return 0.0  # Conservative fallback
```

---

## GPU Detection Enhancement

```python
def detect_gpu() -> dict:
    """Detect GPU availability and capabilities."""
    gpu_info = {
        "available": False,
        "vram_gb": 0,
        "name": None,
        "cuda_available": False
    }
    
    # Try NVIDIA (CUDA)
    try:
        import subprocess
        output = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        lines = output.decode().strip().split('\n')
        if lines:
            parts = lines[0].split(',')
            gpu_info["available"] = True
            gpu_info["name"] = parts[0].strip()
            gpu_info["vram_gb"] = int(float(parts[1].strip()) / 1024)
            gpu_info["cuda_available"] = True
    except Exception:
        pass
    
    # Try AMD (ROCm)
    if not gpu_info["available"]:
        try:
            output = subprocess.check_output(["rocm-smi", "--showmeminfo", "vram"])
            # Parse ROCm output
            gpu_info["available"] = True
        except Exception:
            pass
    
    return gpu_info
```

---

## Your Server's Correct Classification

### Current (Wrong):
```
39GB RAM + 16 cores → HEAVY tier → Llama-2-13B → 135s warmup ❌
```

### With Improved Logic:
```
39GB RAM + 16 cores + NO GPU + Intel Xeon 2014 (benchmark ~2.5 tok/s)
↓
Classification: HEAVY_CPU tier
↓
Model: Llama-2-7B (NOT 13B)
↓
Expected: 18-20s per turn (realistic) ✅
```

### Even Better (Hybrid):
```
Classification: Use hybrid_support
↓
STT: Local (vosk-model-en-us-0.22)
LLM: Cloud (GPT-4o-mini)
TTS: Cloud (Deepgram Aura)
↓
Expected: <5s per turn ✅✅✅
```

---

## Summary of Changes Needed

### 1. Update `registry.json`
- Split tiers into CPU vs GPU variants
- Add realistic latency expectations for CPU-only
- Cap CPU-only at Llama-2-7B (not 13B)
- Add MINIMAL tier recommending hybrid

### 2. Enhance `model_setup.py`
- Add `detect_gpu()` function
- Add `benchmark_cpu_inference()` function
- Update `determine_tier()` to consider GPU + CPU performance
- Warn users if hardware doesn't match tier expectations

### 3. Update Install Messaging
```bash
# During install
print("Detected: 39GB RAM, 16 cores, NO GPU, CPU score: 2.5")
print("Recommendation: MEDIUM_CPU tier (Phi-3-mini)")
print("Alternative: hybrid_support pipeline (5s vs 15s latency)")
```

---

## Immediate Fix for Your Server

**Option A: Switch to Phi-3-mini (Best CPU-only)**
```bash
# 3.8B parameters, more efficient than Llama-2-7B
LOCAL_LLM_MODEL_PATH=/app/models/llm/phi-3-mini-4k-instruct.Q4_K_M.gguf
LOCAL_LLM_MAX_TOKENS=32
LOCAL_LLM_INFER_TIMEOUT_SEC=20
```

**Option B: Use Hybrid (Best overall)**
```yaml
active_pipeline: "hybrid_support"
# STT local, LLM/TTS cloud → <5s latency
```

**Option C: TinyLlama MVP**
```bash
./fix-local-pipeline-mvp.sh  # 10-15s latency, basic quality
```

---

Would you like me to implement these improvements to the model selection logic?
